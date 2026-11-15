# Progress tracker

Status tags: **tested** · **implemented-unverified** · **mocked** · **blocked** · **planned**

## Milestones

| Phase | Acceptance criteria | Status |
|---|---|---|
| 0 Audit | Inventory, gaps, risks, baseline, platform requirements | **tested**: [AUDIT.md](AUDIT.md) |
| 1 Foundation | Validated config, DB and migrations, memory, orchestration, logs, CLI, tests; complete mocked workflow | **tested**: see below |
| 2 Research | Sourced niche and competitor analysis, ranked ideas, evidence-backed content plan, growth scenarios | planned |
| 3 Production | Script, storyboard, narration, assets, render, captions, thumbnail, QA; one original sample Short with no manual editing | planned |
| 4 Publishing | Upload with approval, explicit privacy, quota tracking, duplicate prevention; private test upload with permission | planned (gate logic tested) |
| 5 Analytics | Real metrics (Data API plus Analytics API), baselines, experiments, reports | planned (stats snapshot tested) |
| 6 Hardening | Security review, recovery, backups, deployment, cost controls, runbooks | planned |

## Phase 1 deliverables

| Item | Status | Evidence |
|---|---|---|
| Config load and validation (`bpu/config.py`) | tested | `test_config_validation` |
| SQLite and numbered migrations, rollback on failure | tested | `test_migrations_*`, `test_failed_migration_rolls_back` |
| Project memory: dedup, corrections, expiry, provenance | tested | `test_memory_dedup_correction_and_expiry` |
| Workflow engine: checkpoints, retries with backoff, contracts | tested | `test_transient_failure_is_retried`, `test_contract_violation_is_not_retried` |
| Crash recovery and non-repeatable stages | tested | `test_crash_recovery_*`, `test_interrupted_non_retryable_*` |
| Owner approval checkpoint (approve and reject) | tested | `test_mock_workflow_end_to_end`, `test_rejection_stops_the_job` |
| Pause and resume of all automation | tested | `test_pause_stops_before_next_stage`, CLI smoke run |
| Publishing gate (dry run, refuses mock output, duplicate hash check) | tested (dry run); real upload **planned** | `test_publish_gate_*` |
| Audit log and file log | tested | CLI smoke run (`bpu log`) |
| Backup | tested | `test_settings_and_backup`, CLI smoke run |
| 17 content stages, research to learn | **mocked**: placeholders tagged `"mock": true` | — |
| YouTube OAuth and stats snapshot | tested offline and live | `test_youtube.py`; live `bpu snapshot` on 2026-11-15 returned 2 subscribers and 1 video |
| GitHub Actions runner (dispatch commands, daily snapshot, DB on `state` branch) | implemented-unverified: state restore and save simulated locally across 3 runs; not yet run on GitHub | — |
| Dashboard | planned (CLI `status`, `approve`, `pause` serve as the interface for now) | — |

## Verified test results
- 2026-11-15: `python -m pytest -q`: **18 passed**.
- 2026-11-15: CLI smoke run: `init`, `new`, `run` (stopped at approval), `approve`, `run` (done,
  17/17 stages), `snapshot` (live API), `backup`, `pause`, `resume`, `log`. All as expected.

## Decisions
- **Stdlib-only Python and SQLite and ffmpeg.** Runs on Termux and GitHub Actions without
  compiled dependencies. Add a dependency only when a phase needs it.
- **Own small workflow engine** (`bpu/pipeline.py`, about 170 lines) instead of
  Prefect, Temporal or Airflow. Those need servers or heavy installs, and a SQLite
  checkpoint table gives durability, retries and resume.
- **No FastAPI or dashboard yet.** The CLI covers review, approval and pause. Add a tiny
  stdlib web page when the owner needs to approve from a phone browser.
- **`publishing.mode = dry_run`** is the shipped default, and a test enforces it.
- **Runtime: GitHub Actions** (owner decision, 2026-11-15). The DB persists on the `state`
  branch rather than in a cache (evictable) or artifacts (expire).
- **LLM provider: OpenAI** (owner supplied a key) instead of Gemini. It is paid, so usage
  needs a spend cap and per-run cost logging.

## Blockers
1. **Push access**: the collaborator invite for `prashant-rajpu` must be accepted, and the
   Claude GitHub App needs access to `atlas-signal-videos`.
2. **Repository secrets** not set yet (`YT_*`, `OPENAI_API_KEY`).
3. **OAuth Testing mode**: refresh tokens expire after 7 days, which breaks unattended runs.
   Publish the consent screen to "In production", then sign in again for a long-lived token.
4. **OpenAI key**: the first key was pasted in chat and must be revoked. A new one goes in
   repo secrets only. A monthly spend cap must be agreed before any paid call is coded to run.

## Next actions
1. Resolve the push target, then push.
2. Phase 3 first (owner priority): a real `short` pipeline that renders the Africa
   true-size Short (map animation, narration, captions, loudness -14 LUFS), with QA checks.
3. Phase 2 research stage: competitor and outlier study via public data and a ranked idea list.
