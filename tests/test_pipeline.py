import json

from bpu import db, pipeline
from bpu.pipeline import Stage
from bpu.stages import MOCK


def stages_of(conn, job):
    return {r["stage"]: dict(r) for r in conn.execute(
        "SELECT * FROM stage_runs WHERE job_id = ? ORDER BY rowid", (job,))}


def test_mock_workflow_end_to_end(conn, cfg):
    job = pipeline.create_job(conn, "mock", topic="true size of Africa")
    assert pipeline.run(conn, cfg, job, MOCK) == "awaiting_approval"
    # nothing past the checkpoint ran
    assert "publish" not in stages_of(conn, job)

    pipeline.decide(conn, job, "owner_approval", approved=True)
    assert pipeline.run(conn, cfg, job, MOCK) == "done"

    runs = stages_of(conn, job)
    assert [s.name for s in MOCK] == list(runs)
    assert all(r["status"] == "done" for r in runs.values())
    record = json.loads((cfg["paths"]["outputs"] / f"job-{job}" / "publish_dryrun.json").read_text())
    assert record["mode"] == "dry_run"
    # dry runs are never recorded as real publications
    assert conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0] == 0
    actions = [r["action"] for r in conn.execute("SELECT action FROM audit_log")]
    assert actions[0] == "job.created" and "approval.approved" in actions and actions[-1] == "job.done"


def test_rejection_stops_the_job(conn, cfg):
    job = pipeline.create_job(conn, "mock", topic="t")
    pipeline.run(conn, cfg, job, MOCK)
    pipeline.decide(conn, job, "owner_approval", approved=False, note="weak hook")
    assert pipeline.run(conn, cfg, job, MOCK) == "rejected"
    assert "publish" not in stages_of(conn, job)


def test_transient_failure_is_retried(conn, cfg):
    calls = []

    def flaky(ctx, env):
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("network blip")
        return {"x": 1}

    job = pipeline.create_job(conn, "t")
    assert pipeline.run(conn, cfg, job, [Stage("flaky", flaky, gives=("x",))]) == "done"
    assert len(calls) == 3 and stages_of(conn, job)["flaky"]["attempts"] == 3


def test_exhausted_retries_fail_then_retry_job_resumes(conn, cfg):
    state = {"broken": True}

    def step(ctx, env):
        if state["broken"]:
            raise RuntimeError("still broken")
        return {"y": ctx["x"] + 1}

    stages = [Stage("a", lambda c, e: {"x": 1}, gives=("x",)), Stage("b", step, needs=("x",), gives=("y",))]
    job = pipeline.create_job(conn, "t")
    assert pipeline.run(conn, cfg, job, stages) == "failed"
    b = stages_of(conn, job)["b"]
    assert b["attempts"] == cfg["pipeline"]["max_attempts"] and "still broken" in b["error"]

    state["broken"] = False
    pipeline.retry_job(conn, job)
    assert pipeline.run(conn, cfg, job, stages) == "done"
    assert stages_of(conn, job)["a"]["attempts"] == 1  # checkpoint replayed, not re-run


def test_contract_violation_is_not_retried(conn, cfg):
    calls = []
    stage = Stage("bad", lambda c, e: calls.append(1) or {}, gives=("result",))
    job = pipeline.create_job(conn, "t")
    assert pipeline.run(conn, cfg, job, [stage]) == "failed"
    assert len(calls) == 1 and "did not give" in stages_of(conn, job)["bad"]["error"]


def test_missing_input_fails_before_running(conn, cfg):
    calls = []
    job = pipeline.create_job(conn, "t")
    assert pipeline.run(conn, cfg, job, [Stage("s", lambda c, e: calls.append(1), needs=("nope",))]) == "failed"
    assert not calls


def test_crash_recovery_resumes_from_checkpoint(conn, cfg):
    runs = {"a": 0}

    def a(ctx, env):
        runs["a"] += 1
        return {"x": 1}

    def crash(ctx, env):
        raise KeyboardInterrupt  # simulates the process dying mid-stage

    job = pipeline.create_job(conn, "t")
    try:
        pipeline.run(conn, cfg, job, [Stage("a", a, gives=("x",)), Stage("b", crash)])
    except KeyboardInterrupt:
        pass
    assert stages_of(conn, job)["b"]["status"] == "running"
    stages = [Stage("a", a, gives=("x",)), Stage("b", lambda c, e: {"y": c["x"]}, needs=("x",), gives=("y",))]
    assert pipeline.run(conn, cfg, job, stages) == "done"
    assert runs["a"] == 1


def test_interrupted_non_retryable_stage_is_not_repeated(conn, cfg):
    uploads = []

    def upload(ctx, env):
        uploads.append(1)
        raise KeyboardInterrupt

    job = pipeline.create_job(conn, "t")
    try:
        pipeline.run(conn, cfg, job, [Stage("upload", upload, retry=False)])
    except KeyboardInterrupt:
        pass
    assert pipeline.run(conn, cfg, job, [Stage("upload", upload, retry=False)]) == "failed"
    assert len(uploads) == 1


def test_pause_stops_before_next_stage(conn, cfg):
    def pause_after(ctx, env):
        db.set_setting(env.db, "paused", True)
        return {"x": 1}

    stages = [Stage("a", pause_after, gives=("x",)), Stage("b", lambda c, e: {"y": 2}, gives=("y",))]
    job = pipeline.create_job(conn, "t")
    assert pipeline.run(conn, cfg, job, stages) == "paused"
    assert "b" not in stages_of(conn, job)
    db.set_setting(conn, "paused", False)
    assert pipeline.run(conn, cfg, job, stages) == "done"


def test_publish_gate_refuses_mock_output_outside_dry_run(conn, cfg):
    cfg["publishing"]["mode"] = "private"
    job = pipeline.create_job(conn, "mock", topic="t")
    pipeline.run(conn, cfg, job, MOCK)
    pipeline.decide(conn, job, "owner_approval", approved=True)
    assert pipeline.run(conn, cfg, job, MOCK) == "failed"
    pub = stages_of(conn, job)["publish"]
    assert "refusing to upload mock output" in pub["error"] and pub["attempts"] == 1
