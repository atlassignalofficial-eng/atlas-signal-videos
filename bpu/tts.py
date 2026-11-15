"""Local neural narration with Piper (https://github.com/OHF-Voice/piper1-gpl).

Only voices whose training data allows COMMERCIAL use are listed: the channel
is meant to be monetised. (e.g. en_US-ryan is CC BY-NC-SA and is excluded.)
"""
import subprocess
import sys
import urllib.request
from pathlib import Path

HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
VOICES = {  # name: (model path on HF, dataset licence from the model card)
    "joe": ("en/en_US/joe/medium/en_US-joe-medium", "CC0"),
    "john": ("en/en_US/john/medium/en_US-john-medium", "public domain (LibriVox)"),
    "norman": ("en/en_US/norman/medium/en_US-norman-medium", "public domain (LibriVox)"),
}


def voice_model(name: str, cache_dir) -> Path:
    if name not in VOICES:
        raise ValueError(f"voice {name!r} is not cleared for commercial use; pick from {sorted(VOICES)}")
    rel = VOICES[name][0]
    model = Path(cache_dir) / (Path(rel).name + ".onnx")
    for suffix in (".onnx", ".onnx.json"):
        dest = model.with_suffix(suffix) if suffix == ".onnx" else Path(str(model) + ".json")
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            urllib.request.urlretrieve(HF + rel + suffix, tmp)
            tmp.rename(dest)
    return model


def synthesize(text: str, out_wav, model: Path) -> Path:
    subprocess.run([sys.executable, "-m", "piper", "-m", str(model), "-f", str(out_wav)],
                   input=text, text=True, check=True, capture_output=True)
    return Path(out_wav)


def duration(path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True)
    return float(out.stdout.strip())
