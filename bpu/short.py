"""Render a map Short from a storyboard (templates/shorts/*.json), then QA it.

Storyboard model: named actors (country groups), a list of beats. Each beat has
one narration line and may change what is shown, move actors (true-size sphere
moves), move the camera, and set the title. Changes animate at the start of the
beat; narration timing drives everything.
"""
import json
import math
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import geo, tts

W, H, FPS, SS = 1080, 1920, 30, 2  # SS: supersampling factor for smooth edges
MOVE_SECONDS = 1.6
MAP_BAND = (430, 1470)  # px: below the title, above the captions
GAP, TAIL = 0.35, 1.2  # silence after each line; hold after the last
COLORS = {
    "bg": (10, 24, 48), "land": (40, 58, 90), "edge": (10, 24, 48),
    "teal": (28, 150, 120), "ice": (236, 242, 250), "red": (232, 76, 76),
    "gold": (255, 197, 49), "orange": (255, 138, 40), "blue": (86, 152, 255),
    "white": (255, 255, 255), "shadow": (0, 0, 0),
}


def load(path) -> dict:
    return json.loads(Path(path).read_text())


def build_actors(story, countries) -> dict:
    return {name: [p for sel in a["select"] for p in geo.select(countries, sel)]
            for name, a in story["actors"].items()}


def check_claims(story, actors) -> list[dict]:
    """Recompute every numeric claim from the map data."""
    area = {n: geo.area_km2(p) for n, p in actors.items()}
    out = []
    for c in story.get("checks", []):
        if "ratio" in c:
            a, b = c["ratio"]
            value = area[a] / area[b]
            ok = abs(value - c["expect"]) / c["expect"] <= c["tolerance"]
            out.append({"claim": c["claim"], "value": round(value, 2), "passed": ok})
        elif "fits" in c:
            total, cap = sum(area[n] for n in c["fits"]), area[c["in"]]
            out.append({"claim": c["claim"], "value": f"{total / 1e6:.1f}M of {cap / 1e6:.1f}M km2",
                        "passed": total < cap})
        else:
            raise ValueError(f"unknown check {c}")
    return out


def narrate(story, work: Path, voice_dir) -> dict:
    model = tts.voice_model(story["voice"], voice_dir)
    lines, t = [], 0.0
    for i, beat in enumerate(story["beats"]):
        wav = tts.synthesize(beat["say"], work / f"line{i:02d}.wav", model)
        d = tts.duration(wav)
        lines.append({"wav": str(wav), "start": round(t, 3), "dur": round(d, 3)})
        t += d + GAP
    return {"voice": story["voice"], "licence": tts.VOICES[story["voice"]][1],
            "lines": lines, "total": round(t - GAP + TAIL, 3)}


# ---------------------------------------------------------------- timeline

def _ease(p):
    p = max(0.0, min(1.0, p))
    return p * p * (3 - 2 * p)


def plan(story, actors) -> list[dict]:
    """Per beat: the state before and after it (shapes at rest, camera, shown set)."""
    shown, unlabeled, title = set(), set(), ["", ""]
    cam = story["cameras"][story["beats"][0].get("camera", "world")]
    rest = dict(actors)  # actor -> polygons at their current resting place
    out = []
    for beat in story["beats"]:
        before = {"shown": set(shown), "cam": cam, "rest": dict(rest)}
        shown |= set(beat.get("show", []))
        hidden = set(beat.get("hide", []))
        shown -= hidden
        unlabeled |= set(beat.get("unlabel", []))
        title = beat.get("title", title)
        new_cam = story["cameras"][beat["camera"]] if "camera" in beat else cam
        moves = {}
        for name, to in beat.get("move", {}).items():
            moves[name] = (rest[name], to)
            rest[name] = geo.move(rest[name], to)
        out.append({"before": before, "moves": moves, "appear": shown - before["shown"],
                    "hidden": hidden, "title": title, "cam": (cam, new_cam),
                    "unlabeled": set(unlabeled)})
        cam = new_cam
    return out


# ---------------------------------------------------------------- drawing

def _font(size):
    for name in ("Inter:bold", "DejaVu Sans:bold"):
        try:
            path = subprocess.run(["fc-match", "-f", "%{file}", name], capture_output=True,
                                  text=True, check=True).stdout
            return ImageFont.truetype(path, size)
        except (OSError, subprocess.CalledProcessError, FileNotFoundError):
            continue
    return ImageFont.load_default(size)


class Painter:
    def __init__(self, countries):
        self.bg = [[[geo.mercator(*pt) for pt in ring] for ring in poly]
                   for c in countries for poly in c["polys"]]
        self.f_title, self.f_cap, self.f_label = _font(96 * SS), _font(66 * SS), _font(34 * SS)

    def view(self, cam_a, cam_b, p):
        (ax0, ay0), (ax1, ay1) = geo.mercator(cam_a[0], cam_a[2]), geo.mercator(cam_a[1], cam_a[3])
        (bx0, by0), (bx1, by1) = geo.mercator(cam_b[0], cam_b[2]), geo.mercator(cam_b[1], cam_b[3])
        x0, x1 = ax0 + (bx0 - ax0) * p, ax1 + (bx1 - ax1) * p
        y0, y1 = ay0 + (by0 - ay0) * p, ay1 + (by1 - ay1) * p
        # fit the camera box into the band between the title and the captions
        top, bottom = MAP_BAND[0] * SS, MAP_BAND[1] * SS
        s = min(W * SS / (x1 - x0), (bottom - top) / (y1 - y0))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        return lambda x, y: ((x - cx) * s + W * SS / 2, (top + bottom) / 2 - (y - cy) * s)

    def frame(self, actors_now, colors, labels, to_px, title, caption) -> Image.Image:
        img = Image.new("RGB", (W * SS, H * SS), COLORS["bg"])
        d = ImageDraw.Draw(img, "RGBA")
        for poly in self.bg:
            for ring in poly:
                d.polygon([to_px(x, y) for x, y in ring], fill=COLORS["land"], outline=COLORS["edge"])
        for name, (polys, alpha) in actors_now.items():
            fill = (*COLORS[colors[name]], int(255 * alpha))
            for poly in polys:
                pts = [to_px(*geo.mercator(*pt)) for pt in poly[0]]
                d.polygon(pts, fill=fill, outline=(*COLORS["edge"], int(255 * alpha)), width=2 * SS)
        for text, (x, y), alpha in labels:
            self._text(d, text, x, y, self.f_label, COLORS["white"], alpha)
        if title[0]:
            self._text(d, title[0], W * SS / 2, 230 * SS, self.f_title, COLORS["white"])
        if title[1]:
            self._text(d, title[1], W * SS / 2, 345 * SS, self.f_title, COLORS["gold"])
        if caption:
            self._text(d, caption, W * SS / 2, 1560 * SS, self.f_cap, COLORS["white"])
        return img.resize((W, H), Image.LANCZOS)

    @staticmethod
    def _text(d, text, x, y, font, color, alpha=1.0):
        a = int(255 * alpha)
        d.text((x, y), text, font=font, fill=(*color, a), anchor="mm",
               stroke_width=max(2, font.size // 12), stroke_fill=(*COLORS["shadow"], a))


def _caption(line_text, t_in_line, dur, words_per_chunk=3):
    words = line_text.split()
    chunks = [" ".join(words[i:i + words_per_chunk]) for i in range(0, len(words), words_per_chunk)]
    total = sum(len(c) for c in chunks)
    acc = 0.0
    for c in chunks:
        acc += len(c) / total * dur
        if t_in_line < acc:
            return c.upper()
    return chunks[-1].upper() if t_in_line < dur + GAP else ""


def render(story, countries, actors, narration, work: Path, out_mp4: Path) -> dict:
    beats, painter = plan(story, actors), Painter(countries)
    lines, total = narration["lines"], narration["total"]
    colors = {n: a["color"] for n, a in story["actors"].items()}
    label_text = {n: a["label"] for n, a in story["actors"].items()}
    n_frames = math.ceil(total * FPS)

    audio = _mix_audio(lines, [lines[i]["start"] for i, b in enumerate(story["beats"]) if b.get("move")],
                       total, work)
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-i", str(audio), "-c:v", "libx264", "-preset", "medium",
         "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-t", f"{total:.3f}", "-movflags", "+faststart", str(out_mp4)],
        stdin=subprocess.PIPE)
    try:
        for f in range(n_frames):
            enc.stdin.write(_frame_at(f / FPS, story, beats, lines, painter, colors, label_text,
                                      actors).tobytes())
    finally:
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError("ffmpeg encode failed")
    return {"file": str(out_mp4), "frames": n_frames, "seconds": total}


def _frame_at(t, story, beats, lines, painter, colors, label_text, actors):
    i = max(k for k, ln in enumerate(lines) if ln["start"] <= t) if t >= lines[0]["start"] else 0
    b, ln = beats[i], lines[i]
    p = _ease((t - ln["start"]) / MOVE_SECONDS)
    to_px = painter.view(*b["cam"], p)

    now, labels = {}, []
    for name in actors:
        if name in b["moves"]:
            src, to = b["moves"][name]
            polys = geo.move(src, to, t=p)
        else:
            polys = b["before"]["rest"][name]
        if name in b["hidden"]:
            alpha = 1 - p
        elif name in b["before"]["shown"] or name in b["appear"]:
            alpha = 1.0
        else:
            continue
        if alpha <= 0.01:
            continue
        now[name] = (polys, alpha)
        if name not in b["unlabeled"]:
            cx, cy = geo.centroid(polys)
            labels.append((label_text[name], to_px(*geo.mercator(cx, cy)), alpha))
    caption = _caption(story["beats"][i]["say"], t - ln["start"], ln["dur"])
    return painter.frame(now, colors, labels, to_px, b["title"], caption)


def _mix_audio(lines, whoosh_at, total, work: Path) -> Path:
    """Narration + soft pad + a whoosh per move, normalised to -14 LUFS."""
    out = work / "mix.wav"
    args, parts = ["ffmpeg", "-v", "error", "-y"], []
    for k, ln in enumerate(lines):
        args += ["-i", ln["wav"]]
        ms = int(ln["start"] * 1000)
        parts.append(f"[{k}:a]aresample=44100,adelay={ms}|{ms}[n{k}]")
    n = len(lines)
    for j, hz in enumerate((110.0, 164.81, 220.0)):  # A2 / E3 / A3 pad
        args += ["-f", "lavfi", "-i", f"sine=frequency={hz}:sample_rate=44100:duration={total:.2f}"]
    parts.append(f"[{n}:a][{n + 1}:a][{n + 2}:a]amix=inputs=3:normalize=1,lowpass=f=900,"
                 f"tremolo=f=0.2:d=0.3,volume=0.10,afade=t=in:d=1.5,"
                 f"afade=t=out:st={max(0, total - 2):.2f}:d=2[pad]")
    whooshes = []
    for j, at in enumerate(whoosh_at):
        ms = int(at * 1000)
        parts.append(f"anoisesrc=d=0.9:c=pink:r=44100:a=0.6,bandpass=f=700:width_type=h:w=900,"
                     f"afade=t=in:d=0.35,afade=t=out:st=0.4:d=0.5,volume=0.35,"
                     f"adelay={ms}|{ms}[w{j}]")
        whooshes.append(f"[w{j}]")
    mix_in = "".join(f"[n{k}]" for k in range(n)) + "[pad]" + "".join(whooshes)
    parts.append(f"{mix_in}amix=inputs={n + 1 + len(whooshes)}:normalize=0:duration=longest,"
                 f"atrim=0:{total:.3f}[out]")
    premix = work / "premix.wav"
    subprocess.run(args + ["-filter_complex", ";".join(parts), "-map", "[out]", "-ac", "2", str(premix)],
                   check=True)
    return _normalize(premix, out)


def _normalize(src: Path, dest: Path, target=-14.0) -> Path:
    """Two-pass EBU R128 loudnorm: single pass undershoots on short clips."""
    spec = f"loudnorm=I={target}:TP=-1.5:LRA=11"
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src),
                          "-af", spec + ":print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True, check=True).stderr
    m = json.loads(log[log.rindex("{"):log.rindex("}") + 1])
    second = (f"{spec}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
              f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
              f"offset={m['target_offset']}:linear=true,aresample=44100")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", second, str(dest)], check=True)
    return dest


# ---------------------------------------------------------------- QA

def qa(mp4) -> dict:
    """Technical checks a reviewer should never have to do by eye."""
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(mp4)],
        capture_output=True, text=True, check=True).stdout)
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in probe["streams"])
    dur = float(probe["format"]["duration"])
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mp4),
                          "-vf", "blackdetect=d=0.5:pix_th=0.05",
                          "-af", "ebur128=peak=true,silencedetect=n=-45dB:d=1.5", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", log)[-1])
    peak = float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", log)[-1])
    checks = {
        "vertical 1080x1920": (v["width"], v["height"]) == (W, H),
        "30 fps": v["r_frame_rate"] == f"{FPS}/1",
        "has audio": has_audio,
        "duration 10-180 s (Shorts limit)": 10 <= dur <= 180,
        "loudness -14 ±1 LUFS": abs(lufs + 14) <= 1,
        "true peak <= -1 dBTP": peak <= -1.0,
        "no black segments": "black_start" not in log,
        "no silent gaps > 1.5 s": "silence_start" not in log,
    }
    return {"passed": all(checks.values()), "checks": checks,
            "measured": {"duration": round(dur, 2), "lufs": lufs, "true_peak": peak}}
