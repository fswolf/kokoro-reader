#!/bin/bash
# Kokoro Reader TTS server
set -e
cd "$(dirname "$0")"   # plain dirname: macOS readlink has no -f

export KOKORO_HOST=127.0.0.1
export KOKORO_PORT=8899
export KOKORO_VOICE=am_adam
# export KOKORO_LANG=a        # a=American, b=British
# export KOKORO_DEVICE=cuda   # cuda (NVIDIA/ROCm) or mps (Apple Silicon)

# Use the first venv we find, else whatever python3 is on PATH.
for venv in .venv ../.venv "$HOME/ai-voice-venv"; do
  if [ -x "$venv/bin/python" ]; then
    exec "$venv/bin/python" kokoro_server.py
  fi
done

echo "No venv found — using system python3." >&2
echo "To set one up:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
exec python3 kokoro_server.py
