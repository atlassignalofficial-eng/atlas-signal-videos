"""Stage lists for each job kind.

  mock  - Phase 1: content stages return placeholder data tagged {"mock": True}
          to exercise the engine end to end.
  short - Phase 3: a real map Short rendered from templates/shorts/<template>.json.

The publishing gate is shared: it enforces approval, the publishing mode,
duplicate prevention, and refuses to upload mock output.
"""
import hashlib
import json

from . import memory
from .pipeline import Stage


def _mock(gives: str, payload: dict):
    def fn(ctx, env):
        return {gives: {"mock": True, **payload}}
    return fn


def publish(ctx, env):
    """Publishing gate. Only dry runs are implemented until Phase 4."""
    mode = env.cfg["publishing"]["mode"]
    meta, video = ctx["metadata"], ctx["video"]
    record = {"mode": mode, "title": meta.get("title"), "video": video, "metadata": meta}
    if mode == "dry_run":
        path = env.out_dir / "publish_dryrun.json"
        path.write_text(json.dumps(record, indent=2, default=str))
        return {"publication": {"mode": mode, "video_id": None, "record": str(path)}}

    if video.get("mock") or meta.get("mock"):
        raise PermissionError("refusing to upload mock output")
    digest = hashlib.sha256(json.dumps(video, sort_keys=True).encode()).hexdigest()
    dupe = env.db.execute("SELECT video_id FROM publications WHERE content_hash = ?",
                          (digest,)).fetchone()
    if dupe:
        raise PermissionError(f"already uploaded as {dupe['video_id']}")
    raise NotImplementedError("real uploads arrive in Phase 4")


def learn(ctx, env):
    # Mock learnings go to kind 'mock' so they never pollute real project memory.
    memory.remember(env.db, "mock", f"job-{env.job_id}", ctx["analytics"], source="mock pipeline")
    return {"learning": {"mock": True, "stored": f"job-{env.job_id}"}}


MOCK = [
    Stage("research", _mock("research", {"findings": ["placeholder trend"]}),
          needs=("topic",), gives=("research",)),
    Stage("score", _mock("scored_ideas", {"ideas": [{"title": "placeholder", "score": 0.5}]}),
          needs=("research",), gives=("scored_ideas",)),
    Stage("select", _mock("idea", {"title": "Placeholder idea", "format": "short"}),
          needs=("scored_ideas",), gives=("idea",)),
    Stage("verify_sources", _mock("sources", {"items": []}), needs=("idea",), gives=("sources",)),
    Stage("script", _mock("script", {"beats": ["hook", "payoff"]}),
          needs=("idea", "sources"), gives=("script",)),
    Stage("editorial_qa", _mock("editorial", {"passed": True}), needs=("script",), gives=("editorial",)),
    Stage("storyboard", _mock("storyboard", {"scenes": []}), needs=("script",), gives=("storyboard",)),
    Stage("voice", _mock("narration", {"file": None}), needs=("script",), gives=("narration",)),
    Stage("visuals", _mock("assets", {"files": []}), needs=("storyboard",), gives=("assets",)),
    Stage("render", _mock("video", {"file": None}), needs=("narration", "assets"), gives=("video",)),
    Stage("video_qa", _mock("qa", {"passed": True}), needs=("video",), gives=("qa",)),
    Stage("thumbnail", _mock("thumbnail", {"file": None}), needs=("idea",), gives=("thumbnail",)),
    Stage("seo", _mock("metadata", {"title": "Placeholder title", "tags": []}),
          needs=("idea", "script"), gives=("metadata",)),
    Stage("owner_approval", None, approval=True),
    Stage("publish", publish, needs=("metadata", "video", "owner_approval_approved"),
          gives=("publication",), retry=False),
    Stage("analytics", _mock("analytics", {"views": None}), needs=("publication",), gives=("analytics",)),
    Stage("learn", learn, needs=("analytics",), gives=("learning",)),
]


# ---------------------------------------------------------------- short (Phase 3)

def _story(ctx):
    from . import short
    return short.load(ctx["story_path"])


def _world(env):
    from . import geo
    return geo.load_countries(env.cfg["paths"]["cache"])


def script(ctx, env):
    from .config import ROOT
    path = ROOT / "templates" / "shorts" / f"{ctx['template']}.json"
    if not path.exists():
        raise FileNotFoundError(f"no storyboard {path}")
    return {"story_path": str(path), "slug": _story({"story_path": path})["slug"]}


def editorial_qa(ctx, env):
    """Every numeric claim is recomputed from the map data; any miss stops the job."""
    from . import short
    story = _story(ctx)
    results = short.check_claims(story, short.build_actors(story, _world(env)))
    failed = [r for r in results if not r["passed"]]
    if failed:
        raise ValueError(f"claims failed fact-check: {failed}")
    return {"editorial": {"claims": results}}


def voice(ctx, env):
    from . import short
    work = env.out_dir / "audio"
    work.mkdir(exist_ok=True)
    return {"narration": short.narrate(_story(ctx), work, env.cfg["paths"]["cache"] / "voices")}


def render(ctx, env):
    from . import geo, short, tts
    story, countries = _story(ctx), _world(env)
    out = env.out_dir / f"{ctx['slug']}.mp4"
    video = short.render(story, countries, short.build_actors(story, countries), ctx["narration"],
                         env.out_dir / "audio", out)
    provenance = {
        "map_data": geo.SOURCE,
        "voice": {"name": ctx["narration"]["voice"], "dataset_licence": ctx["narration"]["licence"],
                  "engine": tts.VOICES[ctx["narration"]["voice"]][0]},
        "music_and_sfx": "synthesised by ffmpeg in this run (no third-party audio)",
        "fonts": "Inter (SIL OFL) or DejaVu Sans (free licence)",
        "storyboard": ctx["story_path"],
    }
    (env.out_dir / "provenance.json").write_text(json.dumps(provenance, indent=2))
    return {"video": video}


def video_qa(ctx, env):
    from . import short
    report = short.qa(ctx["video"]["file"])
    (env.out_dir / "qa.json").write_text(json.dumps(report, indent=2))
    if not report["passed"]:
        raise ValueError(f"video QA failed: {[k for k, ok in report['checks'].items() if not ok]}")
    return {"qa": report}


def thumbnail(ctx, env):
    import subprocess
    lines = ctx["narration"]["lines"]
    at = lines[min(3, len(lines) - 1)]["start"] + 2.2  # the "reveal" beat, title on screen
    out = env.out_dir / "thumbnail.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", ctx["video"]["file"],
                    "-frames:v", "1", str(out)], check=True)
    return {"thumbnail": {"file": str(out), "at": round(at, 2)}}


def seo(ctx, env):
    meta = dict(_story(ctx)["metadata"])
    problems = []
    if not 0 < len(meta["title"]) <= 100:
        problems.append("title must be 1-100 characters")
    if len(meta["description"]) > 5000:
        problems.append("description over 5000 characters")
    if len(",".join(meta["tags"])) > 500:
        problems.append("tags over 500 characters")
    if any(c in "".join(meta["tags"]) + meta["title"] for c in "<>"):
        problems.append("< and > are not allowed")
    if problems:
        raise ValueError("; ".join(problems))
    (env.out_dir / "upload.txt").write_text(
        f"TITLE\n{meta['title']}\n\nDESCRIPTION\n{meta['description']}\n\n"
        f"TAGS\n{', '.join(meta['tags'])}\n\nPLAYLIST\n{meta.get('playlist', '')}\n")
    return {"metadata": meta}


SHORT = [
    Stage("script", script, needs=("template",), gives=("story_path", "slug")),
    Stage("editorial_qa", editorial_qa, needs=("story_path",), gives=("editorial",), retry=False),
    Stage("voice", voice, needs=("story_path",), gives=("narration",)),
    Stage("render", render, needs=("story_path", "narration", "slug"), gives=("video",)),
    Stage("video_qa", video_qa, needs=("video",), gives=("qa",), retry=False),
    Stage("thumbnail", thumbnail, needs=("video", "narration"), gives=("thumbnail",)),
    Stage("seo", seo, needs=("story_path",), gives=("metadata",)),
    Stage("owner_approval", None, approval=True),
    Stage("publish", publish, needs=("metadata", "video", "owner_approval_approved"),
          gives=("publication",), retry=False),
]

PIPELINES = {"mock": MOCK, "short": SHORT}
