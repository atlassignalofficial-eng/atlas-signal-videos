"""Narration engines.

  azure - Microsoft Azure AI Speech (official REST API). The free F0 tier gives
          0.5M characters/month; generated audio may be used commercially.
          Needs AZURE_SPEECH_KEY and AZURE_SPEECH_REGION in the environment.
  piper - local neural TTS (https://github.com/OHF-Voice/piper1-gpl), free and offline.

Only voices cleared for COMMERCIAL use are listed: the channel is meant to be
monetised. (e.g. Piper en_US-ryan is CC BY-NC-SA and is excluded; edge-tts is
excluded because it uses the Edge browser's read-aloud service, which is not
licensed for commercial use.)
"""
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

PIPER_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
VOICES = {  # name: (engine, voice id, licence note)
    "andrew": ("azure", "en-US-AndrewNeural", "Azure AI Speech output (commercial use allowed)"),
    "andrew-ml": ("azure", "en-US-AndrewMultilingualNeural", "Azure AI Speech output (commercial use allowed)"),
    "joe": ("piper", "en/en_US/joe/medium/en_US-joe-medium", "CC0"),
    "john": ("piper", "en/en_US/john/medium/en_US-john-medium", "public domain (LibriVox)"),
    "norman": ("piper", "en/en_US/norman/medium/en_US-norman-medium", "public domain (LibriVox)"),
}


def licence(name: str) -> str:
    return VOICES[name][2]


def synthesize(text: str, out_wav, voice: str, cache_dir, opener=urllib.request.urlopen,
               rate: str | None = None) -> Path:
    """`rate` is a speed change such as "+10%" (Azure voices only)."""
    if voice not in VOICES:
        raise ValueError(f"voice {voice!r} is not cleared for commercial use; pick from {sorted(VOICES)}")
    engine, vid, _ = VOICES[voice]
    if engine == "azure":
        return _azure(text, Path(out_wav), vid, opener, rate)
    model = _piper_model(vid, cache_dir)
    subprocess.run([sys.executable, "-m", "piper", "-m", str(model), "-f", str(out_wav)],
                   input=text, text=True, check=True, capture_output=True)
    return Path(out_wav)


def _azure(text, out_wav: Path, voice_id, opener, rate=None) -> Path:
    key, region = os.environ.get("AZURE_SPEECH_KEY"), os.environ.get("AZURE_SPEECH_REGION")
    if not key or not region:
        raise RuntimeError("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION must be set for Azure voices")
    body = escape(text)
    if rate:
        if not re.fullmatch(r"[+-]\d{1,2}%", rate):
            raise ValueError(f"bad voice rate {rate!r}; use e.g. '+10%'")
        body = f"<prosody rate='{rate}'>{body}</prosody>"
    ssml = f"<speak version='1.0' xml:lang='en-US'><voice name='{voice_id}'>{body}</voice></speak>"
    req = urllib.request.Request(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1", ssml.encode(),
        headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
                 "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
                 "User-Agent": "blueprints-uncovered"})
    with opener(req) as r:
        audio = r.read()
    if not audio.startswith(b"RIFF"):
        raise RuntimeError("Azure Speech returned no audio")
    out_wav.write_bytes(audio)
    return out_wav


def _piper_model(rel: str, cache_dir) -> Path:
    model = Path(cache_dir) / (Path(rel).name + ".onnx")
    for dest, suffix in ((model, ".onnx"), (Path(str(model) + ".json"), ".onnx.json")):
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            urllib.request.urlretrieve(PIPER_HF + rel + suffix, tmp)
            tmp.rename(dest)
    return model


def duration(path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True)
    return float(out.stdout.strip())
