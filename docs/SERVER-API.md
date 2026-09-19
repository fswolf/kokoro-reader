# Server API

`server/kokoro_server.py`. Stdlib `ThreadingHTTPServer`, HTTP/1.1, `Content-Length` always
set. Binds `127.0.0.1:8899` by default. No authentication. `Access-Control-Allow-Origin: *`
so browser extensions can call it.

Everything a client needs is these three endpoints.

## GET /health

```json
{"ok": true, "voice": "am_adam", "loaded": true, "lang": "a"}
```

`loaded` is false until the model finishes loading (a few seconds on first start).
Use this for a reachability check — it never blocks on synthesis.

## GET /voices

```json
{"voices": ["am_adam", "am_michael", ...], "default": "am_adam"}
```

The list is hardcoded in `VOICES`, not queried from the model. A voice outside the list may
still work; a voice Kokoro doesn't recognise comes back as a 500.

## POST /tts

Request:

```json
{"text": "Hello there.", "voice": "am_adam", "speed": 1.0}
```

`voice` and `speed` are optional. Response is `audio/wav`.

| | |
|---|---|
| Format | 16-bit signed PCM, mono, 24000 Hz |
| `text` | **truncated to 1200 chars, silently** (`MAX_CHARS`) |
| `speed` | clamped to 0.5–2.0 |
| Empty `text` | `400 {"error": "empty text"}` |
| Malformed JSON | `400 {"error": "bad request: ..."}` |
| Synthesis failure | `500 {"error": "..."}` |
| Other paths | `404` |

```bash
curl -s localhost:8899/health

curl -s -X POST localhost:8899/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"Testing.","voice":"am_adam"}' -o out.wav
```

## What the server does not do

Worth knowing before writing a client, because it shapes where the work lands:

- **No streaming.** The whole WAV is synthesized and buffered before the response is sent,
  so time-to-first-audio scales with text length. Send a sentence, not a page.
- **Synthesis is serialized.** A mutex around the Kokoro pipeline means concurrent requests
  queue. Two clients at once (say the extension and a MUD script) take turns.
- **No sentence splitting.** The server speaks exactly what you send it. All the chunking,
  lookahead and playback queueing lives in `extension/extract.js` and
  `extension/background.js`.
- **No caching.** Identical text is re-synthesized every time.

The first three mean a second client either reimplements the chunking or the splitting moves
server-side into a `/speak` endpoint that chunks internally and streams. The latter is the
better shape once there's more than one client.

## Environment

Read at startup by `kokoro_server.py`:

| Variable | Default | |
|---|---|---|
| `KOKORO_HOST` | `127.0.0.1` | loopback; see the README's security note |
| `KOKORO_PORT` | `8899` | |
| `KOKORO_VOICE` | `am_adam` | used when a request omits `voice` |
| `KOKORO_LANG` | `a` | `a` American, `b` British |
| `KOKORO_DEVICE` | auto | `cuda` to force GPU |

## Clients

- `extension/` — the Firefox extension
- `server/kokoro_tray.py` — tray app; polls `/health`, and its "Test voice" is a `/tts` call
