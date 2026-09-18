const DEFAULTS = {
  server: 'http://127.0.0.1:8899',
  voice: 'am_adam',
  speed: 1.0,
  volume: 1.0,
  lookahead: 2
};

let cfg = { ...DEFAULTS };
let S = {
  chunks: [],
  i: 0,
  state: 'idle',          // idle | loading | playing | paused
  title: '',
  tabId: null,
  cache: new Map(),       // index -> Promise<objectURL>
  audio: null,
  token: 0,               // invalidates stale playback callbacks
  error: ''
};

browser.storage.local.get(DEFAULTS).then((v) => { cfg = { ...DEFAULTS, ...v }; });
browser.storage.onChanged.addListener((ch) => {
  for (const k in ch) cfg[k] = ch[k].newValue;
  if (S.audio && 'volume' in ch) S.audio.volume = clamp(cfg.volume, 0, 1);
});

const clamp = (n, lo, hi) => Math.min(Math.max(+n || 0, lo), hi);
const status = () => ({
  state: S.state, i: S.i, total: S.chunks.length,
  title: S.title, text: S.chunks[S.i] || '', error: S.error, cfg
});

function push() {
  browser.runtime.sendMessage({ type: 'status', ...status() }).catch(() => {});
}

// ---------- synthesis ----------
function synth(index) {
  if (S.cache.has(index)) return S.cache.get(index);
  const text = S.chunks[index];
  if (text === undefined) return null;
  const p = fetch(cfg.server.replace(/\/+$/, '') + '/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice: cfg.voice, speed: clamp(cfg.speed, 0.5, 2) })
  }).then(async (r) => {
    if (!r.ok) throw new Error('server ' + r.status + ': ' + (await r.text()).slice(0, 200));
    return URL.createObjectURL(await r.blob());
  });
  S.cache.set(index, p);
  return p;
}

function prefetch() {
  for (let k = 1; k <= cfg.lookahead; k++) {
    const j = S.i + k;
    if (j < S.chunks.length) (synth(j) || Promise.resolve()).catch(() => {});
  }
}

function dropCache(before) {
  for (const [k, p] of S.cache) {
    if (k < before) {
      p.then((u) => URL.revokeObjectURL(u)).catch(() => {});
      S.cache.delete(k);
    }
  }
}

// ---------- playback ----------
function stopAudio() {
  S.token++;
  if (S.audio) { S.audio.onended = null; S.audio.onerror = null; S.audio.pause(); S.audio.src = ''; S.audio = null; }
}

async function playAt(index) {
  if (index < 0 || index >= S.chunks.length) return finish();
  S.i = index;
  S.error = '';
  dropCache(index);
  stopAudio();
  const token = S.token;
  S.state = 'loading';
  push();
  prefetch();

  let url;
  try {
    url = await synth(index);
  } catch (e) {
    S.error = String(e.message || e);
    S.state = 'idle';
    return push();
  }
  if (token !== S.token) return;

  const a = new Audio(url);
  a.volume = clamp(cfg.volume, 0, 1);
  S.audio = a;
  a.onended = () => { if (token === S.token) playAt(index + 1); };
  a.onerror = () => {
    if (token !== S.token) return;
    S.error = 'audio decode failed';
    S.state = 'idle';
    push();
  };
  try {
    await a.play();
    S.state = 'playing';
  } catch (e) {
    S.error = String(e.message || e);
    S.state = 'idle';
  }
  push();
}

function finish() {
  stopAudio();
  dropCache(Infinity);
  S.state = 'idle';
  S.i = 0;
  S.chunks = [];
  push();
}

function stop() {
  S.chunks = [];
  finish();
}

// ---------- entry points ----------
async function readTab(tabId) {
  stop();
  S.tabId = tabId;
  try {
    const res = await browser.tabs.executeScript(tabId, { file: '/extract.js' });
    const data = (res && res[0]) || {};
    const chunks = (data.chunks || []).filter((c) => c && c.trim());
    if (!chunks.length) { S.error = 'No readable text found on this page.'; S.state = 'idle'; return push(); }
    S.chunks = chunks;
    S.title = data.title || '';
    playAt(0);
  } catch (e) {
    S.error = 'Cannot read this page (' + (e.message || e) + ')';
    S.state = 'idle';
    push();
  }
}

function readText(text, title) {
  stop();
  const chunks = String(text).split(/\n{2,}/).map((s) => s.replace(/\s+/g, ' ').trim()).filter(Boolean);
  if (!chunks.length) return;
  S.chunks = chunks;
  S.title = title || 'Selection';
  playAt(0);
}

function pause() {
  if (S.state === 'playing' && S.audio) { S.audio.pause(); S.state = 'paused'; push(); }
}
function resume() {
  if (S.state === 'paused' && S.audio) { S.audio.play().catch(() => {}); S.state = 'playing'; push(); }
}
function toggle() {
  if (S.state === 'playing') pause();
  else if (S.state === 'paused') resume();
  else browser.tabs.query({ active: true, currentWindow: true }).then((t) => t[0] && readTab(t[0].id));
}
const skip = (n) => { if (S.chunks.length) playAt(clamp(S.i + n, 0, S.chunks.length - 1)); };

// ---------- wiring ----------
browser.runtime.onMessage.addListener((msg) => {
  switch (msg.type) {
    case 'read': return browser.tabs.query({ active: true, currentWindow: true })
      .then((t) => t[0] && readTab(t[0].id)).then(() => status());
    case 'readText': readText(msg.text, msg.title); return Promise.resolve(status());
    case 'pause': pause(); break;
    case 'resume': resume(); break;
    case 'toggle': toggle(); break;
    case 'stop': stop(); break;
    case 'next': skip(1); break;
    case 'prev': skip(-1); break;
    case 'restart': if (S.chunks.length) playAt(0); break;
    case 'status': break;
    case 'reload':
      if (S.chunks.length) { dropCache(Infinity); playAt(S.i); }
      break;
  }
  return Promise.resolve(status());
});

browser.commands.onCommand.addListener((c) => {
  if (c === 'toggle-read') toggle();
  else if (c === 'stop-read') stop();
  else if (c === 'next-chunk') skip(1);
  else if (c === 'prev-chunk') skip(-1);
});

browser.contextMenus.create({
  id: 'kokoro-read-selection',
  title: 'Read selection with Kokoro',
  contexts: ['selection']
});
browser.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === 'kokoro-read-selection' && info.selectionText) {
    readText(info.selectionText, 'Selection');
  }
});

browser.tabs.onRemoved.addListener((id) => { if (id === S.tabId) stop(); });
