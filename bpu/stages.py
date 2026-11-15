"""Stage lists for each job kind.

Phase 1 status: every content stage below is a MOCK. It returns fixed
placeholder data tagged {"mock": True} so the engine can be exercised end to
end. The publishing gate is real: it enforces approval, the publishing mode,
duplicate prevention, and refuses to upload mock output. Real stages replace
the mocks phase by phase (docs/PROGRESS.md).
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

PIPELINES = {"mock": MOCK}
