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

## Docs
- [MASTER_PROMPT.md](MASTER_PROMPT.md): full specification
- [CLAUDE.md](CLAUDE.md): architecture, commands, conventions
- [docs/PROGRESS.md](docs/PROGRESS.md): milestones, status, blockers
- [docs/AUDIT.md](docs/AUDIT.md): baseline, feasibility, platform requirements
