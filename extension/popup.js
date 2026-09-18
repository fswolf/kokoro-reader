const FALLBACK_VOICES = [
  'am_adam', 'am_michael', 'am_onyx', 'am_liam', 'am_puck', 'am_echo', 'am_eric', 'am_fenrir',
  'bm_george', 'bm_lewis', 'bm_daniel', 'bm_fable',
  'af_bella', 'af_heart', 'af_nicole', 'af_sarah', 'af_sky', 'af_aoede', 'af_kore', 'af_nova',
  'bf_emma', 'bf_isabella', 'bf_alice', 'bf_lily'
];
const $ = (id) => document.getElementById(id);
const send = (type, extra) => browser.runtime.sendMessage({ type, ...extra }).catch(() => null);

let cfg = {};

function paint(s) {
  if (!s) return;
  cfg = s.cfg || cfg;
  $('prog').textContent = s.total ? `${s.i + 1} / ${s.total}` : '';
  $('now').textContent = s.state === 'loading' ? 'Synthesizing…' : (s.text || '');
  $('now').style.display = (s.text || s.state === 'loading') ? '' : 'none';
  $('toggle').textContent = s.state === 'paused' ? 'Resume' : 'Pause';
  $('toggle').disabled = s.state === 'idle';
  $('prev').disabled = $('next').disabled = !s.total;
  $('read').textContent = s.state === 'idle' ? 'Read page' : 'Restart';
  $('err').textContent = s.error || '';
}

async function health() {
  const url = (cfg.server || 'http://127.0.0.1:8899').replace(/\/+$/, '');
  try {
    const r = await fetch(url + '/health', { cache: 'no-store' });
    if (!r.ok) throw 0;
    $('dot').className = 'dot up';
    $('dot').title = 'server up';
    const v = await fetch(url + '/voices').then((x) => x.json()).catch(() => null);
    if (v && v.voices) fillVoices(v.voices);
  } catch {
    $('dot').className = 'dot down';
    $('dot').title = 'server unreachable — start start_server.sh';
    $('err').textContent = 'Server unreachable at ' + url;
  }
}

function fillVoices(list) {
  const sel = $('voice');
  sel.innerHTML = '';
  for (const v of list) {
    const o = document.createElement('option');
    o.value = v;
    o.textContent = v;
    sel.appendChild(o);
  }
  sel.value = cfg.voice || list[0];
}

(async () => {
  const s = await send('status');
  paint(s);
  fillVoices(FALLBACK_VOICES);
  $('speed').value = cfg.speed ?? 1;
  $('volume').value = cfg.volume ?? 1;
  $('server').value = cfg.server || 'http://127.0.0.1:8899';
  $('speedv').textContent = (+$('speed').value).toFixed(2) + '×';
  health();
})();

browser.runtime.onMessage.addListener((m) => { if (m.type === 'status') paint(m); });

$('read').onclick = () => send('read').then(paint);
$('stop').onclick = () => send('stop').then(paint);
$('toggle').onclick = () => send('toggle').then(paint);
$('next').onclick = () => send('next').then(paint);
$('prev').onclick = () => send('prev').then(paint);

$('voice').onchange = (e) => browser.storage.local.set({ voice: e.target.value }).then(() => send('reload'));
$('speed').oninput = (e) => { $('speedv').textContent = (+e.target.value).toFixed(2) + '×'; };
$('speed').onchange = (e) => browser.storage.local.set({ speed: +e.target.value }).then(() => send('reload'));
$('volume').onchange = (e) => browser.storage.local.set({ volume: +e.target.value });
$('server').onchange = (e) => browser.storage.local.set({ server: e.target.value.trim() }).then(health);
