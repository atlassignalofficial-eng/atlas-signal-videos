"""Render a map Short from a storyboard (templates/shorts/*.json), then QA it.

Storyboard model: named actors (country groups), a list of beats. Each beat has
one narration line and may change what is shown, move actors (true-size sphere
moves), move the camera, and set the title. Changes animate at the start of the
beat; narration timing drives everything.
"""
import functools
import json
import math
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import geo, tts

W, H, FPS, SS = 1080, 1920, 30, 2  # SS: supersampling factor for smooth edges
MOVE_SECONDS = 1.2
MAP_BAND = (430, 1470)  # px: below the title, above the captions
GAP, TAIL = 0.16, 0.9  # silence after each line; hold after the last
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
        elif "bigger" in c:
            a, b = c["bigger"]
            out.append({"claim": c["claim"], "value": round(area[a] / area[b], 3),
                        "passed": area[a] > area[b]})
        elif "fits" in c:
            total, cap = sum(area[n] for n in c["fits"]), area[c["in"]]
            out.append({"claim": c["claim"], "value": f"{total / 1e6:.1f}M of {cap / 1e6:.1f}M km2",
                        "passed": total < cap})
        else:
            raise ValueError(f"unknown check {c}")
    return out


def narrate(story, work: Path, voice_dir) -> dict:
    lines, t = [], 0.0
    for i, beat in enumerate(story["beats"]):
        wav = tts.synthesize(beat["say"].replace("*", ""), work / f"line{i:02d}.wav",
                             story["voice"], voice_dir, rate=story.get("voice_rate"))
        wav = _trim_silence(wav, work / f"line{i:02d}t.wav")
        d = tts.duration(wav)
        lines.append({"wav": str(wav), "start": round(t, 3), "dur": round(d, 3)})
        t += d + GAP + beat.get("pause", 0)  # "pause": extra seconds to let a visual land
    return {"voice": story["voice"], "licence": tts.licence(story["voice"]),
            "lines": lines, "total": round(t - GAP + TAIL, 3)}


def _trim_silence(src: Path, dest: Path) -> Path:
    """Cut the padding TTS engines add around a line, so the pacing is ours to set."""
    cut = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.03"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af",
                    f"{cut},areverse,{cut},areverse", str(dest)], check=True)
    return dest


# ---------------------------------------------------------------- timeline

def _ease(p):
    p = max(0.0, min(1.0, p))
    return p * p * (3 - 2 * p)


def _pop(age, seconds=0.14, amount=0.2):
    """Scale factor for text that has been on screen for `age` seconds."""
    return 1 + amount * (1 - _ease(age / seconds))


def _merc_polys(polys):
    return [[geo.mercator(*pt) for pt in poly[0]] for poly in polys]


def plan(story, actors) -> list[dict]:
    """Per beat: the state before it and what changes during it."""
    shown, unlabeled, with_area, title = set(), set(), set(), ["", ""]
    cam = story["cameras"][story["beats"][0].get("camera", "world")]
    rest = dict(actors)  # actor -> polygons at their current resting place
    ghosts = {}          # actor -> its map-size outline (Mercator coords) at rest
    out = []
    for beat in story["beats"]:
        before = {"shown": set(shown), "cam": cam, "rest": dict(rest), "ghosts": dict(ghosts)}
        shown |= set(beat.get("show", []))
        hidden = set(beat.get("hide", []))
        shown -= hidden
        unlabeled |= set(beat.get("unlabel", []))
        with_area |= set(beat.get("area", []))
        new_title = beat.get("title", title)
        new_cam = story["cameras"][beat["camera"]] if "camera" in beat else cam
        # A ghost is the shape as the MAP draws it: it slides in Mercator space, so it
        # never shrinks, while the real actor makes a true-size move beside it.
        ghost_moves = {}
        for name, to in beat.get("ghost", {}).items():
            src = _merc_polys(rest[name])
            cx, cy = geo.mercator(*geo.centroid(rest[name]))
            tx, ty = geo.mercator(*to)
            ghost_moves[name] = (src, tx - cx, ty - cy)
            ghosts[name] = [[(x + tx - cx, y + ty - cy) for x, y in ring] for ring in src]
        unghost = set(beat.get("unghost", []))
        for name in unghost:
            ghosts.pop(name, None)
        moves = {}
        for name, to in beat.get("move", {}).items():
            moves[name] = (rest[name], to)
            rest[name] = geo.move(rest[name], to)
        out.append({"before": before, "moves": moves, "appear": shown - before["shown"],
                    "hidden": hidden, "title": new_title, "title_changed": new_title != title,
                    "cam": (cam, new_cam), "unlabeled": set(unlabeled), "with_area": set(with_area),
                    "ghost_moves": ghost_moves, "unghost": unghost,
                    "pulse": set(beat.get("pulse", [])),
                    "move_seconds": beat.get("move_seconds", MOVE_SECONDS)})
        cam, title = new_cam, new_title
    return out


# ---------------------------------------------------------------- drawing

@functools.lru_cache(maxsize=64)
def _font(size):
    for name in ("Inter:bold", "DejaVu Sans:bold"):
        try:
            path = subprocess.run(["fc-match", "-f", "%{file}", name], capture_output=True,
                                  text=True, check=True).stdout
            return ImageFont.truetype(path, size)
        except (OSError, subprocess.CalledProcessError, FileNotFoundError):
            continue
    return ImageFont.load_default(size)


def _area_text(km2):
    m = km2 / 1e6
    return f"{m:.0f}M km²" if m >= 10 else f"{m:.1f}M km²"


class Painter:
    def __init__(self, countries):
        self.bg = [[[geo.mercator(*pt) for pt in ring] for ring in poly]
                   for c in countries for poly in c["polys"]]

    def view(self, cam_a, cam_b, p, zoom=1.0):
        (ax0, ay0), (ax1, ay1) = geo.mercator(cam_a[0], cam_a[2]), geo.mercator(cam_a[1], cam_a[3])
        (bx0, by0), (bx1, by1) = geo.mercator(cam_b[0], cam_b[2]), geo.mercator(cam_b[1], cam_b[3])
        x0, x1 = ax0 + (bx0 - ax0) * p, ax1 + (bx1 - ax1) * p
        y0, y1 = ay0 + (by0 - ay0) * p, ay1 + (by1 - ay1) * p
        # fit the camera box into the band between the title and the captions
        top, bottom = MAP_BAND[0] * SS, MAP_BAND[1] * SS
        s = min(W * SS / (x1 - x0), (bottom - top) / (y1 - y0)) * zoom
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        return lambda x, y: ((x - cx) * s + W * SS / 2, (top + bottom) / 2 - (y - cy) * s)

    def frame(self, layers, labels, to_px, title, caption) -> Image.Image:
        """layers: draw-ordered [(pixel rings, rgb, alpha, style)], style in fill|lifted|ghost."""
        img = Image.new("RGB", (W * SS, H * SS), COLORS["bg"])
        d = ImageDraw.Draw(img, "RGBA")
        for poly in self.bg:
            for ring in poly:
                d.polygon([to_px(x, y) for x, y in ring], fill=COLORS["land"], outline=COLORS["edge"])
        self._graticule(d, to_px)
        for rings, rgb, alpha, style in layers:
            a = int(255 * alpha)
            for pts in rings:
                if style == "ghost":
                    d.polygon(pts, fill=(*rgb, int(48 * alpha)))
                    d.line(pts + pts[:1], fill=(*rgb, int(220 * alpha)), width=3 * SS, joint="curve")
                    continue
                if style == "lifted":
                    d.polygon([(x + 7 * SS, y + 9 * SS) for x, y in pts], fill=(0, 0, 0, int(90 * alpha)))
                d.polygon(pts, fill=(*rgb, a), outline=(*COLORS["edge"], a), width=2 * SS)
        for text, (x, y), alpha, color, size in labels:
            self._text(d, text, x, y, _font(size * SS), COLORS[color], alpha)
        for line, y, color in ((title["text"][0], 230, "white"), (title["text"][1], 345, "gold")):
            if line:
                fit = min(1.0, (W - 90) * SS / _font(96 * SS).getlength(line))  # never clip
                self._text(d, line, W * SS / 2, y * SS,
                           _font(round(96 * fit * title["scale"]) * SS), COLORS[color])
        if caption:
            text, strong, scale = caption
            size = round((84 if strong else 72) * scale) * SS
            self._text(d, text, W * SS / 2, 1570 * SS, _font(size), COLORS["gold" if strong else "white"])
        return img.resize((W, H), Image.LANCZOS)

    @staticmethod
    def _graticule(d, to_px):
        """Faint lat/long grid. On Mercator the rows visibly spread toward the poles."""
        faint = (255, 255, 255, 22)
        for lat in range(-60, 81, 20):
            y = to_px(0, geo.mercator(0, lat)[1])[1]
            d.line([(0, y), (W * SS, y)], fill=faint, width=SS)
        for lon in range(-180, 181, 30):
            x = to_px(math.radians(lon), 0)[0]
            d.line([(x, 0), (x, H * SS)], fill=faint, width=SS)
        y = to_px(0, 0)[1]
        d.line([(0, y), (W * SS, y)], fill=(*COLORS["gold"], 120), width=2 * SS)
        d.text((W * SS - 24 * SS, y - 8 * SS), "EQUATOR", font=_font(24 * SS), anchor="rd",
               fill=(*COLORS["gold"], 170))

    @staticmethod
    def _text(d, text, x, y, font, color, alpha=1.0):
        a = int(255 * alpha)
        d.text((x, y), text, font=font, fill=(*color, a), anchor="mm",
               stroke_width=max(2, font.size // 11), stroke_fill=(*COLORS["shadow"], a))


def _caption(line_text, t_in_line, dur, words_per_chunk=2):
    """(TEXT, emphasised, seconds on screen) for the chunk being spoken, or None.

    Words wrapped in *asterisks* are emphasised: their chunk is drawn larger, in gold.
    """
    words, inside = [], False
    for tok in line_text.split():
        inside = inside or tok.startswith("*")
        words.append((tok.replace("*", ""), inside))
        if tok.rstrip(".,!?").endswith("*"):
            inside = False
    chunks = [[]]
    for w in words:
        chunks[-1].append(w)
        if len(chunks[-1]) == words_per_chunk or w[0][-1] in ".,!?":
            chunks.append([])
    chunks = [c for c in chunks if c]
    total = sum(len(w) for w, _ in words)
    acc = 0.0
    for k, chunk in enumerate(chunks):
        start = acc
        acc += sum(len(w) for w, _ in chunk) / total * dur
        if t_in_line < acc or (k == len(chunks) - 1 and t_in_line < dur + GAP):
            return (" ".join(w for w, _ in chunk).upper(), any(e for _, e in chunk), t_in_line - start)
    return None


def render(story, countries, actors, narration, work: Path, out_mp4: Path) -> dict:
    beats, painter = plan(story, actors), Painter(countries)
    lines, total = narration["lines"], narration["total"]
    n_frames = math.ceil(total * FPS)
    cues = {key: [lines[i]["start"] for i, b in enumerate(story["beats"]) if b.get(key)]
            for key in ("move", "impact")}
    cues["pop"] = [lines[i]["start"] for i, b in enumerate(story["beats"]) if b.get("show") and i]
    audio = _mix_audio(lines, cues, total, work)
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-i", str(audio), "-c:v", "libx264", "-preset", "medium",
         "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-t", f"{total:.3f}", "-movflags", "+faststart", str(out_mp4)],
        stdin=subprocess.PIPE)
    try:
        for f in range(n_frames):
            enc.stdin.write(frame_at(f / FPS, story, beats, lines, total, painter, actors).tobytes())
    finally:
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError("ffmpeg encode failed")
    return {"file": str(out_mp4), "frames": n_frames, "seconds": total}


def frame_at(t, story, beats, lines, total, painter, actors) -> Image.Image:
    i = max(k for k, ln in enumerate(lines) if ln["start"] <= t) if t >= lines[0]["start"] else 0
    b, ln = beats[i], lines[i]
    age = t - ln["start"]
    beat_len = (lines[i + 1]["start"] if i + 1 < len(lines) else total) - ln["start"]
    # a move must land before the next beat starts, or the shape would jump
    p = _ease(age / min(b["move_seconds"], beat_len * 0.92))
    to_px = painter.view(*b["cam"], p, zoom=1 + 0.05 * t / total)  # slow push-in: never static
    spec = story["actors"]

    layers, labels = [], []
    for name in actors:
        if name in b["ghost_moves"] or name in b["before"]["ghosts"]:
            if name in b["ghost_moves"]:
                src, dx, dy = b["ghost_moves"][name]
                rings, g_alpha = [[(x + dx * p, y + dy * p) for x, y in r] for r in src], p
            else:
                rings = b["before"]["ghosts"][name]
                g_alpha = 1 - p if name in b["unghost"] else 1.0
            if g_alpha > 0.01:
                px = [[to_px(x, y) for x, y in r] for r in rings]
                layers.append((px, COLORS["white"], g_alpha, "ghost"))
                top = min(pt[1] for r in px for pt in r)
                mid = sum(pt[0] for r in px for pt in r) / sum(len(r) for r in px)
                labels.append((story.get("ghost_label", "MAP SIZE"), (mid, top + 46 * SS),
                               g_alpha, "white", 34))
        polys = geo.move(*b["moves"][name], t=p) if name in b["moves"] else b["before"]["rest"][name]
        if name in b["hidden"]:
            alpha = 1 - p
        elif name in b["appear"]:
            alpha = min(1.0, age / 0.2)
        elif name in b["before"]["shown"]:
            alpha = 1.0
        else:
            continue
        if alpha <= 0.01:
            continue
        cx, cy = to_px(*geo.mercator(*geo.centroid(polys)))
        k = 1 + 0.045 * math.sin(age * 9) if name in b["pulse"] else 1.0  # attention wobble
        px = [[((x - cx) * k + cx, (y - cy) * k + cy) for x, y in
               (to_px(*geo.mercator(*pt)) for pt in poly[0])] for poly in polys]
        layers.append((px, COLORS[spec[name]["color"]], alpha,
                       "fill" if spec[name].get("base") else "lifted"))
        if name not in b["unlabeled"]:
            if "label_at" in spec[name]:  # fixed spot, for when the centre gets covered
                lx, ly = to_px(*geo.mercator(*spec[name]["label_at"]))
            else:
                lx, ly = cx, cy + spec[name].get("label_dy", 0) * SS
            if name in b["with_area"]:
                labels.append((spec[name]["label"], (lx, ly - 20 * SS), alpha, "white", 34))
                labels.append((_area_text(geo.area_km2(actors[name])), (lx, ly + 22 * SS),
                               alpha, "gold", 34))
            else:
                labels.append((spec[name]["label"], (lx, ly), alpha, "white", 34))
    cap = _caption(story["beats"][i]["say"], age, ln["dur"])
    caption = (cap[0], cap[1], _pop(cap[2])) if cap else None
    title = {"text": b["title"], "scale": _pop(age, 0.22, 0.25) if b["title_changed"] else 1.0}
    return painter.frame(layers, labels, to_px, title, caption)


def _mix_audio(lines, cues, total, work: Path) -> Path:
    """Narration over a pad and a soft pulse, with whoosh / pop / impact cues. -14 LUFS.

    Every sound is synthesised here by ffmpeg, so there is no third-party audio.
    """
    out = work / "mix.wav"
    args, parts, mix = ["ffmpeg", "-v", "error", "-y"], [], []
    for k, ln in enumerate(lines):
        args += ["-i", ln["wav"]]
        ms = int(ln["start"] * 1000)
        parts.append(f"[{k}:a]aresample=44100,adelay={ms}|{ms}[n{k}]")
        mix.append(f"[n{k}]")

    def add(chain, at=0.0):
        ms = int(max(0.0, at) * 1000)
        parts.append(f"{chain},adelay={ms}|{ms}[s{len(mix)}]")
        mix.append(f"[s{len(mix)}]")

    fade = f"afade=t=in:d=1.2,afade=t=out:st={max(0, total - 1.5):.2f}:d=1.5"
    pad = "+".join(f"sin(2*PI*{hz}*t)" for hz in (110.0, 164.81, 220.0))  # A2 E3 A3
    add(f"aevalsrc='({pad})/3':s=44100:d={total:.2f},lowpass=f=900,tremolo=f=0.2:d=0.3,volume=0.09,{fade}")
    # heartbeat-style kick at 100 BPM keeps the pace up under the voice
    add(f"aevalsrc='sin(2*PI*(42+70*exp(-mod(t,0.6)*30))*mod(t,0.6))*exp(-mod(t,0.6)*8)'"
        f":s=44100:d={total:.2f},lowpass=f=160,volume=0.30,{fade}")
    for at in cues.get("move", []):
        add("anoisesrc=d=0.9:c=pink:r=44100:a=0.6,bandpass=f=700:width_type=h:w=900,"
            "afade=t=in:d=0.35,afade=t=out:st=0.4:d=0.5,volume=0.35", at)
    for at in cues.get("pop", []):
        add("aevalsrc='sin(2*PI*(520+900*t)*t)*exp(-t*38)':s=44100:d=0.16,volume=0.30", at)
    for at in cues.get("impact", []):
        add("anoisesrc=d=0.7:c=pink:r=44100:a=0.5,highpass=f=1200,afade=t=in:d=0.7:curve=cub,"
            "volume=0.30", at - 0.7)  # riser into the hit
        add("aevalsrc='sin(2*PI*(38+55*exp(-t*14))*t)*exp(-t*3.2)':s=44100:d=1.4,volume=0.75", at)
    parts.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=longest,"
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
