# BLUEPRINTS UNCOVERED

AI-assisted production system for the faceless YouTube channel
[@blueprintsuncovered](https://www.youtube.com/@blueprintsuncovered): *the engineering
behind our world*. It covers Shorts and long videos, built with free and open-source tools.

**Goal:** 10,000 genuine subscribers. Growth comes from original, well-researched,
engaging videos, never from fake engagement.

**How it works:** research → ideas → script → fact-check → voice → visuals → render →
QA → SEO → **owner approval** → publish → analytics → learn. Every step is checkpointed
in SQLite, so the system can stop and resume safely. Nothing goes public without the
owner's approval.

## Quick start
```bash
python3 -m pytest -q          # needs: pip install pytest
python3 -m bpu init
python3 -m bpu new --topic "true size of Africa"
python3 -m bpu run 1
python3 -m bpu status 1
```
Requires Python 3.11+ and ffmpeg. There are no other dependencies yet.

YouTube access: put the Desktop-app OAuth file at `data/secrets/client_secret.json`,
then run `python3 -m bpu auth-url` and follow the link, then
`python3 -m bpu auth-code '<the localhost URL you were sent to>'`.

## Make a Short
```bash
pip install pillow==12.3.0 piper-tts==1.8.0   # plus ffmpeg
python3 -m bpu new --kind short --template true-size-africa   # prints the job id
python3 -m bpu run <id>        # renders and runs QA, then stops for your approval
```
The job folder `outputs/job-<id>/` holds the video, thumbnail, `upload.txt` (title,
description and tags), `qa.json` and `provenance.json`.

## Running on GitHub Actions
The `bpu` workflow (`.github/workflows/bpu.yml`) is the main way to run this.
- **Control it:** Actions → bpu → Run workflow, then pick a command (status, new, run,
  approve, reject, retry, pause, resume, snapshot, log). The result appears in the run summary.
- **Schedule:** a stats snapshot runs daily.
- **State:** the SQLite database is kept on the `state` branch, one commit per run.
- **Repository secrets** (Settings → Secrets and variables → Actions):
  `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`, `OPENAI_API_KEY`,
  `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` (narration voice).

## Docs
- [MASTER_PROMPT.md](MASTER_PROMPT.md): full specification
- [CLAUDE.md](CLAUDE.md): architecture, commands, conventions
- [docs/PROGRESS.md](docs/PROGRESS.md): milestones, status, blockers
- [docs/AUDIT.md](docs/AUDIT.md): baseline, feasibility, platform requirements
