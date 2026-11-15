"""Geometry, storyboard logic, QA and a tiny real render. Offline: synthetic shapes."""
import json
import subprocess

import pytest

from bpu import geo, short, tts


def square(lon, lat, size):
    return [[[(lon, lat), (lon + size, lat), (lon + size, lat + size), (lon, lat + size)]]]


COUNTRIES = [
    {"iso": "BIG", "name": "Big", "continent": "Testland", "polys": square(0, -10, 20)},
    {"iso": "SML", "name": "Small", "continent": "North", "polys": square(-40, 60, 10) + square(-20, 70, 2)},
]


def test_area_of_one_degree_square_at_equator():
    assert geo.area_km2(square(0, 0, 1)) == pytest.approx(111.19 ** 2, rel=0.01)


def test_move_keeps_true_area_reaches_target_and_stays_upright():
    src = square(-100, 40, 10)
    moved = geo.move(src, (10, 20))
    assert geo.area_km2(moved) == pytest.approx(geo.area_km2(src), rel=0.005)
    assert geo.centroid(moved) == pytest.approx((10, 20), abs=0.01)
    (sw, se, ne, nw) = moved[0][0]
    assert sw[1] == pytest.approx(se[1], abs=0.2)  # bottom edge still level
    assert ne[1] > se[1]                             # north still up
    half = geo.move(src, (10, 20), t=0.5)
    assert geo.area_km2(half) == pytest.approx(geo.area_km2(src), rel=0.005)


def test_select_mainland_takes_largest_polygon_and_rejects_unknowns():
    assert len(geo.select(COUNTRIES, "country:SML")) == 2
    assert len(geo.select(COUNTRIES, "mainland:SML")) == 1
    with pytest.raises(KeyError):
        geo.select(COUNTRIES, "country:NOPE")


STORY = {
    "slug": "t", "voice": "joe",
    "metadata": {"title": "t", "description": "d", "tags": ["a"]},
    "cameras": {"world": [-60, 40, -30, 80], "close": [-10, 30, -20, 20]},
    "actors": {"big": {"select": ["continent:Testland"], "color": "teal", "label": "BIG"},
               "small": {"select": ["mainland:SML"], "color": "ice", "label": "SMALL"}},
    "checks": [{"claim": "big is ~9.4x small (high-latitude square is smaller)", "ratio": ["big", "small"], "expect": 9.4, "tolerance": 0.05},
               {"claim": "small fits", "fits": ["small"], "in": "big"},
               {"claim": "big beats small", "bigger": ["big", "small"]}],
    "beats": [{"say": "Look at this.", "title": ["A", "B"], "show": ["big", "small"], "camera": "world"},
              {"say": "Now move it.", "move": {"small": [10, 0]}, "camera": "close", "unlabel": ["big"]},
              {"say": "Gone.", "hide": ["small"]}],
}


def test_claims_are_recomputed_and_can_fail():
    actors = short.build_actors(STORY, COUNTRIES)
    results = short.check_claims(STORY, actors)
    assert [r["passed"] for r in results] == [True, True, True]
    wrong = {**STORY, "checks": [{**STORY["checks"][0], "expect": 14}]}
    assert short.check_claims(wrong, actors)[0]["passed"] is False


def test_plan_tracks_moves_hides_labels_and_camera():
    beats = short.plan(STORY, short.build_actors(STORY, COUNTRIES))
    assert beats[0]["appear"] == {"big", "small"}
    assert "small" in beats[1]["moves"] and beats[1]["cam"] == (STORY["cameras"]["world"], STORY["cameras"]["close"])
    assert beats[1]["unlabeled"] == {"big"} and beats[2]["hidden"] == {"small"}
    assert beats[2]["before"]["rest"]["small"] != beats[1]["before"]["rest"]["small"]  # moved


def test_captions_follow_the_line_break_at_punctuation_and_mark_emphasis():
    line = "It *shrinks*. Flat maps stretch things"
    assert short._caption(line, 0.0, 3.0)[:2] == ("IT SHRINKS.", True)   # sentence ends the chunk
    assert short._caption(line, 1.5, 3.0)[:2] == ("FLAT MAPS", False)
    assert short._caption(line, 2.9, 3.0)[0] == "STRETCH THINGS"
    assert short._caption(line, 9.0, 3.0) is None


def test_ghost_keeps_map_size_while_the_real_shape_shrinks():
    """The on-screen proof: a Mercator-space copy never shrinks; the true-size move does."""
    story = {**STORY, "beats": [STORY["beats"][0],
                                {"say": "Move.", "move": {"small": [10, 0]}, "ghost": {"small": [10, 0]}},
                                {"say": "Bye.", "unghost": ["small"]}]}
    actors = short.build_actors(story, COUNTRIES)
    beats = short.plan(story, actors)

    def height(rings):
        ys = [y for r in rings for _, y in r]
        return max(ys) - min(ys)

    src, dx, dy = beats[1]["ghost_moves"]["small"]
    ghost = beats[2]["before"]["ghosts"]["small"]
    real = short._merc_polys(beats[2]["before"]["rest"]["small"])
    assert height(ghost) == pytest.approx(height(src))      # ghost: same size on the map
    assert height(real) < height(ghost) * 0.5               # real shape: much smaller at the equator
    assert "small" in beats[2]["unghost"]


def test_pause_and_asterisks_do_not_reach_the_voice(tmp_path, monkeypatch):
    spoken = []

    def fake_tts(text, out, voice, cache, rate=None):
        spoken.append((text, rate))
        return _tone(out, 1.0)

    monkeypatch.setattr(short.tts, "synthesize", fake_tts)
    story = {**STORY, "voice_rate": "+10%",
             "beats": [{"say": "It *shrinks*.", "pause": 0.5}, {"say": "Done."}]}
    nar = short.narrate(story, tmp_path, tmp_path)
    assert spoken == [("It shrinks.", "+10%"), ("Done.", "+10%")]
    gap = nar["lines"][1]["start"] - nar["lines"][0]["dur"]
    assert gap == pytest.approx(short.GAP + 0.5, abs=0.01)


def test_only_commercially_licensed_voices_are_allowed(tmp_path):
    with pytest.raises(ValueError, match="commercial"):
        tts.synthesize("hi", tmp_path / "x.wav", "ryan", tmp_path)


def test_azure_voice_sends_escaped_ssml_and_writes_wav(tmp_path, monkeypatch):
    import io
    sent = []

    def fake_azure(req):
        sent.append(req)
        return io.BytesIO(b"RIFF....WAVEfmt fake")

    monkeypatch.setenv("AZURE_SPEECH_KEY", "k")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "eastus")
    out = tts.synthesize("Africa > Greenland & more", tmp_path / "a.wav", "andrew", tmp_path,
                         opener=fake_azure)
    req = sent[0]
    assert req.full_url == "https://eastus.tts.speech.microsoft.com/cognitiveservices/v1"
    assert req.headers["Ocp-apim-subscription-key"] == "k"
    assert b"en-US-AndrewNeural" in req.data and b"Africa &gt; Greenland &amp; more" in req.data
    assert b"prosody" not in req.data
    tts.synthesize("Hi", tmp_path / "b.wav", "andrew", tmp_path, opener=fake_azure, rate="+10%")
    assert b"<prosody rate='+10%'>Hi</prosody>" in sent[1].data
    with pytest.raises(ValueError, match="rate"):
        tts.synthesize("Hi", tmp_path / "c.wav", "andrew", tmp_path, opener=fake_azure, rate="fast")
    assert out.read_bytes().startswith(b"RIFF")


def test_azure_voice_needs_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    with pytest.raises(RuntimeError, match="AZURE_SPEECH_KEY"):
        tts.synthesize("hi", tmp_path / "a.wav", "andrew", tmp_path)


def _tone(path, seconds, hz=220):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency={hz}:duration={seconds}", str(path)], check=True)
    return path


def test_tiny_render_passes_technical_checks_except_length(tmp_path):
    """Real frames + real audio mix, with tones standing in for TTS."""
    lines, t = [], 0.0
    for i, d in enumerate((1.0, 1.2, 0.6)):
        lines.append({"wav": str(_tone(tmp_path / f"l{i}.wav", d, 200 + 50 * i)), "start": t, "dur": d})
        t += d + short.GAP
    narration = {"voice": "joe", "licence": "CC0", "lines": lines, "total": t - short.GAP + short.TAIL}
    actors = short.build_actors(STORY, COUNTRIES)
    out = tmp_path / "t.mp4"
    video = short.render(STORY, COUNTRIES, actors, narration, tmp_path, out)
    report = short.qa(out)
    assert video["frames"] == pytest.approx(narration["total"] * short.FPS, abs=1)
    checks = report["checks"]
    assert checks["vertical 1080x1920"] and checks["30 fps"] and checks["has audio"]
    assert checks["loudness -14 ±1 LUFS"] and checks["true peak <= -1 dBTP"]
    assert not checks["duration 10-180 s (Shorts limit)"]  # 5 s is too short, and QA says so
    assert report["passed"] is False


def test_normalize_hits_target(tmp_path):
    src = _tone(tmp_path / "quiet.wav", 6)
    out = short._normalize(src, tmp_path / "loud.wav")
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(out), "-af", "ebur128",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    lufs = float(log.rsplit("I:", 1)[1].split("LUFS")[0])
    assert lufs == pytest.approx(-14, abs=1)


def test_storyboard_in_repo_is_valid():
    from bpu.config import ROOT
    for path in (ROOT / "templates" / "shorts").glob("*.json"):
        story = json.loads(path.read_text())
        assert story["voice"] in tts.VOICES
        names = set(story["actors"])
        for b in story["beats"]:
            used = set(b.get("show", [])) | set(b.get("hide", [])) | set(b.get("move", {}))
            used |= set(b.get("ghost", {})) | set(b.get("unghost", [])) | set(b.get("area", []))
            assert used | set(b.get("pulse", [])) | set(b.get("unlabel", [])) <= names
            assert b.get("camera", "world") in story["cameras"]
        assert len(story["metadata"]["title"]) <= 100
