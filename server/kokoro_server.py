#!/usr/bin/env python3
"""Local Kokoro TTS HTTP server for the Firefox screen reader extension.

Stdlib only + kokoro/numpy (already in ~/ai-voice-venv).

  GET  /health          -> {"ok":true,"voice":...,"loaded":bool}
  GET  /voices          -> {"voices":[...]}
  POST /tts             -> audio/wav   body: {"text":..,"voice":..,"speed":1.0}

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

_pipe = None
_lock = threading.Lock()


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
            self._json(200, {"voices": VOICES, "default": DEFAULT_VOICE})
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
                audio = synth(text, voice, speed)
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
