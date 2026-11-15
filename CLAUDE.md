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
- `bpu/stages.py`: stage lists per job kind (`PIPELINES`): `mock` (Phase 1) and `short` (real).
- `bpu/geo.py`: Natural Earth countries (pinned commit), true areas, true-size sphere moves, Mercator.
- `bpu/tts.py`: narration via Azure AI Speech (`andrew`, default) or local Piper; only commercially licensed voices.
- `bpu/short.py`: storyboard to fact-check to narration to frames (Pillow) to mp4 (ffmpeg), plus QA.
- `templates/shorts/*.json`: storyboards (actors, cameras, beats, claims, metadata).
- `bpu/youtube.py`: YouTube Data API over OAuth, stdlib only; `snapshot()` stores stats.
- `bpu/cli.py`: `python -m bpu …`
- `.github/workflows/bpu.yml`: production runtime (GitHub Actions). The DB lives on the
  `state` branch, and secrets come from repo secrets, written to `data/secrets/` per run.

## Commands
```bash
python -m pytest -q                 # all tests: run before every commit
python -m bpu init                  # create or migrate the DB
python -m bpu new --kind mock --topic "…"   # create a job -> prints id
python -m bpu new --kind short --template true-size-africa   # real Short job
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
  The engine is stdlib-only. Rendering needs the `render` extra (Pillow, piper-tts) and ffmpeg.
- **Every on-screen number needs a `checks` entry** in its storyboard; editorial QA recomputes it.
- **Voices:** add one to `tts.VOICES` only after reading its MODEL_CARD licence (commercial use).
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
Phases 0, 1 and 3 (map Shorts) are done and tested (28 tests). The sample Short was rendered locally.
The Actions runner is not yet run on GitHub. Next: Phase 2 research, then the LLM storyboard writer. See docs/PROGRESS.md.
