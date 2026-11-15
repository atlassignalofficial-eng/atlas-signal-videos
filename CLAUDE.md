# Blueprints Uncovered — working notes for Claude

Read this file, then [docs/PROGRESS.md](docs/PROGRESS.md), at the start of every
session. Update PROGRESS.md (status, test results, blockers, next actions) at the end.
The full specification is [MASTER_PROMPT.md](MASTER_PROMPT.md).

## Mission
An AI-assisted production system for the faceless YouTube channel BLUEPRINTS
UNCOVERED (@blueprintsuncovered): the engineering behind our world. Goal: genuine
growth toward 10,000 subscribers and sustainable income. Never promise results;
never fake engagement.

## Architecture
- `bpu/config.py`: loads and validates `config/settings.toml` (paths resolve from the project root).
- `bpu/db.py`: SQLite connection, numbered migrations in `bpu/migrations/`, audit log, settings, backup.
- `bpu/memory.py`: long-term project memory (dedup, corrections via `superseded_by`, expiry).
- `bpu/pipeline.py`: durable workflow engine. Stages are checkpointed in `stage_runs`,
  declare `needs` and `gives`, retry with backoff, and can be approval gates or non-retryable.
- `bpu/stages.py`: stage lists per job kind (`PIPELINES`). Content stages are mocks in Phase 1.
- `bpu/youtube.py`: YouTube Data API over OAuth, stdlib only; `snapshot()` stores stats.
- `bpu/cli.py`: `python -m bpu …`

## Commands
```bash
python -m pytest -q                 # all tests: run before every commit
python -m bpu init                  # create or migrate the DB
python -m bpu new --kind mock --topic "…"   # create a job -> prints id
python -m bpu run <job>             # advance until done, approval, pause or failure
python -m bpu approve <job> [--reject --note "…"]
python -m bpu status [<job>]        # jobs, or one job's stages
python -m bpu pause | resume        # kill switch for all automation
python -m bpu snapshot              # live channel and video stats into the DB
python -m bpu backup | log
python -m bpu auth-url | auth-code '<redirected localhost url>'
```

## Conventions
- **Stdlib first.** No new dependency without a phase needing it; pin it in `pyproject.toml`.
  It must install on Termux (aarch64).
- **Never edit a shipped migration.** Add `bpu/migrations/000N_*.sql`.
- New stage: a function `(ctx, env) -> dict`, registered with exact `needs` and `gives`.
  Uploads and other external side effects use `retry=False`.
- Mocks must say so: return `{"mock": True, …}` and stay labelled "mocked" in PROGRESS.md.
- Every real external action writes an `audit_log` row.

## Security
- Secrets live only in `data/secrets/` (gitignored, mode 600): `client_secret.json`, `token.json`.
  `data/`, `outputs/`, `logs/` and media are never committed.
- Subprocess calls use argument lists, never `shell=True`.
- Keep personal information about the owner out of the repo.

## Approval checkpoints (ask the owner first)
Public publishing (every job has an `owner_approval` stage; `publishing.mode` ships as
`dry_run`), spending money or enabling paid APIs, deleting data, rebranding or repositioning
the channel, permission changes, and sharing private data.
Free to do without asking: research, code, tests, local drafts and renders, analysis.

## YouTube API facts (checked 2026-11-15; re-verify when relevant)
- Always set `status.privacyStatus` on upload: it defaults to **public**.
- Uploads from unverified projects reportedly no longer forced private (revision 2026-11-02).
- OAuth app in Testing mode, so the refresh token expires after 7 days.
- YPP thresholds rise on 2027-02-01 (see docs/AUDIT.md).

## Current status
Phase 0 and Phase 1 are done and tested (18 tests). Next: Phase 3 sample Short. See docs/PROGRESS.md.
