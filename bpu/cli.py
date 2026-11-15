"""Command line: `python -m bpu <command>`. Run with -h for the list."""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from . import config, db, pipeline
from .stages import PIPELINES


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="bpu", description="Blueprints Uncovered production system")
    p.add_argument("--config", help="path to settings.toml")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create/migrate the database")
    n = sub.add_parser("new", help="create a job")
    n.add_argument("--kind", default="mock", choices=sorted(PIPELINES))
    n.add_argument("--topic", default="placeholder topic")
    for name in ("run", "retry"):
        sub.add_parser(name, help=f"{name} a job").add_argument("job", type=int)
    a = sub.add_parser("approve", help="approve (or --reject) a job's waiting checkpoint")
    a.add_argument("job", type=int)
    a.add_argument("--reject", action="store_true")
    a.add_argument("--note")
    sub.add_parser("status", help="jobs, or one job's stages").add_argument("job", type=int, nargs="?")
    sub.add_parser("pause", help="stop all automation before its next stage")
    sub.add_parser("resume", help="allow automation again")
    sub.add_parser("log", help="recent audit log").add_argument("-n", type=int, default=20)
    sub.add_parser("backup", help="copy the database to the backups folder")
    sub.add_parser("snapshot", help="store current YouTube channel/video stats")
    sub.add_parser("auth-url", help="print the YouTube sign-in link")
    sub.add_parser("auth-code", help="finish sign-in").add_argument("redirected_url")
    args = p.parse_args(argv)

    cfg = config.load(args.config)
    cfg["paths"]["logs"].mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=cfg["paths"]["logs"] / "bpu.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    conn = db.connect(cfg["paths"]["db"])
    return COMMANDS[args.cmd](conn, cfg, args) or 0


def _init(conn, cfg, args):
    print(f"database ready at schema v{db.migrate(conn)}: {cfg['paths']['db']}")


def _new(conn, cfg, args):
    print(pipeline.create_job(conn, args.kind, topic=args.topic))


def _run(conn, cfg, args):
    kind = _job(conn, args.job)["kind"]
    status = pipeline.run(conn, cfg, args.job, PIPELINES[kind])
    print(f"job {args.job}: {status}")
    return 0 if status in ("done", "awaiting_approval", "paused") else 1


def _retry(conn, cfg, args):
    pipeline.retry_job(conn, args.job)
    return _run(conn, cfg, args)


def _approve(conn, cfg, args):
    waiting = conn.execute("SELECT stage FROM stage_runs WHERE job_id = ? AND "
                           "status = 'awaiting_approval'", (args.job,)).fetchone()
    if not waiting:
        print(f"job {args.job} is not waiting for approval", file=sys.stderr)
        return 1
    pipeline.decide(conn, args.job, waiting["stage"], not args.reject, args.note)
    print(f"job {args.job} {waiting['stage']}: {'rejected' if args.reject else 'approved'}"
          " - run it again to continue")


def _status(conn, cfg, args):
    print(f"automation: {'PAUSED' if pipeline.is_paused(conn) else 'active'}"
          f"   publishing mode: {cfg['publishing']['mode']}")
    if args.job is None:
        for r in conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 20"):
            print(f"{r['id']:>4}  {r['kind']:<8} {r['status']:<18} {r['updated_at']}")
        return
    _job(conn, args.job)
    for r in conn.execute("SELECT * FROM stage_runs WHERE job_id = ? ORDER BY rowid", (args.job,)):
        err = f"  {r['error']}" if r["error"] else ""
        print(f"{r['stage']:<16} {r['status']:<18} tries={r['attempts']}{err}")


def _pause(conn, cfg, args, value=True):
    db.set_setting(conn, "paused", value)
    db.audit(conn, "owner", "automation.paused" if value else "automation.resumed")
    print("automation", "paused" if value else "resumed")


def _log(conn, cfg, args):
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (args.n,)).fetchall()
    for r in reversed(rows):
        print(r["at"], r["actor"], r["action"], r["detail"] or "")


def _backup(conn, cfg, args):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(db.backup(conn, cfg["paths"]["backups"] / f"bpu-{stamp}.sqlite3"))


def _yt(cfg):
    from .youtube import YouTube
    return YouTube(cfg["paths"]["secrets"])


def _snapshot(conn, cfg, args):
    from .youtube import snapshot
    stats = snapshot(conn, _yt(cfg))
    db.audit(conn, "system", "analytics.snapshot", **stats)
    print(json.dumps(stats))


def _job(conn, job_id):
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise SystemExit(f"no job {job_id}")
    return row


COMMANDS = {
    "init": _init, "new": _new, "run": _run, "retry": _retry, "approve": _approve,
    "status": _status, "pause": _pause,
    "resume": lambda c, cfg, a: _pause(c, cfg, a, value=False),
    "log": _log, "backup": _backup, "snapshot": _snapshot,
    "auth-url": lambda c, cfg, a: print(_yt(cfg).auth_url()),
    "auth-code": lambda c, cfg, a: _yt(cfg).exchange(a.redirected_url) or print("signed in"),
}
