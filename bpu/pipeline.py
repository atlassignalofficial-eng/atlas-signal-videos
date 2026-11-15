"""Durable workflow engine.

A job runs an ordered list of Stages. Every stage result is checkpointed in
stage_runs, so `run()` can be called again after a crash, a failure, a pause
or an approval and it continues where it stopped. Stages talk through one
context dict: each stage declares the keys it `needs` and the keys it `gives`,
and the engine enforces both.
"""
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from . import db

log = logging.getLogger("bpu.pipeline")


@dataclass(frozen=True)
class Stage:
    name: str
    fn: Callable[[dict, SimpleNamespace], dict] | None
    needs: tuple = ()
    gives: tuple = ()
    approval: bool = False  # owner checkpoint: fn is ignored, run() stops until decided
    retry: bool = True      # False for stages that must never repeat (uploads)


class ContractError(Exception):
    """A stage was wired wrong: missing inputs or outputs. Never retried."""


def create_job(conn, kind: str, **inputs) -> int:
    job_id = conn.execute("INSERT INTO jobs (kind, input) VALUES (?, ?)",
                          (kind, json.dumps(inputs))).lastrowid
    db.audit(conn, "system", "job.created", job_id=job_id, kind=kind)
    return job_id


def decide(conn, job_id: int, stage: str, approved: bool, note: str | None = None, actor="owner"):
    """Record the owner's decision for an approval stage."""
    decision = "approved" if approved else "rejected"
    conn.execute("INSERT INTO approvals (job_id, stage, decision, note) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT (job_id, stage) DO UPDATE SET decision = excluded.decision, "
                 "note = excluded.note, decided_at = datetime('now')",
                 (job_id, stage, decision, note))
    db.audit(conn, actor, f"approval.{decision}", job_id=job_id, stage=stage, note=note)


def retry_job(conn, job_id: int) -> None:
    """Give a failed job a fresh set of attempts on its failed stage."""
    conn.execute("UPDATE stage_runs SET status = 'running', attempts = 0, error = NULL "
                 "WHERE job_id = ? AND status = 'failed'", (job_id,))
    _set_job(conn, job_id, "pending")
    db.audit(conn, "owner", "job.retry", job_id=job_id)


def is_paused(conn) -> bool:
    return bool(db.get_setting(conn, "paused", False))


def run(conn, cfg: dict, job_id: int, stages: list[Stage], sleep=time.sleep) -> str:
    """Advance a job as far as it can go. Returns the job's resulting status."""
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise KeyError(f"no job {job_id}")
    if job["status"] in ("done", "rejected", "failed"):
        return job["status"]

    out_dir = Path(cfg["paths"]["outputs"]) / f"job-{job_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    env = SimpleNamespace(db=conn, cfg=cfg, job_id=job_id, out_dir=out_dir)
    ctx = json.loads(job["input"])
    max_attempts = cfg["pipeline"]["max_attempts"]
    backoff = cfg["pipeline"]["retry_backoff_seconds"]

    for st in stages:
        row = conn.execute("SELECT * FROM stage_runs WHERE job_id = ? AND stage = ?",
                           (job_id, st.name)).fetchone()
        if row and row["status"] == "done":
            ctx.update(json.loads(row["output"]))
            continue
        if is_paused(conn):
            return _set_job(conn, job_id, "paused")
        _set_job(conn, job_id, "running")

        if st.approval:
            status = _approval(conn, job_id, st, ctx)
            if status != "done":
                return status
            continue

        missing = [k for k in st.needs if k not in ctx]
        if missing:
            return _fail(conn, job_id, st, row["attempts"] if row else 0,
                         ContractError(f"needs missing keys {missing}"))

        attempts = row["attempts"] if row else 0
        if row and row["status"] == "running" and not st.retry and attempts:
            # Interrupted mid-way through a stage that must not repeat (e.g. an upload).
            return _fail(conn, job_id, st, attempts, RuntimeError(
                "interrupted during a non-retryable stage; check YouTube Studio, then retry"))
        limit = max_attempts if st.retry else 1
        while True:
            attempts += 1
            _stage(conn, job_id, st.name, "running", attempts)
            try:
                out = st.fn(ctx, env)
                if not isinstance(out, dict):
                    raise ContractError(f"returned {type(out).__name__}, expected dict")
                lacking = [k for k in st.gives if k not in out]
                if lacking:
                    raise ContractError(f"did not give {lacking}")
            except Exception as e:  # noqa: BLE001 - every failure is recorded, not lost
                log.warning("job %s stage %s attempt %s failed: %s", job_id, st.name, attempts, e)
                if isinstance(e, ContractError) or attempts >= limit:
                    return _fail(conn, job_id, st, attempts, e)
                _stage(conn, job_id, st.name, "running", attempts, error=repr(e))
                sleep(backoff * 2 ** (attempts - 1))
                continue
            _stage(conn, job_id, st.name, "done", attempts, output=out)
            ctx.update(out)
            break

    db.audit(conn, "system", "job.done", job_id=job_id)
    return _set_job(conn, job_id, "done")


def _approval(conn, job_id, st, ctx) -> str:
    decision = conn.execute("SELECT * FROM approvals WHERE job_id = ? AND stage = ?",
                            (job_id, st.name)).fetchone()
    if decision is None:
        _stage(conn, job_id, st.name, "awaiting_approval", 0)
        db.audit(conn, "system", "approval.requested", job_id=job_id, stage=st.name)
        return _set_job(conn, job_id, "awaiting_approval")
    if decision["decision"] == "rejected":
        _stage(conn, job_id, st.name, "failed", 0, error=f"rejected: {decision['note']}")
        return _set_job(conn, job_id, "rejected")
    out = {f"{st.name}_approved": True}
    _stage(conn, job_id, st.name, "done", 0, output=out)
    ctx.update(out)
    return "done"


def _fail(conn, job_id, st, attempts, err) -> str:
    _stage(conn, job_id, st.name, "failed", attempts, error=f"{type(err).__name__}: {err}")
    db.audit(conn, "system", "stage.failed", job_id=job_id, stage=st.name, error=str(err))
    return _set_job(conn, job_id, "failed")


def _stage(conn, job_id, stage, status, attempts, output=None, error=None):
    conn.execute(
        "INSERT INTO stage_runs (job_id, stage, status, attempts, output, error) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (job_id, stage) DO UPDATE SET "
        "status = excluded.status, attempts = excluded.attempts, output = excluded.output, "
        "error = excluded.error, updated_at = datetime('now')",
        (job_id, stage, status, attempts,
         json.dumps(output, default=str) if output is not None else None, error))


def _set_job(conn, job_id, status) -> str:
    conn.execute("UPDATE jobs SET status = ?, updated_at = datetime('now') WHERE id = ?",
                 (status, job_id))
    return status
