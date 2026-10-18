#!/usr/bin/env python3
"""Local Kokoro TTS HTTP server for the Firefox screen reader extension.

Stdlib only + kokoro/numpy (already in ~/ai-voice-venv).

  GET  /health          -> {"ok":true,"voice":...,"loaded":bool}
  GET  /voices          -> {"voices":[...],"blends":{...}}
  POST /tts             -> audio/wav   body: {"text":..,"voice":..,"speed":1.0}

Voices can be blended. A Kokoro voice is a [510,1,256] embedding tensor,
so a weighted average of two of them is itself a valid voice - one that
exists nowhere else, at no cost in speed, because the model does the
same amount of work either way.

  "af_bella"                  a stock voice, as before
  "af_bella,af_sky"           equal mix
  "af_bella:0.7,af_sky:0.3"   weighted; weights are normalised
  "luna"                      a name from blends.json

blends.json sits beside this file and maps names to recipes:

  {"luna": "af_bella:0.6,af_sky:0.4"}

so the client only ever has to say "luna", and retuning her doesn't
mean editing every client that talks to this server.

Env: KOKORO_HOST KOKORO_PORT KOKORO_LANG KOKORO_DEVICE KOKORO_VOICE
"""
import io
import json
import os
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

HOST = os.environ.get("KOKORO_HOST", "127.0.0.1")
PORT = int(os.environ.get("KOKORO_PORT", "8899"))
LANG = os.environ.get("KOKORO_LANG", "a")
DEVICE = os.environ.get("KOKORO_DEVICE", "")  # "cuda" / "cpu" / "" = auto
DEFAULT_VOICE = os.environ.get("KOKORO_VOICE", "am_adam")
SR = 24000
MAX_CHARS = 1200

VOICES = [
    "am_adam", "am_michael", "am_onyx", "am_liam", "am_puck", "am_echo",
    "am_eric", "am_fenrir", "am_santa",
    "bm_george", "bm_lewis", "bm_daniel", "bm_fable",
    "af_bella", "af_heart", "af_nicole", "af_sarah", "af_sky", "af_aoede",
    "af_kore", "af_nova", "af_river", "af_alloy", "af_jessica",
    "bf_emma", "bf_isabella", "bf_alice", "bf_lily",
]

BLENDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "blends.json")

_pipe = None
_lock = threading.Lock()
_blend_cache = {}


def blends():
    """Named recipes. Re-read per call so editing the file takes effect
    without a restart - it is a few hundred bytes and nobody is calling
    /voices in a loop."""
    try:
        with open(BLENDS_FILE) as f:
            data = json.load(f)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception:
        return {}


def parse_blend(spec):
    """'af_bella:0.6,af_sky:0.4' -> [('af_bella',0.6), ('af_sky',0.4)].

    Weights are normalised, so 6:4, 60:40 and 0.6:0.4 all mean the same
    thing and nobody has to make them sum to one. A missing weight is 1.
    """
    parts = []
    for piece in spec.split(","):
        piece = piece.strip()
        if not piece:
            continue
        name, _, weight = piece.partition(":")
        name = name.strip()
        if not name:
            continue
        try:
            w = float(weight) if weight.strip() else 1.0
        except ValueError:
            w = 1.0
        if w > 0:
            parts.append((name, w))
    total = sum(w for _, w in parts)
    return [(n, w / total) for n, w in parts] if total > 0 else []


def voice_for(name):
    """What to hand KPipeline: a plain name, or a blended tensor.

    Plain names are passed through as strings untouched, so the common
    path behaves exactly as it did before this existed.
    """
    name = (name or "").strip()
    recipes = blends()
    spec = recipes.get(name, name)

    if "," not in spec and ":" not in spec:
        return spec or DEFAULT_VOICE

    if spec in _blend_cache:
        return _blend_cache[spec]

    parts = parse_blend(spec)
    if not parts:
        return DEFAULT_VOICE
    if len(parts) == 1:
        return parts[0][0]

    mixed = None
    for voice_name, weight in parts:
        pack = pipe().load_voice(voice_name)
        contribution = pack * weight
        mixed = contribution if mixed is None else mixed + contribution

    _blend_cache[spec] = mixed
    print("blended %s -> %s" % (name, spec), flush=True)
    return mixed


def pipe():
    global _pipe
    if _pipe is None:
        from kokoro import KPipeline
        kw = {"lang_code": LANG, "repo_id": "hexgrad/Kokoro-82M"}
        if DEVICE:
            kw["device"] = DEVICE
        try:
            _pipe = KPipeline(**kw)
        except TypeError:
            kw.pop("device", None)
            _pipe = KPipeline(**kw)
    return _pipe


def synth(text, voice, speed):
    out = []
    for _, _, audio in pipe()(text, voice=voice, speed=speed):
        out.append(np.asarray(audio, dtype=np.float32).reshape(-1))
    if not out:
        return np.zeros(1, dtype=np.float32)
    return np.concatenate(out)


def wav_bytes(samples):
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "KokoroReader/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._json(200, {"ok": True, "voice": DEFAULT_VOICE,
                             "loaded": _pipe is not None, "lang": LANG})
        elif path == "/voices":
            recipes = blends()
            self._json(200, {"voices": sorted(recipes) + VOICES,
                             "blends": recipes,
                             "default": DEFAULT_VOICE})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/tts":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            text = (req.get("text") or "").strip()[:MAX_CHARS]
            voice = req.get("voice") or DEFAULT_VOICE
            speed = float(req.get("speed") or 1.0)
        except Exception as e:
            return self._json(400, {"error": "bad request: %s" % e})

        if not text:
            return self._json(400, {"error": "empty text"})
        speed = min(max(speed, 0.5), 2.0)

        try:
            with _lock:
                audio = synth(text, voice_for(voice), speed)
            self._send(200, wav_bytes(audio), "audio/wav")
        except Exception as e:
            self.log_message("tts failed: %s", e)
            self._json(500, {"error": str(e)})


def main():
    print("Loading Kokoro (%s, device=%s)..." % (LANG, DEVICE or "auto"), flush=True)
    pipe()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    srv.daemon_threads = True
    print("Kokoro reader server on http://%s:%d  (voice %s)" % (HOST, PORT, DEFAULT_VOICE), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        srv.server_close()


if __name__ == "__main__":
    main()
