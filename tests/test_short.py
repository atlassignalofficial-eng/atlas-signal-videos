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
               {"claim": "small fits", "fits": ["small"], "in": "big"}],
    "beats": [{"say": "Look at this.", "title": ["A", "B"], "show": ["big", "small"], "camera": "world"},
              {"say": "Now move it.", "move": {"small": [10, 0]}, "camera": "close", "unlabel": ["big"]},
              {"say": "Gone.", "hide": ["small"]}],
}


def test_claims_are_recomputed_and_can_fail():
    actors = short.build_actors(STORY, COUNTRIES)
    results = short.check_claims(STORY, actors)
    assert [r["passed"] for r in results] == [True, True]
    wrong = {**STORY, "checks": [{**STORY["checks"][0], "expect": 14}]}
    assert short.check_claims(wrong, actors)[0]["passed"] is False


def test_plan_tracks_moves_hides_labels_and_camera():
    beats = short.plan(STORY, short.build_actors(STORY, COUNTRIES))
    assert beats[0]["appear"] == {"big", "small"}
    assert "small" in beats[1]["moves"] and beats[1]["cam"] == (STORY["cameras"]["world"], STORY["cameras"]["close"])
    assert beats[1]["unlabeled"] == {"big"} and beats[2]["hidden"] == {"small"}
    assert beats[2]["before"]["rest"]["small"] != beats[1]["before"]["rest"]["small"]  # moved


def test_captions_follow_the_line():
    line = "one two three four five six"
    assert short._caption(line, 0.0, 2.0) == "ONE TWO THREE"
    assert short._caption(line, 1.9, 2.0) == "FOUR FIVE SIX"
    assert short._caption(line, 5.0, 2.0) == ""


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
            assert set(b.get("show", [])) | set(b.get("hide", [])) | set(b.get("move", {})) <= names
            assert b.get("camera", "world") in story["cameras"]
        assert len(story["metadata"]["title"]) <= 100
