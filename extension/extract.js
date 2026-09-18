// Injected on demand. Returns {title, chunks:[string]} as the script result.
(() => {
  const BLOCKS = 'p,li,blockquote,h1,h2,h3,h4,h5,h6,pre,dd,dt,figcaption,td,summary';
  const DROP = /^(script|style|noscript|nav|aside|footer|header|form|button|select|textarea|svg|iframe|video|audio|template)$/i;
  const JUNK = /(^|[\s_-])(nav|menu|sidebar|footer|header|comment|share|social|promo|advert|banner|cookie|newsletter|related|breadcrumb|pagination|subscribe|modal|popup|toolbar)([\s_-]|$)/i;
  const MAX = 300;   // target chars per spoken chunk
  const HARD = 420;  // never exceed

  const visible = (el) => {
    if (!el.isConnected) return false;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || +s.opacity === 0) return false;
    if (el.getAttribute('aria-hidden') === 'true') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0;
  };

  const junky = (el) => {
    const id = (el.id || '') + ' ' + (typeof el.className === 'string' ? el.className : '');
    const role = el.getAttribute('role') || '';
    return JUNK.test(id) || /^(navigation|banner|complementary|contentinfo|search)$/.test(role);
  };

  const linkDensity = (el) => {
    const total = (el.textContent || '').length || 1;
    let linked = 0;
    for (const a of el.querySelectorAll('a')) linked += (a.textContent || '').length;
    return linked / total;
  };

  function pickRoot() {
    const explicit = document.querySelector('article, main, [role="main"], [itemprop="articleBody"]');
    const pool = [...document.querySelectorAll('article, main, [role="main"], div, section')];
    let best = null, bestScore = 0;
    for (const el of pool) {
      if (junky(el) || !visible(el)) continue;
      let score = 0;
      for (const p of el.querySelectorAll('p,li,blockquote,pre')) {
        const len = (p.textContent || '').trim().length;
        if (len > 40) score += len;
      }
      if (!score) continue;
      score *= (1 - Math.min(linkDensity(el), 0.9));
      if (/^(article|main)$/i.test(el.tagName)) score *= 1.4;
      if (score > bestScore) { bestScore = score; best = el; }
    }
    if (explicit && best && !explicit.contains(best) && !best.contains(explicit)) {
      // trust the semantic tag when the heuristic wandered off into a sidebar
      return explicit;
    }
    return best || explicit || document.body;
  }

  function collect(root) {
    const out = [];
    const h1 = document.querySelector('h1');
    if (h1 && visible(h1)) out.push((h1.textContent || '').trim());
    for (const el of root.querySelectorAll(BLOCKS)) {
      if (DROP.test(el.tagName) || !visible(el)) continue;
      if (el.closest('nav,aside,footer,header,form') && !root.matches('nav,aside,footer,header,form')) continue;
      if (junky(el)) continue;
      if (el.querySelector(BLOCKS)) continue;            // container, not a leaf
      const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
      if (t.length < 2) continue;
      if (linkDensity(el) > 0.8 && t.length < 120) continue;
      out.push(el.tagName === 'PRE' ? t.slice(0, 600) : t);
    }
    return out;
  }

  const DOT = '';
  const ABBR = /\b(mr|mrs|ms|dr|prof|rev|sr|jr|st|mt|vs|etc|no|fig|eq|approx|inc|ltd|llc|dept|est|al|ca|vol|pp|ed|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|mon|tue|wed|thu|fri|sat|sun)\./gi;

  // Hide dots that don't end sentences so the splitter can't break inside them.
  const protect = (t) => t
    .replace(/(\d)\.(\d)/g, '$1' + DOT + '$2')          // 3.5
    .replace(/\b(?:[a-z]\.){2,}/gi, (m) => m.replace(/\./g, DOT))  // e.g. U.S.A. a.m.
    .replace(ABBR, (m) => m.slice(0, -1) + DOT)
    .replace(/\b([A-Z])\.(?=\s+[A-Z])/g, '$1' + DOT);   // J. R. R. Tolkien
  const restore = (t) => t.split(DOT).join('.');

  function sentences(text) {
    const parts = protect(text).match(/[^.!?…]+(?:[.!?…]+["'”’)\]]*|$)/g) || [text];
    const out = [];
    for (let p of parts) {
      p = restore(p).trim();
      if (!p) continue;
      const prev = out[out.length - 1];
      if (prev && /^[a-z)\]]/.test(p)) out[out.length - 1] = prev + ' ' + p;
      else out.push(p);
    }
    return out;
  }

  function splitLong(s) {
    if (s.length <= HARD) return [s];
    const out = [];
    let buf = '';
    for (const piece of s.split(/(?<=[,;:—–)])\s+/)) {
      if ((buf + ' ' + piece).trim().length > HARD && buf) { out.push(buf.trim()); buf = piece; }
      else buf = (buf ? buf + ' ' : '') + piece;
    }
    if (buf.trim()) out.push(buf.trim());
    // still too long (no punctuation at all) -> hard word wrap
    return out.flatMap((x) => {
      if (x.length <= HARD) return [x];
      const words = x.split(' ');
      const acc = [];
      let b = '';
      for (const w of words) {
        if ((b + ' ' + w).length > HARD && b) { acc.push(b); b = w; } else b = b ? b + ' ' + w : w;
      }
      if (b) acc.push(b);
      return acc;
    });
  }

  function chunk(lines) {
    const out = [];
    let buf = '';
    const flush = () => { if (buf.trim()) out.push(buf.trim()); buf = ''; };
    for (const line of lines) {
      for (const s of sentences(line)) {
        for (const piece of splitLong(s)) {
          if (!buf) { buf = piece; continue; }
          if (buf.length + piece.length + 1 <= MAX) buf += ' ' + piece;
          else { flush(); buf = piece; }
        }
      }
      flush(); // don't run paragraphs together
    }
    flush();
    // de-dupe consecutive repeats and drop noise-only chunks
    return out.filter((c, i) => c !== out[i - 1] && /[A-Za-z0-9À-ɏ]/.test(c));
  }

  const root = pickRoot();
  const lines = collect(root);
  const chunks = chunk(lines.length > 1 ? lines : collect(document.body));
  return { title: document.title || '', url: location.href, chunks };
})();
