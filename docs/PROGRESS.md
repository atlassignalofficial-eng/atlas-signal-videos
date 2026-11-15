# Progress tracker

Status tags: **tested** · **implemented-unverified** · **mocked** · **blocked** · **planned**

## Milestones

| Phase | Acceptance criteria | Status |
|---|---|---|
| 0 Audit | Inventory, gaps, risks, baseline, platform requirements | **tested**: [AUDIT.md](AUDIT.md) |
| 1 Foundation | Validated config, DB and migrations, memory, orchestration, logs, CLI, tests; complete mocked workflow | **tested**: see below |
| 2 Research | Sourced niche and competitor analysis, ranked ideas, evidence-backed content plan, growth scenarios | planned |
| 3 Production | Script, storyboard, narration, assets, render, captions, thumbnail, QA; one original sample Short with no manual editing | **tested** for map Shorts (sample rendered 2026-11-15); LLM scripting **planned** |
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

## Phase 3 deliverables

| Item | Status | Evidence |
|---|---|---|
| Storyboard format (`templates/shorts/*.json`): actors, cameras, beats, claims, metadata | tested | `test_storyboard_in_repo_is_valid`, `test_plan_*` |
| True-size geometry: sphere moves keep area and north-up; Natural Earth pinned to commit `ca96624` | tested | `test_move_keeps_true_area_*`, `test_area_of_one_degree_square_*` |
| Fact-check stage: every numeric claim recomputed from map data; failure stops the job | tested | `test_claims_are_recomputed_and_can_fail`; sample: 13.72× (claim ≈14×), 22.6M of 30.0M km² |
| Narration: Azure AI Speech `andrew` (owner's choice) or local Piper (joe, john, norman); commercial-safe voices only | Piper **tested**; Azure **implemented-unverified** (request format tested offline; needs a key for a live test) | `test_azure_voice_*`, `test_only_commercially_licensed_voices_are_allowed`; en_US-ryan rejected (CC BY-NC-SA) |
| Render: 1080×1920 30 fps, 2× supersampled, captions, titles, labels, camera moves | tested | `test_tiny_render_*`; sample Short (33 s) |
| Sound: narration, ffmpeg-synth pad, whoosh per move, two-pass loudnorm to −14 LUFS | tested | `test_normalize_hits_target`; sample measured −14.5 LUFS, −1.2 dBTP |
| Video QA report (size, fps, audio, duration, loudness, peak, black frames, silence) | tested | sample: 8/8 checks passed (`outputs/job-N/qa.json`) |
| Thumbnail still, SEO validation, `upload.txt` for manual upload, `provenance.json` | tested | sample job 1 |
| Script writing by LLM (OpenAI) | planned: needs a new key and a spend cap | — |
| Long-form 16:9 workflow | planned | — |

## Verified test results
- 2026-11-15: `python -m pytest -q`: **30 passed** (about 22 s).
- 2026-11-15: CLI smoke run: `init`, `new`, `run` (stopped at approval), `approve`, `run` (done,
  17/17 stages), `snapshot` (live API), `backup`, `pause`, `resume`, `log`. All as expected.
- 2026-11-15: `bpu new --kind short --template true-size-africa` then `run`: 7 stages done in about 4 min
  (4 CPU), stopped at approval; `approve` and `run` gave a dry-run publish package. QA 8/8.

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
- **Rendering: Pillow and ffmpeg**, not Remotion, Manim or MoviePy. Flat 2D map animation needs
  only polygon drawing; the others add Node, LaTeX or heavy dependencies for no gain here.
  Revisit for 3D or long-form explainers.
- **TTS: Microsoft Azure AI Speech, voice en-US-AndrewNeural** (owner's choice, 2026-11-15).
  Uses the official REST API on the free F0 tier (0.5M characters/month, commercial use of
  output allowed). edge-tts was rejected: it uses the Edge read-aloud service, which isn't
  licensed for commercial use, and it needs WebSocket. Piper remains a free offline fallback.
- **Honest packing:** countries placed inside Africa still overlap a little (no layout fits
  without rotation), so the narration claims only what the area check proves.
- **OAuth stays in Testing** (owner, 2026-11-15): "Publish app" stayed disabled. The owner
  uploads finished videos manually from `upload.txt`; the sign-in is renewed weekly for stats.

## Blockers
1. **`main` branch**: the work is on `claude/blueprints-foundation` and must be merged before
   Actions can be triggered.
2. **Repository secrets** not set yet (`YT_*`, `OPENAI_API_KEY`, `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`).
   Without the Azure secrets the sample Short stops at the voice stage.
3. **OAuth Testing mode**: the refresh token expires after 7 days, so the daily snapshot fails
   until the owner signs in again.
4. **OpenAI key**: the first key was pasted in chat and must be revoked. A new one goes in
   repo secrets only. A monthly spend cap must be agreed before any paid call is coded to run.

## Next actions
1. Owner: create the Azure Speech resource (Free F0) and add its key and region as secrets; review the sample; merge PR #1.
2. Run `new` with `template=true-size-africa` on GitHub Actions to verify the cloud render.
3. Phase 2: research stage (public data on competitors and outliers) and a ranked idea list.
4. LLM storyboard writer (OpenAI, under a spend cap) so new map Shorts don't need hand-written JSON.
