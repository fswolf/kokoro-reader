# Kokoro Reader TTS server
FROM python:3.12-slim
LABEL org.opencontainers.image.source=https://github.com/fswolf/kokoro-reader

RUN apt-get update \
 && apt-get install -y --no-install-recommends espeak-ng \
 && rm -rf /var/lib/apt/lists/*

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/cache/huggingface \
    KOKORO_HOST=0.0.0.0 \
    KOKORO_PORT=8899 \
    KOKORO_VOICE=am_adam \
    KOKORO_LANG=a

WORKDIR /app

# CPU-only torch first: the default wheels pull CUDA and balloon the image to ~6 GB.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY server/requirements.txt .
RUN pip install -r requirements.txt

COPY server/kokoro_server.py .

EXPOSE 8899
VOLUME ["/cache/huggingface"]

# Generous start period: the first run downloads ~330 MB of model weights.
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8899/health', timeout=3).status == 200 else 1)"

CMD ["python", "kokoro_server.py"]
