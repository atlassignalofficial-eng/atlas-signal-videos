# Phase 0 — Audit (2026-11-15)

## Repository
`atlassignalofficial-eng/atlas-signal-videos` held only a README with the channel
brief. No code, config, docs or tests. This repository is the first code.

Related earlier repos by the owner, inspected for reuse:

| Repo | Useful parts | Notes |
|---|---|---|
| `prashant-rajpu/youtube-automation` | `tts.py` (Piper with espeak-ng fallback), `music.py` (ffmpeg synth pad / looped bed) | Ideas reused in Phase 3 |
| `prashant-rajpu/idlevelocity-shorts-automation` | Edge-TTS voice, procedural SFX, sidechain-ducked BGM, GitHub Actions publish workflow | Shows the owner's runtime: **Termux on Android (aarch64)** and GitHub Actions |

## Channel baseline (verified via YouTube Data API, 2026-11-15)
- Channel `UCumLp5-bwnu8TnCo216uA6A`, handle `@blueprintsuncovered`, created 2026-11-07.
- 2 subscribers, 1 public video, about 1,450 views.
- Video `psfRWxkwNyI` "How Big Africa REALLY Is!": a 10 s Short, about 1,450 views, 6 likes, 0 comments
  in its first day. The visual is a near-static map; the promised reveal never appears.
  Audio at -26 LUFS (YouTube norm is about -14).
- Phone verified (long uploads eligible). Not monetised.
- Not available through this API: impressions, CTR, retention, swipe-away rate, revenue.
  These need the YouTube Analytics API (scope `yt-analytics.readonly`, planned for Phase 5).

## Goal feasibility (from real data, not a forecast)
- Target: 10,000 subscribers by 2027-01-01. That is 47 days from today, so the channel
  needs about **213 net new subscribers per day** starting now.
- Observed conversion: 2 subscribers from about 1,450 views (about 0.14%). One video is
  too small a sample to plan on. At that rate, 10,000 subscribers needs roughly
  7 million views in 47 days.
- Assessment: **very unlikely** from this baseline. It is not impossible: a single viral
  Short can deliver it. Recommended staging:
  1. 1,000 subscribers (the monetisation gate).
  2. Monetisation eligibility.
  3. 10,000 as the stretch goal.

  Conservative, base and optimistic scenarios are built in Phase 2, once there are more
  than one video's worth of data.

## Platform requirements checked (2026-11-15)
- **YPP standard**: 1,000 subscribers plus either 4,000 watch hours in 12 months or
  10M Shorts views in 90 days. Requires 2-Step Verification and AdSense.
  **From 2027-02-01 new applicants need 8,000 watch hours or 20M Shorts views**,
  still with 1,000 subscribers.
  A country-limited expanded tier exists (500 subscribers plus 3,000 hours or 3M Shorts
  views); UAE eligibility is unverified.
  Shorts-feed watch time does not count toward the watch-hours path.
  Source: https://support.google.com/youtube/answer/72851,
  https://support.google.com/youtube/answer/12843009
- **API uploads from unverified projects**: the 2026-11-02 revision history says they are
  **no longer forced private**, which reverses the July 2020 policy. Some reference pages
  still show the old rule. To verify with a private test upload in Phase 4.
  Source: https://developers.google.com/youtube/v3/revision_history
- `videos.insert` defaults to **public** when `privacyStatus` is unset. The publisher must
  always set it explicitly.
- Quota is moving to a granular system starting with `videos.insert` and `search.list`
  (revision 2026-06-01). Track quota usage in Phase 4.
- The OAuth consent screen is in "Testing" mode, so refresh tokens expire after 7 days.
  The owner re-signs in, or publishes the app.

## Environment
- Dev and CI container: Python 3.13, ffmpeg 6.1, 4 CPU, 15 GB RAM, no GPU.
- Owner runtime (inferred from earlier repos, **to confirm**): Android, Termux, aarch64.
  Because of this, Phase 1 is stdlib-only, with no compiled dependencies.

## Credentials
| Credential | State |
|---|---|
| YouTube OAuth client (Desktop) | Provided, stored in `data/secrets/` (gitignored), working |
| YouTube token (`youtube.force-ssl`) | Working; expires within 7 days (Testing mode) |
| Gemini API key | Not provided; needed for Phase 2 scripting |
| YouTube Analytics API | Not enabled; needed for Phase 5 retention and CTR |
| GitHub push to `atlas-signal-videos` | **Blocked**: the connected account has no push access |

## Risks
1. **Inauthentic or mass-produced content policy.** Templated AI channels get refused
   monetisation. Mitigation: original research, owner review of every video, varied formats.
2. **Deadline.** See feasibility above.
3. **Copyright.** Only original or licensed assets, with provenance recorded per asset
   (Phase 3).
4. **Secrets.** The OAuth client secret was shared in chat. Desktop-app secrets are
   low-sensitivity per Google, but rotate it if the chat is ever shared.
5. **Privacy.** The original README contained the owner's personal details in a public
   repo. They were kept out of this repo's README.
