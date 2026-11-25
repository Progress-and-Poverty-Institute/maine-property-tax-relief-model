/* Maine Property Tax Relief Explorer.
 *
 * Every number on the page is read from data/dashboard.json (the model's data
 * bundle) or data/findings.csv (generated from it). Prose comes from
 * data/copy_x.json (Explorer-Ready Copy and the page intros, from 10-19) and,
 * for the About page and the scenario table's program columns, data/copy.json
 * (Report-Ready Copy). Nothing numeric is typed in here.
 *
 * NAMING TRAP. The bundle still carries the pre-rename codes: bundle "broad"
 * B1-B6 are the Representative Archetypes R1-R6, and bundle "narrow" N1-N7 are
 * the Burdened Archetypes B1-B7. The two schemes collide on B1-B6. Codes are
 * translated once, in buildArchetypes(), and a bundle code is never displayed.
 */
(() => {
'use strict';

// Everything the page loads is found relative to this script, so the tool works
// at /maine-tax-relief-explorer and /maine-tax-relief-explorer/ alike (the site's
// Next.js host drops trailing slashes) and on any host it is copied to.
const BASE = new URL('.', document.currentScript.src);
const at = (p) => new URL(p, BASE).href;

const $ = (s, r = document) => r.querySelector(s);
const main = $('#main');
let D, COPY, CX, FIND, ARCH, SCEN;
const warnings = [];
const redraws = [];

// ------------------------------------------------------------ formatting
const MINUS = '−';
const sign = (x) => (x < 0 ? MINUS : '');
const fmt = {
  int: (x) => Math.round(x).toLocaleString('en-US'),
  m: (x) => sign(x) + '$' + (Math.abs(x) / 1e6).toFixed(1) + 'm',
  usd: (x) => sign(Math.round(x)) + '$' + Math.abs(Math.round(x)).toLocaleString('en-US'),
  usdS: (x) => (Math.round(x) > 0 ? '+' : sign(Math.round(x))) + '$' + Math.abs(Math.round(x)).toLocaleString('en-US'),
  pct: (x, d = 1) => { const t = (Math.abs(x) * 100).toFixed(d); return (Number(t) === 0 ? '' : sign(x)) + t + '%'; },
  pctS: (x, d = 1) => { const t = (Math.abs(x) * 100).toFixed(d); return (Number(t) === 0 ? '' : x > 0 ? '+' : sign(x)) + t + '%'; },
  mills: (r) => (r * 1000).toFixed(2) + ' mills',
  k: (x) => {
    const a = Math.abs(x);
    if (a >= 1e6) return sign(x) + (a / 1e6).toFixed(a >= 1e7 ? 0 : 1) + 'm';
    if (a >= 1e3) return sign(x) + (a / 1e3).toFixed(a >= 1e4 ? 0 : 1).replace(/\.0$/, '') + 'k';
    return sign(x) + Math.round(a);
  },
  // Bar labels. k1: thousands to one decimal ("5.7k"); kc: rounded thousands ("512k"), finer below 10,000.
  k1: (x) => (Math.round(x) === 0 ? '0' : (x / 1e3).toFixed(1) + 'k'),
  kc: (x) => { const a = Math.abs(x); return a >= 1e4 ? Math.round(a / 1e3) + 'k' : a >= 1e3 ? (a / 1e3).toFixed(1) + 'k' : String(Math.round(a)); },
  usd10: (x) => fmt.usd(Math.round(x / 10) * 10),
  usd100: (x) => fmt.usd(Math.round(x / 100) * 100),
  usdS10: (x) => fmt.usdS(Math.round(x / 10) * 10),
};
// Rounded shares that sum to 100% (largest remainder), for rows a reader will add up.
function shares100(vals) {
  const t = sum(vals), raw = vals.map((v) => (t ? (v / t) * 100 : 0)), fl = raw.map(Math.floor);
  let left = 100 - sum(fl);
  raw.map((r, i) => [r - fl[i], i]).sort((a, b) => b[0] - a[0]).forEach(([, i]) => { if (left > 0) { fl[i] += 1; left -= 1; } });
  return fl.map((x) => x + '%');
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const stripTags = (h) => h.replace(/<[^>]+>/g, '');
const sum = (a) => a.reduce((x, y) => x + y, 0);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'html') el.innerHTML = v;
    else if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(kid));
  }
  return el;
}

// ------------------------------------------------------------ data
function parseCSV(text) {
  const rows = [];
  let row = [], cell = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') q = false;
      else cell += c;
    } else if (c === '"') q = true;
    else if (c === ',') { row.push(cell); cell = ''; }
    else if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; }
    else if (c !== '\r') cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  const head = rows.shift();
  return rows.filter((r) => r.length > 1).map((r) => Object.fromEntries(head.map((k, i) => [k, r[i] ?? ''])));
}

function sec(tab, prefix) {
  // A tab's own "# " heading often shares its title with the section under it; prefer the one with content.
  const all = COPY.sections.filter((s) => s.tab === tab && s.title.startsWith(prefix));
  return all.find((s) => s.blocks.length && s.level > 1) || all[0];
}

function buildArchetypes() {
  const mk = (rows, set) => rows.map((p) => {
    const bcode = p.archetype.split(' ')[0];
    const code = set === 'rep' ? 'R' + bcode.slice(1) : 'B' + bcode.slice(1);
    const name = p.archetype.slice(bcode.length + 1);
    return { code, bcode, set, name, p };
  });
  ARCH = [...mk(D.broad, 'rep'), ...mk(D.narrow, 'bur')];
  // Commercial archetypes (30 Oct 2026): parcels, not households. They carry a vignette, a
  // per-scenario explainer and a bill; no income, credit or burden. Bills come from the
  // bundle's `commercial` / `commercial_cells` blocks as given, never from a mill rate.
  for (const c of D.commercial || []) {
    const cc = (CX.com || {})[c.id];
    if (!cc) warnings.push(`No copy for commercial archetype ${c.id}.`);
    else if (cc.label.toLowerCase() !== c.label.toLowerCase()) warnings.push(`${c.id}: copy label "${cc.label}" does not match the bundle's "${c.label}".`);
    ARCH.push({ code: c.id, bcode: c.id, set: 'com', name: cc ? cc.label : c.label, c });
  }
  // Guard the rename: every published code's copy heading must name the
  // same archetype the bundle row does.
  for (const a of ARCH.filter((x) => x.set !== 'com')) {
    const c = CX.arch[a.code];
    if (!c) warnings.push(`No Explorer-Ready Copy section for ${a.code} (${a.name}).`);
    else if (c.title.toLowerCase() !== a.name.toLowerCase()) {
      warnings.push(`${a.code}: copy heading "${c.title}" does not match the model's "${a.name}". Check the code translation before publishing.`);
    }
  }
  const burTotal = sum(D.narrow.map((p) => p.households));
  for (const a of ARCH) a.shareOfSet = a.set === 'bur' ? a.p.households / burTotal : null;
}
const arch = (code) => ARCH.find((a) => a.code === code);
const archSet = (set) => ARCH.filter((a) => a.set === set);
const scen = (id) => SCEN.find((s) => s.id === String(id));
const scenGroup = (g) => SCEN.filter((s) => s.group === g);
function scenTitle(s) {
  const c = CX.scen[s.id];
  return `S${s.id}. ${c ? c.title : s.name}`;
}
const scenShort = (s) => scenTitle(s).replace(/^S\d+\.\s*/, '');
const SET_LABEL = { rep: 'Representative Archetypes', bur: 'Burdened Archetypes', com: 'Commercial Archetypes' };
const isCom = (a) => a.set === 'com';
const comCell = (a, s) => D.commercial_cells.find((r) => r.a === a.code && r.s === s.id);
const millPct = (x) => (Math.abs(x) < 0.005 ? 'No change' : (x > 0 ? '+' : MINUS) + Math.abs(x).toFixed(2) + '%');
const usdChange = (x) => (Math.abs(x) < 0.5 ? '$0' : (x > 0 ? '+$' : MINUS + '$') + Math.abs(Math.round(x)).toLocaleString('en-US'));
const lcFirst = (t) => t.charAt(0).toLowerCase() + t.slice(1);
// Key Findings are written against scenarios 1-14 only; they are shown for those two groups and
// for no other (Steve, 30 Oct 2026: with S15-S19 in view several of their claims become wrong).
const KF_GROUPS = ['cost35', 'realloc'];

// ------------------------------------------------------------ tooltip
const tip = $('#tip');
document.addEventListener('mousemove', (e) => {
  const t = e.target.closest && e.target.closest('[data-tip]');
  if (!t) { tip.hidden = true; return; }
  tip.innerHTML = t.getAttribute('data-tip');
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  let x = e.clientX + 14, y = e.clientY + 14;
  if (x + r.width > window.innerWidth - 8) x = e.clientX - r.width - 14;
  if (y + r.height > window.innerHeight - 8) y = e.clientY - r.height - 14;
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
});
document.addEventListener('scroll', () => { tip.hidden = true; }, { passive: true });

// ------------------------------------------------------------ charts
const NS = 'http://www.w3.org/2000/svg';
function niceScale(lo, hi, n = 5) {
  if (lo === hi) { hi = lo + 1; }
  const step0 = (hi - lo) / n;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const e = step0 / mag;
  const step = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * mag;
  const a = Math.floor(lo / step + 1e-9) * step, b = Math.ceil(hi / step - 1e-9) * step;
  const ticks = [];
  for (let t = a; t <= b + step / 2; t += step) ticks.push(Math.abs(t) < step / 1e6 ? 0 : t);
  return { lo: a, hi: b, ticks };
}
// Bar with a 4px rounded data-end, square at the baseline.
function barPath(x, y0, y1, w) {
  const top = Math.min(y0, y1), hgt = Math.abs(y1 - y0);
  if (hgt < 0.5) return '';
  const r = Math.min(4, hgt, w / 2);
  if (y1 <= y0) { // grows up
    return `M${x},${y0}V${top + r}Q${x},${top} ${x + r},${top}H${x + w - r}Q${x + w},${top} ${x + w},${top + r}V${y0}Z`;
  }
  const bot = top + hgt; // grows down
  return `M${x},${y0}V${bot - r}Q${x},${bot} ${x + r},${bot}H${x + w - r}Q${x + w},${bot} ${x + w},${bot - r}V${y0}Z`;
}
const colorVar = (c) => `var(--${c})`;

/* Vertical grouped bars.
 * o.cats: [{label: 'line1\nline2', tip: 'html'}]
 * o.series: [{name, color, values}]  color is a CSS token name
 * o.signColor: colour a single series by sign (gain/loss)
 * o.colors: per-bar token names for a single series */
function vbars(el, o) {
  const draw = () => {
    const W = Math.max(280, el.clientWidth || 640);
    const narrow = W < 520;
    const bandGuess = (W - 60) / o.cats.length;
    const lines = (o.compact && bandGuess < 54) ? 1 : Math.max(...o.cats.map((c) => c.label.split('\n').length));
    const H = o.height || 260;
    const rotate = o.compact && bandGuess < 40;
    const m = { l: narrow ? 44 : 56, r: 8, t: o.yTitle ? 24 : 10, b: (rotate ? 44 : 14 + 14 * lines) + (o.xTitle ? 18 : 0) };
    // Value labels above the bars: horizontal when they fit the bar, else turned upright.
    let lblVertical = false;
    if (o.labels) {
      const bw0 = Math.min(o.series.length === 1 ? 64 : 34, ((W - m.l - m.r) / o.cats.length * (o.series.length === 1 ? 0.62 : 0.8) - (o.series.length - 1) * 2) / o.series.length);
      const longest = Math.max(...o.series.flatMap((se) => se.values.filter((v) => v != null).map((v) => o.labels(v).length)));
      lblVertical = longest * 5.6 > bw0 + 6;
      m.t += lblVertical ? 6 + longest * 6 : 16;
    }
    const pw = W - m.l - m.r, ph = H - m.t - m.b;
    const all = o.series.flatMap((s) => s.values).filter((v) => v != null && isFinite(v));
    const sc = o.domain ? niceScale(Math.min(0, o.domain[0]), Math.max(0, o.domain[1]), 4)
      : niceScale(Math.min(0, ...all), Math.max(0, ...all), narrow ? 4 : 5);
    const y = (v) => m.t + ph - ((v - sc.lo) / (sc.hi - sc.lo)) * ph;
    const band = pw / o.cats.length;
    const ns = o.series.length;
    // Bars fill most of their band (a fixed thin bar floats in empty space on wide screens).
    const bw = Math.min(ns === 1 ? 64 : 34, (band * (ns === 1 ? 0.62 : 0.8) - (ns - 1) * 2) / ns);
    const gw = ns * bw + (ns - 1) * 2;
    let s = `<svg class="viz" xmlns="${NS}" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.aria || '')}">`;
    for (const t of sc.ticks) {
      s += `<line class="${t === 0 ? 'base' : 'grid'}" x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}"/>`;
      s += `<text x="${m.l - 6}" y="${y(t) + 4}" text-anchor="end">${esc(o.fmtTick(t))}</text>`;
    }
    o.cats.forEach((c, i) => {
      const gx = m.l + band * i + (band - gw) / 2;
      s += '<g class="m">';
      o.series.forEach((se, j) => {
        const v = se.values[i];
        if (v == null || !isFinite(v)) return;
        const col = o.colors ? o.colors[i] : o.signColor ? (v < 0 ? 'loss' : 'gain') : se.color;
        s += `<path class="bar" fill="${colorVar(col)}" d="${barPath(gx + j * (bw + 2), y(0), y(v), bw)}"/>`;
        if (o.labels) {
          const cx = gx + j * (bw + 2) + bw / 2, top = Math.min(y(0), y(v)) - 4;
          s += lblVertical
            ? `<text class="lbl" x="${cx + 3.5}" y="${top}" text-anchor="start" transform="rotate(-90 ${cx + 3.5} ${top})">${esc(o.labels(v))}</text>`
            : `<text class="lbl" x="${cx}" y="${top}" text-anchor="middle">${esc(o.labels(v))}</text>`;
        }
      });
      const tipHtml = `<b>${c.tip || esc(c.label.replace('\n', ' '))}</b>` + o.series.map((se) =>
        `<br>${ns > 1 ? esc(se.name) + ': ' : ''}${se.values[i] == null ? 'not modeled' : esc(o.fmt(se.values[i]))}`).join('');
      s += `<rect class="hit" x="${m.l + band * i}" y="${m.t}" width="${band}" height="${ph}" data-tip="${esc(tipHtml)}"/>`;
      s += '</g>';
      const lab = (o.compact && band < 54) ? o.compact[i] : c.label;
      if (rotate) {
        const cx = m.l + band * i + band / 2, cy = m.t + ph + 12;
        s += `<text class="cat" x="${cx}" y="${cy}" text-anchor="end" font-size="10.5" transform="rotate(-45 ${cx} ${cy})">${esc(lab)}</text>`;
        return;
      }
      lab.split('\n').forEach((ln, k) => {
        s += `<text class="cat" x="${m.l + band * i + band / 2}" y="${m.t + ph + 16 + 14 * k}" text-anchor="middle" font-size="${narrow ? 10.5 : 12}">${esc(ln)}</text>`;
      });
    });
    if (o.xTitle) s += `<text x="${m.l + pw / 2}" y="${H - 4}" text-anchor="middle">${esc(o.xTitle)}</text>`;
    if (o.yTitle) s += `<text x="0" y="11" text-anchor="start">${esc(o.yTitle)}</text>`;
    s += '</svg>';
    el.innerHTML = s;
  };
  draw();
  redraws.push({ el, draw });
}

/* Horizontal bars, one series, labels at the tips. Labels sit above the bar on narrow screens. */
function hbars(el, o) {
  const draw = () => {
    const W = Math.max(280, el.clientWidth || 640);
    const narrow = W < 600;
    const lab = narrow ? 0 : Math.min(270, W * 0.36);
    const rowH = narrow ? 40 : 28;
    const m = { l: lab + 8, r: 64, t: 6, b: 24 };
    const H = m.t + m.b + rowH * o.cats.length;
    const pw = W - m.l - m.r;
    const vals = o.values.filter((v) => v != null && isFinite(v));
    const sc = o.domain ? niceScale(Math.min(0, o.domain[0]), Math.max(0, o.domain[1]), narrow ? 3 : 5)
      : niceScale(Math.min(0, ...vals), Math.max(0, ...vals), narrow ? 3 : 5);
    const x = (v) => m.l + ((v - sc.lo) / (sc.hi - sc.lo)) * pw;
    let s = `<svg class="viz" xmlns="${NS}" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.aria || '')}">`;
    for (const t of sc.ticks) {
      s += `<line class="${t === 0 ? 'base' : 'grid'}" x1="${x(t)}" x2="${x(t)}" y1="${m.t}" y2="${H - m.b}"/>`;
      s += `<text x="${x(t)}" y="${H - 6}" text-anchor="middle">${esc(o.fmtTick(t))}</text>`;
    }
    const bh = Math.min(18, rowH - (narrow ? 22 : 10));
    o.cats.forEach((c, i) => {
      const v = o.values[i];
      const top = m.t + rowH * i;
      const by = top + (narrow ? 18 : (rowH - bh) / 2);
      if (narrow) s += `<text class="cat" x="${m.l}" y="${top + 13}">${esc(c.label)}</text>`;
      else s += `<text class="cat" x="${m.l - 8}" y="${by + bh / 2 + 4}" text-anchor="end">${esc(c.label)}</text>`;
      if (v != null && isFinite(v)) {
        const x0 = x(0), x1 = x(v), w = Math.abs(x1 - x0), r = Math.min(4, w, bh / 2);
        const col = v < 0 ? 'loss' : 'gain';
        let d = '';
        if (w >= 0.5) {
          d = v >= 0
            ? `M${x0},${by}H${x1 - r}Q${x1},${by} ${x1},${by + r}V${by + bh - r}Q${x1},${by + bh} ${x1 - r},${by + bh}H${x0}Z`
            : `M${x0},${by}H${x1 + r}Q${x1},${by} ${x1},${by + r}V${by + bh - r}Q${x1},${by + bh} ${x1 + r},${by + bh}H${x0}Z`;
        }
        s += `<path class="bar" fill="${colorVar(col)}" d="${d}"/>`;
        // Negative values are labelled just right of the zero line, so they never run into the area names.
        const lx = v >= 0 ? x1 + 5 : x0 + 5;
        s += `<text class="v" x="${lx}" y="${by + bh / 2 + 4}" text-anchor="start">${esc(o.fmt(v))}</text>`;
      }
      s += `<rect class="hit" x="0" y="${top}" width="${W}" height="${rowH}" data-tip="${esc(`<b>${esc(c.tip || c.label)}</b><br>${v == null ? 'not modeled' : esc(o.fmt(v))}`)}"/>`;
    });
    s += '</svg>';
    el.innerHTML = s;
  };
  draw();
  redraws.push({ el, draw });
}

let rto;
window.addEventListener('resize', () => {
  clearTimeout(rto);
  rto = setTimeout(() => {
    for (let i = redraws.length - 1; i >= 0; i--) {
      if (!document.body.contains(redraws[i].el)) redraws.splice(i, 1);
      else redraws[i].draw();
    }
  }, 120);
});

function legend(items) {
  return h('div', { class: 'legend' }, items.map(([name, col]) =>
    h('span', {}, h('i', { style: `background:var(--${col})` }), name)));
}
function dataTable(head, rows, numFrom = 1, cls = '') {
  return h('div', { class: 'tscroll' }, h('table', { class: cls },
    h('thead', {}, h('tr', {}, head.map((c, i) => h('th', { class: i >= numFrom ? 'n' : null }, c)))),
    h('tbody', {}, rows.map((r) => h('tr', {}, r.map((c, i) => h('td', { class: i >= numFrom ? 'n' : null }, c)))))));
}
function seg(options, current, onPick, cls = '') {
  return h('div', { class: 'seg ' + cls, role: 'group' }, options.map(([val, label]) =>
    h('button', { type: 'button', 'aria-pressed': String(val === current), onclick: () => onPick(val) }, label)));
}

// ------------------------------------------------------------ exhibits, boxes, parts
// Every chart and table is a numbered exhibit with its notes and source beneath,
// so a reader can cite "Exhibit 4" and carry the caveat with it. Numbering is per page.
let EX = { n: 0, b: 0, items: [] };
// Reader-facing date for this version, e.g. "14 October 2026". No times, no internal file names.
const versionDate = () => {
  const [y, m, d] = D.generated.slice(0, 10).split('-').map(Number);
  return `${d} ${['January','February','March','April','May','June','July','August','September','October','November','December'][m - 1]} ${y}`;
};
function exhibit({ title, sub, controls, legendItems, plot, body, table, notes, cls }) {
  EX.n += 1;
  const id = `panel-${EX.n}`;
  const b = h('div', { class: 'body' });
  if (legendItems) b.append(legend(legendItems));
  if (plot) { const p = h('div', { class: 'plot' }); b.append(p); requestAnimationFrame(() => plot(p)); }
  if (body) b.append(body);
  const noteList = (Array.isArray(notes) ? notes : [notes]).filter(Boolean);
  return h('section', { class: 'panel ' + (cls || ''), id, 'aria-labelledby': id + '-t' },
    h('div', { class: 'eh' }, h('h3', { class: 'et', id: id + '-t' }, title.replace(/, (Scenario \d+|[RB]\d)$/, '')), controls || null),
    sub ? h('p', { class: 'es', html: sub }) : null,
    b,
    noteList.length ? h('p', { class: 'notes', html: noteList.join(' ') }) : null,
    table ? h('details', { class: 'tbl' }, h('summary', {}, 'Show the numbers'), table) : null);
}
function box(title, ...kids) {
  return h('section', { class: 'box' }, h('h3', { class: 'bt' }, title), ...kids);
}
function part(title, idHint) {
  const id = 'part-' + (idHint || title.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40));
  return h('h2', { class: 'part', id }, title);
}
function facts(rows) {
  return h('dl', { class: 'facts' }, rows.map(([k, v]) => h('div', {}, h('dt', {}, k), h('dd', {}, v))));
}

// ------------------------------------------------------------ the bundle's views
function decileRanges() {
  const cuts = D.decile_cuts;
  return cuts.map((c, i) => i === 0 ? `household income up to ${fmt.usd(c)}`
    : i === cuts.length - 1 ? `household income above ${fmt.usd(cuts[i - 1])}`
      : `household income ${fmt.usd(cuts[i - 1])} to ${fmt.usd(c)}`);
}
const DEC_METRICS = {
  share: { label: 'Share of relief', axis: (v) => fmt.pct(v, 0), val: (v) => fmt.pct(v) },
  perhh: { label: 'Per household', axis: (v) => fmt.usd(v), val: (v) => fmt.usd(v) },
  pct: { label: 'Share of income', axis: (v) => fmt.pct(v, 2), val: (v) => fmt.pct(v, 2) },
};
function decileValues(sid, metric, a = 'ALL') {
  const rows = D.decile_cells.filter((r) => r.s === sid && r.a === a).sort((x, y) => x.d - y.d);
  const tot = sum(rows.map((r) => r.delivered));
  return rows.map((r) => metric === 'share' ? r.delivered / tot
    : metric === 'perhh' ? (r.households ? r.delivered / r.households : null)
      : (r.gain_pct_income ?? null));
}
const hasDecileFields = () => D.decile_cells.length && 'households' in D.decile_cells[0];
const hasGeoPct = () => D.puma_cells.length && 'gain_pct_income' in D.puma_cells[0];
const extent = (arrs) => { const v = arrs.flat().filter((x) => x != null && isFinite(x)); return [Math.min(0, ...v), Math.max(0, ...v)]; };

function decileExhibit(s) {
  const ok = hasDecileFields();
  if (!ok) state.decMetric = 'share';
  const metric = state.decMetric, M = DEC_METRICS[metric];
  const vals = decileValues(s.id, metric);
  const dom = extent(scenGroup(s.group).map((x) => decileValues(x.id, metric)));
  const ranges = decileRanges();
  const opts = Object.entries(DEC_METRICS).filter(([k]) => ok || k === 'share').map(([k, v]) => [k, v.label]);
  const subs = {
    share: 'Each income decile’s part of the relief this scenario delivers. A bar below zero is a decile that pays more than it receives.',
    perhh: 'Average net gain per household in each decile, at today’s claiming rates. Below zero means worse off on average.',
    pct: 'Each decile’s total net gain as a share of its total income.',
  };
  return exhibit({
    title: `Relief by income decile, Scenario ${s.id}`,
    sub: subs[metric],
    controls: seg(opts, metric, (v) => { state.decMetric = v; rerender(); }, 'small'),
    plot: (el) => vbars(el, {
      cats: vals.map((_, i) => ({ label: String(i + 1), tip: `Decile ${i + 1}: ${ranges[i]}` })),
      series: [{ name: M.label, values: vals }], signColor: true, fmt: M.val, fmtTick: M.axis, domain: dom,
      xTitle: 'Income decile', aria: `${M.label} by income decile`,
    }),
    table: dataTable(['Decile', 'Household income', M.label], vals.map((v, i) => [String(i + 1), ranges[i].replace('household income ', ''), v == null ? 'n/a' : M.val(v)]), 2),
    notes: ['Deciles rank every Maine household by income; each holds one-tenth of all households. Lowest-income decile (1) to highest-income decile (10).',
      metric === 'pct' ? 'Households with zero or negative income are left out of this measure.' : ''],
  });
}

const GEO_METRICS = {
  share: { label: 'Share of relief', f: 'share_of_delivered', axis: (v) => fmt.pct(v, 0), val: (v) => fmt.pct(v) },
  perhh: { label: 'Per household', f: 'per_hh', axis: (v) => fmt.usd(v), val: (v) => fmt.usd(v) },
  pct: { label: 'Share of income', f: 'gain_pct_income', axis: (v) => fmt.pct(v, 2), val: (v) => fmt.pct(v, 2) },
};
function geoExhibit(s) {
  const ok = hasGeoPct();
  if (!ok && state.geoMetric === 'pct') state.geoMetric = 'share';
  const metric = state.geoMetric, M = GEO_METRICS[metric];
  const rowsFor = (sid) => D.puma_cells.filter((r) => r.s === sid).sort((a, b) => a.rank - b.rank);
  const rows = rowsFor(s.id);
  const dom = extent(scenGroup(s.group).map((x) => rowsFor(x.id).map((r) => r[M.f])));
  const opts = Object.entries(GEO_METRICS).filter(([k]) => ok || k !== 'pct').map(([k, v]) => [k, v.label]);
  return exhibit({
    title: `Relief by survey area, Scenario ${s.id}`,
    sub: metric === 'share' ? 'Each area’s share of the change in property tax relief. A negative share means the area loses on net while the state as a whole gains.'
      : metric === 'perhh' ? 'Average net gain per household in each area, at today’s claiming rates.'
        : 'Each area’s total net gain as a share of its total income.',
    controls: seg(opts, metric, (v) => { state.geoMetric = v; rerender(); }, 'small'),
    plot: (el) => hbars(el, { cats: rows.map((r) => ({ label: r.label })), values: rows.map((r) => r[M.f]), fmt: M.val, fmtTick: M.axis, domain: dom, aria: `${M.label} by survey area` }),
    table: dataTable(['Area', 'Households', M.label, 'Better off', 'Worse off'],
      rows.map((r) => [r.label, fmt.int(r.households), M.val(r[M.f]), fmt.pct(r.better, 0), fmt.pct(r.worse, 0)])),
    notes: [`The ten areas are the Census Bureau’s survey areas for Maine, the finest geography the household data supports. Areas are roughly sorted from most rural to most urban. Each figure describes an area as a whole, not any town inside it (see <a href="#/about">About the model</a>).`],
  });
}

function binShort(i) {
  const e = D.bin_edges; const lo = e[i], hi = e[i + 1];
  const k = (v) => (v < 0 ? MINUS : '+') + '$' + (Math.abs(v) >= 1000 ? Math.abs(v) / 1000 + 'k' : Math.abs(v));
  if (lo == null) return `${k(hi)}\nor more`;
  if (hi == null) return `${k(lo)}\nor more`;
  if (lo < 0 && hi > 0) return 'No\nchange';
  return `${k(lo)} to\n${k(hi)}`;
}
function binCompact(i) {
  const e = D.bin_edges; const lo = e[i], hi = e[i + 1];
  const k = (v) => (v < 0 ? MINUS : '+') + (Math.abs(v) >= 1000 ? Math.abs(v) / 1000 + 'k' : Math.abs(v));
  if (lo == null) return '<' + k(hi);
  if (hi == null) return '>' + k(lo);
  if (lo < 0 && hi > 0) return '0';
  return hi < 0 ? k(lo) : k(hi);
}
function dollarsExhibit(s, a, title) {
  const code = a ? a.bcode : 'ALL';
  const row = D.delivered_bins.find((r) => r.s === s.id && r.a === code);
  const dom = extent(scenGroup(s.group).map((x) => D.delivered_bins.find((r) => r.s === x.id && r.a === code).bins));
  const mid = (row.bins.length - 1) / 2;
  const colors = row.bins.map((_, i) => i < mid ? 'loss' : i > mid ? 'gain' : 'zero');
  const lose = sum(row.bins.slice(0, mid)), gain = sum(row.bins.slice(mid + 1)), none = row.bins[mid];
  return exhibit({
    title: title || 'Number of households made better or worse off by the scenario.',
    sub: `${fmt.int(gain)} households gain, ${fmt.int(none)} see no change and ${fmt.int(lose)} lose.`,
    legendItems: [['Worse off', 'loss'], ['No change', 'zero'], ['Better off', 'gain']],
    plot: (el) => vbars(el, {
      cats: row.bins.map((_, i) => ({ label: binShort(i), tip: esc(D.bin_labels[i][0].toUpperCase() + D.bin_labels[i].slice(1)) })),
      series: [{ name: 'Households', values: row.bins }], colors, compact: row.bins.map((_, i) => binCompact(i)), domain: dom,
      fmt: (v) => fmt.int(v) + ' households', fmtTick: fmt.k, yTitle: 'Households', height: 260, labels: fmt.kc, aria: 'Households by annual change in property tax net of relief',
    }),
    table: dataTable(['Change per year', 'Households'], row.bins.map((b, i) => [D.bin_labels[i], fmt.int(b)])),
    notes: ['A change of a dollar or less in either direction counts as no change.'],
  });
}
function thresholdExhibit(s) {
  const rowsFor = (sid) => D.burden_threshold.filter((r) => r.s === sid).sort((a, b) => a.d - b.d);
  const rows = rowsFor(s.id);
  const dom = extent(scenGroup(s.group).map((x) => rowsFor(x.id).flatMap((r) => [r.now, r.scen])));
  const now = sum(rows.map((r) => r.now)), aft = sum(rows.map((r) => r.scen));
  const t = fmt.pct(D.burden_threshold_pct, 0), ranges = decileRanges();
  return exhibit({
    title: 'How many households are burdened by property taxes, by decile',
    sub: `How many households in each decile pay more than ${t} of their income in property tax (net of relief received).<br>Statewide, ${fmt.int(now)} households are above ${t} today and ${fmt.int(aft)} after this change.`,
    legendItems: [['Today', 's-now'], ['After this scenario', 's-scen']],
    plot: (el) => vbars(el, {
      cats: rows.map((r) => ({ label: String(r.d), tip: `Decile ${r.d}: ${ranges[r.d - 1]}` })),
      series: [{ name: 'Today', color: 's-now', values: rows.map((r) => r.now) }, { name: 'After this scenario', color: 's-scen', values: rows.map((r) => r.scen) }],
      fmt: (v) => fmt.int(v) + ' households', fmtTick: fmt.k, yTitle: 'Households', domain: dom,
      xTitle: 'Income decile', aria: `Households above ${t} of income by decile`,
    }),
    table: dataTable(['Decile', 'Today', 'After this scenario', 'Change'],
      rows.map((r) => [String(r.d), fmt.int(r.now), fmt.int(r.scen), (r.scen > r.now ? '+' : r.scen < r.now ? MINUS : '') + fmt.int(Math.abs(r.scen - r.now))])),
    notes: ['Property tax burden is measured as the tax bill (or 15% of rent), net of relief received.'],
  });
}
// The archetypes whose after-relief burden piles up at exactly 4%, where the
// Fairness Credit formula puts every claimant it does not cap (Steve, 10-19).
const SPIKE_4 = ['R2', 'R4', 'R5', 'R6'];
const burdenNotes = (a) => ['Property tax burden is measured as the tax bill (or 15% of rent), net of relief received. Bands include their upper edge, so a household at exactly 4% counts as 2% to 4%.',
  SPIKE_4.includes(a.code) ? 'The after-relief spike at 2% to 4% is not a coincidence; it is because the Fairness Credit is specifically designed to reduce the tax burden to exactly 4% of income.' : ''];
// On the Archetypes page: before any relief against today. On the comparison
// page: today against the scenario (Steve, 10-19: the before-relief bar goes).
function burdenExhibit(a, s) {
  const rows = D.burden_rows.filter((r) => r.a === a.bcode);
  const before = rows.find((r) => r.series === 'before_relief').bins;
  const now = rows.find((r) => r.series === 'now').bins;
  const t = fmt.pct(D.burden_threshold_pct, 0);
  let series, dom = null;
  if (s) {
    const c = D.burden_cells.find((r) => r.s === s.id && r.a === a.bcode);
    series = [{ name: 'Today', color: 's-now', values: now }, { name: `Under Scenario ${s.id}`, color: 's-scen', values: c.bins }];
    dom = extent([now, ...scenGroup(s.group).map((x) => D.burden_cells.find((r) => r.s === x.id && r.a === a.bcode).bins)]);
  } else {
    series = [{ name: 'Before any relief', color: 's-before', values: before }, { name: 'After today’s relief', color: 's-now', values: now }];
  }
  const labels = D.burden_bin_labels;
  const short = labels.map((l) => l.replace('under ', 'Under\n').replace('above ', 'Above\n').replace(' to ', ' to\n'));
  const atOrBelow6 = (b) => 1 - share6(b);
  const lead = `Number of households with property taxes at different shares of their income, ${s ? `today and under Scenario ${s.id}` : 'before and after existing relief programs'}.`;
  const sub = a.set === 'rep'
    ? (s ? `${lead} ${fmt.pct(atOrBelow6(now), 0)} of this archetype is at or below ${t} today and ${fmt.pct(atOrBelow6(series[1].values), 0)} under Scenario ${s.id}.`
      : `${lead} ${fmt.pct(atOrBelow6(before), 0)} of this archetype is at or below ${t} before any relief and ${fmt.pct(atOrBelow6(now), 0)} after today’s programs.`)
    : `${lead} Because this is a Burdened Archetype, there are no households with burdens below ${t}${s ? ' today' : ''}.`;
  return exhibit({
    title: s ? `Property tax burden today and under Scenario ${s.id}` : 'Property tax burden before and after today’s relief',
    sub, legendItems: series.map((x) => [x.name, x.color]),
    plot: (el) => vbars(el, {
      cats: short.map((l, i) => ({ label: l, tip: esc(labels[i][0].toUpperCase() + labels[i].slice(1)) + ' of income' })),
      series, fmt: (v) => fmt.int(v) + ' households', fmtTick: fmt.k, yTitle: 'Households', height: 280, domain: dom, labels: fmt.k1, aria: 'Households by property tax burden band',
    }),
    table: dataTable(['Burden band', ...series.map((x) => x.name)], labels.map((l, i) => [l, ...series.map((x) => fmt.int(x.values[i]))])),
    notes: burdenNotes(a),
  });
}

// ------------------------------------------------------------ copy rendering
function renderBlocks(blocks, hooks = {}) {
  const frag = document.createDocumentFragment();
  for (const b of blocks) {
    if (hooks.skip && hooks.skip(b)) continue;
    let el = null;
    if (b.type === 'chart') el = hooks.chart ? hooks.chart(b) : null;
    else if (b.type === 'p') {
      const t = stripTags(b.html).trim();
      if (/^Non-quantified effects$/i.test(t)) el = null; // the exhibit carries this title
      else el = h('p', { html: b.html });
    } else if (b.type === 'vignette') el = hooks.vignette ? hooks.vignette(b) : h('p', {}, h('em', { html: b.html }));
    else if (b.type === 'label') el = h('h4', {}, b.text);
    else if (b.type === 'list') {
      const min = Math.min(...b.items.map((i) => i.depth));
      el = h(b.items.every((i) => i.ordered) ? 'ol' : 'ul', {}, b.items.map((i) => h('li', { class: 'd' + (i.depth - min + 1), html: i.html })));
    } else if (b.type === 'table') el = hooks.table ? hooks.table(b) : copyTable(b);
    if (el) frag.append(el);
  }
  return frag;
}
function tableKind(b) {
  const head = b.head.join('|').toLowerCase();
  return head.startsWith('parameter') ? 'params' : head.startsWith('affected group') ? 'nqe' : '';
}
function copyTable(b, cls) {
  return h('div', { class: 'tscroll' }, h('table', { class: cls || tableKind(b) },
    h('thead', {}, h('tr', {}, b.head.map((c) => h('th', {}, c)))),
    h('tbody', {}, b.rows.map((r) => h('tr', {}, r.map((c) => h('td', { html: c })))))));
}
function chartKind(t) {
  t = t.toLowerCase();
  // Order matters: placeholder texts describe their charts in words that overlap.
  if (t.includes('burden before and after')) return 'burden';
  if (t.includes('above 6%')) return 'threshold';
  if (t.includes('by decile')) return 'decile';
  if (t.includes('geograph')) return 'geo';
  if (t.includes('dollars delivered')) return 'dollars';
  if (t.includes('which scenarios help')) return 'rank';
  if (t.startsWith('toggle')) return 'toggle';
  if (t.includes('summary table')) return 'summary';
  return null;
}
function prose(blocks, hooks) {
  // First paragraph reads as the lede.
  const f = renderBlocks(blocks, hooks);
  const p = f.querySelector('p');
  if (p) p.classList.add('lede');
  return f;
}

// ------------------------------------------------------------ state + routing
const state = {
  page: 'scenarios', sgroup: 'cost35', s: '1', aset: 'rep', a: 'R1',
  csg: 'cost35', cs: '1', cas: 'rep', ca: 'R1', decMetric: 'share', geoMetric: 'share', multMetric: 'share', atg: 'cost35',
};
function readHash() {
  const [path, qs] = location.hash.replace(/^#\/?/, '').split('?');
  state.page = ['scenarios', 'archetypes', 'comparison', 'about'].includes(path) ? path : 'scenarios';
  const q = new URLSearchParams(qs || '');
  state.go = q.get('go');
  if (state.page === 'scenarios') {
    if (q.get('s') && scen(q.get('s'))) { state.s = q.get('s'); state.sgroup = scen(state.s).group; }
    if (q.get('g') && D.groups[q.get('g')]) state.sgroup = q.get('g');
  } else if (state.page === 'archetypes') {
    if (q.get('a') && arch(q.get('a'))) { state.a = q.get('a'); state.aset = arch(state.a).set; }
  } else if (state.page === 'comparison') {
    if (q.get('s') && scen(q.get('s'))) { state.cs = q.get('s'); state.csg = scen(state.cs).group; }
    if (q.get('a') && arch(q.get('a'))) { state.ca = q.get('a'); state.cas = arch(state.ca).set; }
  }
}
function hashFor() {
  if (state.page === 'scenarios') return `#/scenarios?g=${state.sgroup}&s=${state.s}`;
  if (state.page === 'archetypes') return `#/archetypes?a=${state.a}`;
  if (state.page === 'comparison') return `#/comparison?s=${state.cs}&a=${state.ca}`;
  return '#/about';
}
function rerender() {
  const y = window.scrollY;
  history.replaceState(null, '', hashFor());
  render();
  window.scrollTo(0, y);
}
function goTo(id) {
  requestAnimationFrame(() => { const el = document.getElementById(id); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); });
}
window.addEventListener('hashchange', () => {
  if (!D) return;
  const p = state.page; readHash(); render();
  if (state.go) { goTo('part-' + state.go); state.go = null; history.replaceState(null, '', hashFor()); } else if (p !== state.page) window.scrollTo(0, 0);
});
// In-page links in the copy ("compare the two sets of scenarios") are written #jump:<part>.
document.addEventListener('click', (e) => {
  const a = e.target.closest && e.target.closest('a[href^="#jump:"]');
  if (!a) return;
  e.preventDefault();
  goTo('part-' + a.getAttribute('href').slice(6));
});

function render() {
  document.querySelectorAll('.tabs a').forEach((a) => { if (a.dataset.page === state.page) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  EX = { n: 0 };
  const page = h('div', {});
  ({ scenarios: pageScenarios, archetypes: pageArchetypes, comparison: pageComparison, about: pageAbout })[state.page](page);
  main.replaceChildren(page);
  const titles = PAGE_TITLES;
  document.title = `${titles[state.page]} · Maine Property Tax Relief Explorer`;
}

// ------------------------------------------------------------ Scenarios page
const PAGE_TITLES = { scenarios: 'Policy Scenarios', archetypes: 'Household Archetypes', comparison: 'Pick a Scenario & Archetype', about: 'About the Model' };
function scenarioRowCopy(id) {
  const intro = sec('Scenarios', 'Scenarios - Page Introduction');
  for (const b of intro.blocks.filter((x) => x.type === 'table')) {
    const r = b.rows.find((row) => stripTags(row[0]).trim().startsWith(id + '.'));
    if (r) return { programme: r[1], changes: r[2] };
  }
  // S15-S19 are not in Report-Ready Copy; their rows ride with their own copy (add_greg_copy_oct30.py).
  if (CX.scen[id] && CX.scen[id].row) return CX.scen[id].row;
  return { programme: '', changes: '' };
}
function summaryTable(group, onPick) {
  const hh = D.counts.households;
  const th = (txt, attrs = {}) => h('th', attrs, txt);
  return h('div', { class: 'tscroll' }, h('table', { class: 'stack scen-sum' },
    h('thead', {},
      h('tr', {}, th('Scenario', { rowspan: 2 }), th('Program', { rowspan: 2 }), th('What changes', { rowspan: 2 }),
        th('State cost', { rowspan: 2, class: 'n' }), th('Delivered relief', { rowspan: 2, class: 'n' }), th('Number of Households', { colspan: 3, class: 'span' })),
      h('tr', {}, th('Gaining', { class: 'n' }), th('No change', { class: 'n' }), th('Losing', { class: 'n' }))),
    h('tbody', {}, scenGroup(group).map((s) => {
      const c = scenarioRowCopy(s.id);
      return h('tr', { class: 'click' + (s.id === state.s ? ' sel' : ''), onclick: () => onPick(s.id) },
        h('td', { class: 'lead' }, h('a', { href: `#/scenarios?g=${s.group}&s=${s.id}`, onclick: (e) => { e.preventDefault(); e.stopPropagation(); onPick(s.id); } }, scenTitle(s))),
        h('td', { html: c.programme, 'data-label': 'Program' }), h('td', { html: c.changes, 'data-label': 'What changes' }),
        h('td', { class: 'n', 'data-label': 'State cost' }, fmt.m(s.state_cost)),
        h('td', { class: 'n', 'data-label': 'Delivered relief' }, fmt.m(s.delivered)),
        h('td', { class: 'n', 'data-label': 'Households gaining' }, fmt.int(s.gaining)),
        h('td', { class: 'n', 'data-label': 'Households with no change' }, fmt.int(hh - s.gaining - s.losing)),
        h('td', { class: 'n', 'data-label': 'Households losing' }, fmt.int(s.losing)));
    }))));
}
function multiples(group, onPick, metric) {
  const rows = scenGroup(group);
  const M = DEC_METRICS[metric];
  const series = rows.map((s) => decileValues(s.id, metric));
  const dom = extent(series);
  const wrap = h('div', { class: 'multiples' + (rows.length === 6 ? ' g3' : '') });
  rows.forEach((s, k) => {
    const plotEl = h('div', {});
    wrap.append(h('div', { class: 'm-cell' + (s.id === state.s ? ' sel' : '') },
      h('a', { href: `#/scenarios?g=${group}&s=${s.id}`, onclick: (e) => { e.preventDefault(); onPick(s.id); } }, h('div', { class: 't' }, scenTitle(s))), plotEl));
    requestAnimationFrame(() => vbars(plotEl, {
      cats: series[k].map((_, i) => ({ label: String(i + 1), tip: `Decile ${i + 1}` })),
      series: [{ name: M.label, values: series[k] }], signColor: true,
      fmt: M.val, fmtTick: M.axis, height: 150, domain: dom, aria: `${scenTitle(s)}: ${M.label.toLowerCase()} by decile`,
    }));
  });
  return wrap;
}
function scenarioFacts(s) {
  const hh = D.counts.households;
  const rows = [['State cost', fmt.m(s.state_cost)]];
  if (s.group === 'realloc') rows.push(['Money redirected', fmt.m(s.pool)]);
  // Task Force scenarios: the total the cuts raise, from each scenario's introduction. The bundle's
  // pool for these five is only the Fairness Credit's share (Steve, 29 Oct: add Money redirected).
  else if (CX.scen[s.id] && CX.scen[s.id].redirected) rows.push(['Money redirected', fmt.m(CX.scen[s.id].redirected)]);
  rows.push(['Delivered relief', fmt.m(s.delivered)], ['Better off', fmt.int(s.gaining)], ['No change', fmt.int(hh - s.gaining - s.losing)], ['Worse off', fmt.int(s.losing)]);
  return facts(rows);
}
const listOf = (bs) => bs.map((b) => { const min = Math.min(...b.items.map((i) => i.depth)); return h('ul', {}, b.items.map((i) => h('li', { class: 'd' + (i.depth - min + 1), html: i.html }))); });
// A page introduction from the 10-19 notes, with its "Learn more" accordion.
function pageIntro(key) {
  const f = document.createDocumentFragment();
  f.append(prose(CX.pages[key]));
  const more = CX.pages[key + ':more'];
  if (more) f.append(h('details', { class: 'more' }, h('summary', {}, more.title), h('div', { class: 'more-body' }, renderBlocks(more.blocks))));
  return f;
}
const DEC_DEF = 'Deciles rank every Maine household by income; each holds one-tenth of all households. Lowest-income decile (1) to the left of each panel, highest-income decile (10) to the right.';
function pageScenarios(page) {
  page.append(h('h2', { class: 'page' }, PAGE_TITLES.scenarios), pageIntro('Scenarios'));

  const pick = (id) => { state.s = id; state.sgroup = scen(id).group; rerender(); goTo('part-explore'); };
  const g = state.sgroup, n = scenGroup(g).length;
  page.append(part('Compare the scenarios', 'overview'));
  page.append(h('div', { class: 'selector' }, h('div', { class: 'control' }, h('span', {}, 'Scenario group'),
    seg(Object.entries(D.groups), g, (v) => { state.sgroup = v; if (scen(state.s).group !== v) state.s = scenGroup(v)[0].id; rerender(); }))));
  const s14 = scen('14');
  const notes = ['“No change” means a change of a dollar or less in either direction.',
    '<br><strong>State cost</strong> is money leaving the State budget. <strong>Delivered relief</strong> is the change in what Maine households pay in property taxes (net of the relief they receive). Where a scenario causes mill rates to rise, some of the tax burden is shifted onto non-homestead properties, meaning that households gain more than the scenario costs to the State.',
    g === 'realloc' && s14.state_cost < 0 ? `<br>Scenario 14 spends ${fmt.m(-s14.state_cost)} less than the money it frees up, so it returns that to the State rather than costing anything. Every other reallocation scenario is built to spend its pool exactly.` : ''];
  page.append(exhibit({ title: `${D.groups[g]}: ${n} scenarios`, sub: 'Select a scenario to explore it below.', body: summaryTable(g, pick), notes }));
  if (!hasDecileFields()) state.multMetric = 'share';
  const mm = state.multMetric;
  page.append(exhibit({
    title: 'Each scenario’s relief by income decile',
    sub: { share: 'Each decile’s share of the change in property tax relief.', perhh: 'Average change in income per household, by decile.', pct: 'Each decile’s total net change in income, expressed as a share of income.' }[mm] + '<br>' + DEC_DEF,
    controls: seg(Object.entries(DEC_METRICS).filter(([k]) => hasDecileFields() || k === 'share').map(([k, v]) => [k, v.label]), mm, (v) => { state.multMetric = v; rerender(); }, 'small'),
    body: multiples(g, pick, mm), notes: ['A bar below zero means that taxpayers in that decile pay more due to mill rate increases than they receive in new relief.'],
  }));

  const s = scen(state.s), full = CX.scen[s.id].full;
  page.append(part('Explore a specific policy scenario', 'explore'));
  page.append(h('div', { class: 'stickybar' },
    h('label', { class: 'control' }, h('span', {}, 'Scenario'),
      h('select', { onchange: (e) => { state.s = e.target.value; state.sgroup = scen(e.target.value).group; rerender(); } },
        Object.entries(D.groups).map(([gk, gl]) => h('optgroup', { label: gl }, scenGroup(gk).map((x) => h('option', { value: x.id, selected: x.id === s.id }, scenTitle(x))))))),
    scenarioFacts(s)));
  const side = h('aside', { class: 'ws-side panel' },
    h('h3', { class: 'et' }, scenTitle(s)),
    renderBlocks(full, { table: (b) => copyTable(b, 'params') }),
    s.group === 'realloc' ? h('details', { class: 'more' }, h('summary', {}, 'How the six reallocation scenarios work'), renderBlocks(sec('Scenarios', 'The six scenarios that spend nothing new').blocks)) : null);
  const charts = h('div', { class: 'chart-grid' }, [decileExhibit(s), geoExhibit(s), dollarsExhibit(s), thresholdExhibit(s)]);
  page.append(h('div', { class: 'ws-grid' }, side, h('div', { class: 'ws-main' }, charts)));
  // Non-quantified effects and Key findings stay hidden until their copy is ready (Explorer-Ready Copy, 10-19).
}

// ------------------------------------------------------------ Archetypes page
function firstSentence(html) {
  const t = stripTags(html).trim();
  const m = t.match(/^(.+?\.)(\s|$)/);
  return m ? m[1] : t;
}
const share6 = (bins) => sum(bins.slice(3)) / sum(bins);
// Share of an archetype above 6% of income, before any relief and after today's.
function sharesBurdened(a) {
  const rows = D.burden_rows.filter((r) => r.a === a.bcode);
  return { before: share6(rows.find((r) => r.series === 'before_relief').bins), now: share6(rows.find((r) => r.series === 'now').bins) };
}
const shareArrow = (x, y) => `${fmt.pct(x, 0)} → ${fmt.pct(y, 0)}`;
const isRenter = (a) => a.p.base_is === 'renters';
// For renters the bundle's median "property tax" is 15% of rent, so median rent is that over 15%.
const medRentMonthly = (a) => a.p.med_tax / 0.15 / 12;
function archSummaryTable(set, onPick) {
  const rep = set === 'rep';
  const head = ['Archetype', 'Who is included', 'Households surveyed', rep ? 'Share of owners or renters' : 'Share of the burdened group',
    'Median age', 'Median income', 'Median property tax', 'Median burden, before → after relief', 'Share burdened, before → after relief'];
  if (rep) head.push('Relief delivered');
  return h('div', { class: 'tscroll' }, h('table', { class: 'arch stack' },
    h('thead', {}, h('tr', {}, head.map((c, i) => h('th', { class: i >= 2 ? 'n' : null }, c)))),
    h('tbody', {}, archSet(set).map((a) => {
      const intro = CX.arch[a.code].intro.find((b) => b.type === 'p');
      const p = a.p, sb = sharesBurdened(a);
      const cells = [
        h('td', { class: 'lead' }, h('a', { href: `#/archetypes?a=${a.code}`, onclick: (e) => { e.preventDefault(); e.stopPropagation(); onPick(a.code); } }, `${a.code}. ${a.name}`),
          h('span', { class: 'sub' }, `${fmt.int(p.households)} households`)),
        h('td', { 'data-label': head[1] }, intro ? firstSentence(intro.html) : ''),
        h('td', { class: 'n', 'data-label': head[2] }, fmt.int(p.n)),
        h('td', { class: 'n', 'data-label': head[3] }, rep ? `${fmt.pct(p.share_of_base, 0)} of ${p.base_is}` : fmt.pct(a.shareOfSet, 0)),
        h('td', { class: 'n', 'data-label': head[4] }, String(Math.round(p.med_age))),
        h('td', { class: 'n', 'data-label': head[5] }, fmt.usd100(p.med_income)),
        h('td', { class: 'n', 'data-label': head[6] }, fmt.usd10(p.med_tax)),
        h('td', { class: 'n', 'data-label': head[7] }, `${fmt.pct(p.burden_pre)} → ${fmt.pct(p.burden_post)}`),
        h('td', { class: 'n', 'data-label': head[8] }, shareArrow(sb.before, sb.now)),
      ];
      if (rep) cells.push(h('td', { class: 'n', 'data-label': head[9] }, fmt.m(p.delivered)));
      return h('tr', { class: 'click' + (a.code === state.a ? ' sel' : ''), onclick: () => onPick(a.code) }, cells);
    }))));
}
const AREA_NAME = { Rural: 'Rural Maine', Service: 'Service-center regions', South: 'Southern coast', Portland: 'Greater Portland' };
function areaTableEl(a) {
  const order = ['Rural', 'Service', 'South', 'Portland'];
  const get = (code, area) => (D.archetype_areas.find((r) => r.a === code && r.area === area) || {}).share;
  return dataTable(['Region', a.code, 'All Maine'], order.map((r) => [AREA_NAME[r] || r, fmt.pct(get(a.bcode, r), 0), fmt.pct(get('ALL', r), 0)]));
}
function vignetteBox(a) {
  const c = CX.arch[a.code];
  return box(CX.vtitles[a.code] || 'Vignette',
    c.vignette.map((b) => h('p', { class: 'story', html: b.html })),
    h('p', { class: 'fine' }, 'This vignette describes the circumstances of a very typical household from within this archetype. While their names and occupations are made up, their finances are real: they represent survey data from a real household within the model.'));
}
// One row per scenario in the chosen group: share burdened, average relief per
// household, share better off. Best value in each column bolded.
function archScenarioTable(a) {
  const g = state.atg, rep = a.set === 'rep';
  const now = sharesBurdened(a).now;
  const rows = scenGroup(g).map((s) => {
    const burd = share6(D.burden_cells.find((r) => r.s === s.id && r.a === a.bcode).bins);
    let relief, better;
    if (rep) { const r = D.broad_cells.find((x) => x.s === s.id && x.a === a.bcode); relief = r.per_hh; better = r.gaining / r.households; }
    else { const r = D.narrow_cells.find((x) => x.s === s.id && x.a === a.bcode); relief = r.mean_gain_delivered; better = r.share_better; }
    return { s, burd, relief, better };
  });
  const fB = (x) => fmt.pct(x, 0), fR = (x) => fmt.usdS10(x) + ' a year', fV = (x) => fmt.pct(x, 0);
  const bestB = fB(Math.min(...rows.map((r) => r.burd))), bestR = fR(Math.max(...rows.map((r) => r.relief))), bestV = fV(Math.max(...rows.map((r) => r.better)));
  const cell = (txt, bold, label) => h('td', { class: 'n' + (bold ? ' best' : ''), 'data-label': label }, txt);
  const lb = `Share burdened (today ${fmt.pct(now, 0)})`, lr = 'Average relief per household', lv = 'Share better off';
  return h('section', { class: 'panel' },
    h('div', { class: 'tscroll' }, h('table', { class: 'stack' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Scenario'), h('th', { class: 'n' }, 'Share burdened', h('span', { class: 'sub' }, `Today: ${fmt.pct(now, 0)}`)), h('th', { class: 'n' }, lr), h('th', { class: 'n' }, lv))),
      h('tbody', {}, rows.map((r) => h('tr', {},
        h('td', { class: 'lead' }, h('a', { href: `#/comparison?s=${r.s.id}&a=${a.code}` }, scenTitle(r.s))),
        cell(fB(r.burd), fB(r.burd) === bestB, lb),
        cell(fR(r.relief), fR(r.relief) === bestR, lr),
        cell(fV(r.better), fV(r.better) === bestV, lv)))))),
    h('p', { class: 'notes', html: '<strong>Share burdened</strong> is the proportion of households for whom property tax exceeds 6% of income. <strong>Share better off</strong> is the proportion of households in this archetype who are made better off by the policy scenario. Compare scenarios within a group only: the reallocation scenarios move several times more money.' }));
}
function comSummaryTable(onPick) {
  // Columns per Steve (29 Oct). The mill rate is the town's nominal rate as the parcel was billed:
  // billed over assessed, both from the commitment book. No bill is derived from a rate.
  const head = ['Archetype', 'Town', 'Property value', 'Mill rate', 'Property tax billed today'];
  return h('div', { class: 'tscroll' }, h('table', { class: 'arch stack' },
    h('thead', {}, h('tr', {}, head.map((c, i) => h('th', { class: i >= 2 ? 'n' : null }, c)))),
    h('tbody', {}, archSet('com').map((a) => h('tr', { class: 'click' + (a.code === state.a ? ' sel' : ''), onclick: () => onPick(a.code) },
      h('td', { class: 'lead' }, h('a', { href: `#/archetypes?a=${a.code}`, onclick: (e) => { e.preventDefault(); e.stopPropagation(); onPick(a.code); } }, `${a.code}. ${a.name}`)),
      h('td', { 'data-label': head[1] }, a.c.town),
      h('td', { class: 'n', 'data-label': head[2] }, fmt.usd(a.c.assessed)),
      h('td', { class: 'n', 'data-label': head[3] }, fmt.mills(a.c.billed / a.c.assessed)),
      h('td', { class: 'n', 'data-label': head[4] }, fmt.usd(a.c.billed)))))));
}
function comFacts(a) {
  const c = a.c, rows = [['Town', c.town], ['Property tax billed today', fmt.usd(c.billed)]];
  if (c.units > 1) rows.push(['Dwelling units', String(c.units)], ['Billed per unit', fmt.usd(c.billed_per_unit)]);
  return facts(rows);
}
function comVignetteBox(a) {
  return box('Vignette', CX.com[a.code].vignette.map((b) => h('p', { class: 'story', html: b.html })));
}
// One row per scenario in the chosen group: the town's mill rate change and the bill it produces.
function comScenarioTable(a) {
  const per = a.c.units > 1;
  const head = ['Scenario', 'Mill rate change', 'Property tax bill', 'Change in the bill'];
  if (per) head.push('Change per unit');
  return h('section', { class: 'panel' },
    h('div', { class: 'tscroll' }, h('table', { class: 'stack' },
      h('thead', {}, h('tr', {}, head.map((t, i) => h('th', { class: i ? 'n' : null }, t, i === 2 ? h('span', { class: 'sub' }, `Today: ${fmt.usd(a.c.billed)}`) : null)))),
      h('tbody', {}, scenGroup(state.atg).map((s) => {
        const r = comCell(a, s);
        const cells = [h('td', { class: 'lead' }, h('a', { href: `#/comparison?s=${s.id}&a=${a.code}` }, scenTitle(s))),
          h('td', { class: 'n', 'data-label': head[1] }, millPct(r.mill_pct)),
          h('td', { class: 'n', 'data-label': head[2] }, fmt.usd(r.bill_scen)),
          h('td', { class: 'n', 'data-label': head[3] }, usdChange(r.change))];
        if (per) cells.push(h('td', { class: 'n', 'data-label': head[4] }, usdChange(r.change_per_unit)));
        return h('tr', {}, cells);
      })))));
}
function comEffects(a) {
  const x = (CX.comx || {})[a.code];
  if (!x) return document.createDocumentFragment();
  return box(`How each scenario affects ${lcFirst(a.name)}`,
    h('p', {}, 'Click a scenario title to explore in more detail how it affects this archetype.'),
    h('div', { class: 'effects' }, scenGroup(state.atg).map((s) => h('div', { class: 'effect' },
      h('h4', {}, h('a', { href: `#/comparison?s=${s.id}&a=${a.code}` }, scenTitle(s))), h('p', { html: x.text[s.id] || '' })))));
}
// Key Findings: rendered only for the cost35 and realloc groups, and not at all otherwise,
// so nothing (heading, container or space) is left behind when the Task Force group is selected.
function keyFindings(a) {
  const kf = (CX.kf || {})[a.code];
  if (!kf || !KF_GROUPS.includes(state.atg)) return null;
  return h('div', { class: 'key-findings' }, h('h4', {}, 'Key findings'), h('ul', {}, kf.map((t) => h('li', { html: t }))));
}
// Pronouns for the single-person vignettes; couples and families take "their".
const VIG_PRON = { R4: 'her', R6: 'her', B1: 'her', B3: 'his', B7: 'her' };
// "After receiving relief from ..., Linda's current tax burden is $1,080, exactly 4% of her income."
function vignetteNowSentence(a) {
  const v = D.vignette_cells.find((r) => r.a === a.bcode && r.s === '1');
  const full = CX.vxs[a.code].name, plural = / and /.test(full), pron = VIG_PRON[a.code] || 'their';
  // As the scenario summaries write it: "Linda", "the Caouettes", "Katie and Ryan".
  const words = full.split(' '), surname = plural && words.length > 3 ? words[words.length - 1] : null;
  const name = surname ? `the ${surname}s` : plural ? full : words[0];
  const net = v.counted_tax_base - v.credit_base, credit = v.credit_base >= 1;
  const pct = Math.abs(v.burden_base - 0.04) < 0.0005 ? 'exactly 4%' : fmt.pct(v.burden_base);
  const progs = v.owner ? (credit ? 'the Homestead Exemption and Fairness Credit' : 'the Homestead Exemption') : (credit ? 'the Fairness Credit' : null);
  return progs
    ? `After receiving relief from ${progs}, ${name}${surname ? '’' : '’s'} current tax burden is ${fmt.usd10(net)}, ${pct} of ${pron} income.`
    : `${name[0].toUpperCase() + name.slice(1)} ${plural ? 'receive' : 'receives'} no relief from existing programs; ${pron} current tax burden is ${fmt.usd10(net)}, ${pct} of ${pron} income.`;
}
function vignetteEffects(a) {
  const vx = CX.vxs[a.code];
  if (!vx) return document.createDocumentFragment();
  return box(`How each scenario affects ${vx.name}`,
    h('p', {}, vignetteNowSentence(a), h('br'), 'Click a scenario title to explore in more detail how it affects this archetype.'),
    h('div', { class: 'effects' }, scenGroup(state.atg).map((s) => h('div', { class: 'effect' },
      h('h4', {}, h('a', { href: `#/comparison?s=${s.id}&a=${a.code}` }, scenTitle(s))), h('p', { html: vx.text[s.id] || '' })))));
}
function decileDistribution(a) {
  const rows = D.decile_cells.filter((r) => r.s === '1' && r.a === a.bcode && r.households != null).sort((x, y) => x.d - y.d);
  if (rows.length !== 10) {
    return exhibit({ title: `Where ${a.code} households sit in Maine’s income distribution`, body: h('p', { class: 'small muted' }, 'This chart is not yet available for this archetype.') });
  }
  const tot = sum(rows.map((r) => r.households));
  const vals = rows.map((r) => r.households / tot);
  const ranges = decileRanges();
  return exhibit({
    title: `Where ${a.code} households sit in Maine’s income distribution`,
    sub: 'Share of this archetype’s households in each tenth of Maine households by income.',
    plot: (el) => vbars(el, {
      cats: vals.map((_, i) => ({ label: String(i + 1), tip: `Decile ${i + 1}: ${ranges[i]}` })),
      series: [{ name: 'Share of households', color: 's-now', values: vals }], fmt: (v) => fmt.pct(v), fmtTick: (v) => fmt.pct(v, 0), height: 200,
      xTitle: 'Income decile, lowest (1) to highest (10)', aria: `${a.code} households by income decile`,
    }),
    table: dataTable(['Decile', 'Household income', 'Share of households'], vals.map((v, i) => [String(i + 1), ranges[i].replace('household income ', ''), fmt.pct(v)]), 2),
    notes: ['Each decile holds a tenth of all Maine households, so a bar above 10% means the archetype is over-represented there.'],
  });
}
function pageArchetypes(page) {
  const pick = (code) => { state.a = code; state.aset = arch(code).set; rerender(); goTo('part-explore'); };
  const set = state.aset;
  page.append(h('h2', { class: 'page' }, PAGE_TITLES.archetypes), pageIntro('Archetypes'));

  page.append(part('Compare the archetypes', 'overview'));
  page.append(h('div', { class: 'selector' }, h('div', { class: 'control' }, h('span', {}, 'Archetype set'),
    seg(Object.entries(SET_LABEL), set, (v) => { state.aset = v; state.a = archSet(v)[0].code; rerender(); }))));
  const defs = ['For renters, <strong>Property Tax</strong> is 15% of rent, which is the share counted for the Property Tax Fairness Credit.',
    '<br><strong>Share Burdened</strong> is the proportion of households for whom property tax exceeds 6% of income.'];
  const burTotal = sum(archSet('bur').map((x) => x.p.households));
  const burShare = burTotal / D.counts.households;
  const notes = set === 'com' ? null : set === 'rep' ? defs
    : [`Every household in these archetypes pays more than 6% of their income in property tax, even after receiving existing relief. There are ${fmt.int(burTotal)} of them, about one in ${Math.round(1 / burShare)} Maine households. Every burdened household is placed into one of these 7 archetypes.`, '<br>' + defs[0], defs[1]];
  page.append(exhibit({
    title: `The ${archSet(set).length === 6 ? 'six' : 'seven'} ${SET_LABEL[set]}`,
    sub: 'Select an archetype to explore it below.', body: set === 'com' ? comSummaryTable(pick) : archSummaryTable(set, pick), notes,
  }));

  const a = arch(state.a);
  const archSelect = h('label', { class: 'control' }, h('span', {}, 'Archetype'),
    h('select', { onchange: (e) => { state.a = e.target.value; state.aset = arch(state.a).set; rerender(); } },
      Object.entries(SET_LABEL).map(([sk, sl]) => h('optgroup', { label: sl }, archSet(sk).map((x) => h('option', { value: x.code, selected: x.code === a.code }, `${x.code}. ${x.name}`))))));
  const groupPicker = () => h('div', { class: 'selector' }, h('div', { class: 'control' }, h('span', {}, 'Scenario group'),
    seg(Object.entries(D.groups), state.atg, (v) => { state.atg = v; rerender(); })));
  if (isCom(a)) {
    page.append(part('Explore a specific archetype', 'explore'));
    page.append(h('div', { class: 'stickybar' }, archSelect, comFacts(a)));
    const cc = CX.com[a.code];
    const side = h('aside', { class: 'ws-side panel' },
      h('h3', { class: 'et' }, `${a.code}. ${a.name}`), h('p', { class: 'small muted' }, SET_LABEL[a.set]),
      cc.summary ? h('p', { html: cc.summary }) : null);
    page.append(h('div', { class: 'ws-grid' }, side, h('div', { class: 'ws-main' }, comVignetteBox(a))));
    page.append(part(`How each policy scenario affects archetype ${a.code}`, 'scenarios'));
    page.append(groupPicker(), comScenarioTable(a), comEffects(a));
    return;
  }
  const c = CX.arch[a.code], p = a.p, sb = sharesBurdened(a);
  page.append(part('Explore a specific archetype', 'explore'));
  page.append(h('div', { class: 'stickybar' },
    archSelect,
    facts([['Households surveyed', fmt.int(p.n)], ['Households represented', fmt.int(p.households)], ['Median income', fmt.usd100(p.med_income)],
      isRenter(a) ? ['Median rent', `${fmt.usd10(medRentMonthly(a))} a month`] : ['Median property tax', fmt.usd10(p.med_tax)],
      ['Median burden, before → after relief', `${fmt.pct(p.burden_pre)} → ${fmt.pct(p.burden_post)}`],
      ['Share burdened, before → after relief', shareArrow(sb.before, sb.now)]])));
  const side = h('aside', { class: 'ws-side panel' },
    h('h3', { class: 'et' }, `${a.code}. ${a.name}`), h('p', { class: 'small muted' }, SET_LABEL[a.set]),
    renderBlocks(c.intro),
    keyFindings(a),
    h('h4', {}, 'Where they live'), areaTableEl(a),
    h('p', { class: 'notes', html: 'Four regions built from the ten survey areas; <a href="#/about">About the model</a> lists which areas make up each.' }));
  // Order (Steve, 10-19): income distribution, burden, then the vignette, last before the scenario section.
  page.append(h('div', { class: 'ws-grid' }, side, h('div', { class: 'ws-main' }, decileDistribution(a), burdenExhibit(a), vignetteBox(a))));

  page.append(part(`How each policy scenario affects archetype ${a.code}`, 'scenarios'));
  page.append(groupPicker());
  page.append(archScenarioTable(a), vignetteEffects(a));
  // Key findings stay hidden until their copy is ready (Explorer-Ready Copy, 10-19).
}

// ------------------------------------------------------------ Comparison page
function workedExample(a, s) {
  const v = D.vignette_cells.find((r) => r.a === a.bcode && r.s === s.id);
  if (!v) return document.createDocumentFragment();
  const moves = D.town_mill_scenarios.includes(s.id);
  const isHP = s.family === 'HPLUS';
  const mill1 = v.town_mill * (1 + (v.town_dmill || 0));
  // Taxable value is what the bill is computed on: (home value less the exemption) x the town's rate.
  const tax0 = v.owner ? v.bill_base / v.town_mill : 0, tax1 = v.owner ? v.bill_scen / mill1 : 0;
  const U = 'unchanged';
  const rows = [
    ['Full-value tax rate', fmt.mills(v.town_mill), moves ? `${fmt.mills(mill1)} (${fmt.pctS(v.town_dmill || 0, 2)})` : U],
    ['Household income', fmt.usd(v.income), U],
  ];
  if (v.owner) rows.push(['Home value', fmt.usd(v.home_value), U], ['Taxable value, after the homestead exemption', fmt.usd(tax0), Math.abs(tax1 - tax0) < 1 ? U : fmt.usd(tax1)]);
  else rows.push(['Annual rent', fmt.usd(v.rent_annual), U]);
  rows.push(
    [v.owner ? 'Property tax bill' : '15% of rent, counted as property tax', fmt.usd(v.counted_tax_base), fmt.usd(v.counted_tax_scen)],
    [isHP ? 'Fairness Credit today; Homestead Plus payment under the scenario' : 'Fairness Credit', fmt.usd(v.credit_base), fmt.usd(v.credit_scen)],
    ['Property tax after relief', fmt.usd(v.counted_tax_base - v.credit_base), fmt.usd(v.counted_tax_scen - v.credit_scen)],
    ['Burden, as a share of income', fmt.pct(v.burden_base), fmt.pct(v.burden_scen)]);
  const vx = CX.vxs[a.code];
  const text = vx ? vx.text[s.id] : '';
  return box(`How Scenario ${s.id} affects ${vx ? vx.name : 'one ' + a.code + ' household'}`,
    text ? h('p', { class: 'effect-text', html: text }) : null,
    h('div', { class: 'tscroll' }, h('table', { class: 'stack' },
      h('thead', {}, h('tr', {}, h('th', {}, ''), h('th', { class: 'n' }, 'Today'), h('th', { class: 'n' }, `Under Scenario ${s.id}`))),
      h('tbody', {}, rows.map((r) => h('tr', {}, h('td', { class: 'lead' }, r[0]), h('td', { class: 'n', 'data-label': 'Today' }, r[1]), h('td', { class: 'n' + (r[2] === U ? ' muted' : ''), 'data-label': `Under Scenario ${s.id}` }, r[2])))))));
}
function comparisonSummary(a, s) {
  const now = sharesBurdened(a).now;
  const scenBurd = share6(D.burden_cells.find((r) => r.s === s.id && r.a === a.bcode).bins);
  let better, worse, mean, extra = [];
  if (a.set === 'rep') {
    const r = D.broad_cells.find((x) => x.s === s.id && x.a === a.bcode);
    better = r.gaining; worse = r.losing; mean = r.per_hh;
    [better, worse] = [better / r.households, worse / r.households];
  } else {
    const r = D.narrow_cells.find((x) => x.s === s.id && x.a === a.bcode);
    better = r.share_better; worse = r.share_worse; mean = r.mean_gain_delivered;
    extra = [['Median burden, today → under the scenario', `${fmt.pct(r.burden_now)} → ${fmt.pct(r.burden_scen)}`]];
  }
  const [pb, pw, pu] = shares100([better, worse, Math.max(0, 1 - better - worse)]);
  const rows = [['Households better off', pb], ['Households worse off', pw], ['Households left unchanged', pu], ...extra,
    ['Share burdened before → after relief', shareArrow(now, scenBurd)], ['Average new relief per household', fmt.usdS10(mean) + ' a year']];
  return exhibit({
    title: 'Summary',
    body: h('div', { class: 'tscroll' }, h('table', { class: 'keyfig' }, h('tbody', {}, rows.map(([k, v]) => h('tr', {}, h('td', {}, k), h('td', { class: 'n' }, v)))))),
    notes: ['<strong>Share Burdened</strong> is the proportion of households for whom property tax exceeds 6% of income.'],
  });
}
function comComparison(a, s) {
  const r = comCell(a, s), x = (CX.comx || {})[a.code], per = a.c.units > 1;
  const rows = [['Mill rate change in ' + a.c.town, 'today’s rate', millPct(r.mill_pct)],
    ['Property tax bill', fmt.usd(r.bill_base), fmt.usd(r.bill_scen)],
    ['Change in the bill', '', usdChange(r.change)]];
  if (per) rows.push(['Change per unit', '', usdChange(r.change_per_unit)]);
  return box(`How Scenario ${s.id} affects ${lcFirst(a.name)}`,
    x && x.text[s.id] ? h('p', { class: 'effect-text', html: x.text[s.id] }) : null,
    h('div', { class: 'tscroll' }, h('table', { class: 'stack' },
      h('thead', {}, h('tr', {}, h('th', {}, ''), h('th', { class: 'n' }, 'Today'), h('th', { class: 'n' }, `Under Scenario ${s.id}`))),
      h('tbody', {}, rows.map((q) => h('tr', {}, h('td', { class: 'lead' }, q[0]), h('td', { class: 'n', 'data-label': 'Today' }, q[1]), h('td', { class: 'n', 'data-label': `Under Scenario ${s.id}` }, q[2])))))));
}
function pageComparison(page) {
  page.append(h('h2', { class: 'page' }, PAGE_TITLES.comparison), pageIntro('Comparison'));
  const s = scen(state.cs), a = arch(state.ca);
  // Two fixed rows, so the archetype picker never rides up beside the scenario picker.
  page.append(h('div', { class: 'selector rows' },
    h('div', { class: 'sel-row' },
      h('div', { class: 'control' }, h('span', {}, 'Scenario group'), seg(Object.entries(D.groups), state.csg, (v) => { state.csg = v; state.cs = scenGroup(v)[0].id; rerender(); })),
      h('label', { class: 'control' }, h('span', {}, 'Scenario'), h('select', { onchange: (e) => { state.cs = e.target.value; rerender(); } }, scenGroup(state.csg).map((x) => h('option', { value: x.id, selected: x.id === s.id }, scenTitle(x)))))),
    h('div', { class: 'sel-row' },
      h('div', { class: 'control' }, h('span', {}, 'Archetype set'), seg(Object.entries(SET_LABEL), state.cas, (v) => { state.cas = v; state.ca = archSet(v)[0].code; rerender(); })),
      h('label', { class: 'control' }, h('span', {}, 'Archetype'), h('select', { onchange: (e) => { state.ca = e.target.value; rerender(); } }, archSet(state.cas).map((x) => h('option', { value: x.code, selected: x.code === a.code }, `${x.code}. ${x.name}`)))))));
  const com = isCom(a);
  const story = com ? CX.com[a.code].vignette : CX.arch[a.code].vignette;
  // A commercial archetype's introduction is its vignette (Steve, 29 Oct), so no separate expander.
  const short = com ? CX.com[a.code].vignette : (CX.archShort[a.code] || []);
  page.append(h('div', { class: 'intro-pair' },
    h('div', {}, h('h3', { class: 'pair-h' }, 'The Policy Scenario'), h('p', { class: 'pair-name' }, scenTitle(s)), h('p', { class: 'small muted' }, D.groups[s.group]), renderBlocks(CX.scen[s.id].short),
      h('p', { class: 'small' }, h('a', { href: `#/scenarios?g=${s.group}&s=${s.id}&go=explore` }, 'Full treatment on the Policy Scenarios page'))),
    h('div', {}, h('h3', { class: 'pair-h' }, 'The Chosen Archetype'), h('p', { class: 'pair-name' }, `${a.code}. ${a.name}`), h('p', { class: 'small muted' }, SET_LABEL[a.set]), renderBlocks(short),
      story && !com ? h('details', { class: 'more' }, h('summary', {}, 'Meet the household'), story.map((b) => h('p', { class: 'story', html: b.html }))) : null,
      h('p', { class: 'small' }, h('a', { href: `#/archetypes?a=${a.code}&go=explore` }, 'Full profile on the Household Archetypes page')))));
  page.append(part(`What Scenario ${s.id} does for ${a.code}`, 'results'));
  if (com) { page.append(comComparison(a, s)); return; }
  const build = () => h('div', { class: 'results' },
    h('div', {}, burdenExhibit(a, s), dollarsExhibit(s, a, `Number of households in archetype ${a.code} made better or worse off by scenario ${s.id}.`)),
    h('div', {}, comparisonSummary(a, s)));
  if (a.set === 'bur') { page.append(workedExample(a, s)); page.append(build()); }
  else { page.append(build()); page.append(workedExample(a, s)); }
  // Key findings stay hidden until their copy is ready (Explorer-Ready Copy, 10-19); when shown, they go last.
}
// ------------------------------------------------------------ About page
function pageAbout(page) {
  page.append(h('h2', { class: 'page' }, PAGE_TITLES.about));
  const aboutIntro = sec('Model', 'About the model');
  if (aboutIntro) page.append(prose(aboutIntro.blocks));
  const how = sec('Model', 'How the model works') || sec('Model, Limits, Validation', 'Modelling');
  page.append(part('How the model works', 'how'), renderBlocks(how.blocks.map((b) => (b.type === 'p' && /^<strong>Geography<\/strong>/.test(b.html))
    ? { ...b, html: b.html + ' More detail is below, under “Why results are reported by area, not by town”.' } : b)));
  const lim = sec('Limitations', 'Limitations');
  page.append(part('Limitations to keep in mind', 'limits'), renderBlocks(lim.blocks));
  const val = sec('Validation', 'Validation');
  page.append(part('How we know the model can be trusted', 'validation'), renderBlocks(val.blocks));
  const reg = sec('Archetypes', 'Archetypes - Page Introduction').blocks.find((b) => b.type === 'p' && /^Where each archetype lives/.test(stripTags(b.html)));
  page.append(part('Why results are reported by area, not by town', 'area-not-town'),
    h('p', {}, `This tool mixes two levels of geography, and they are not equally precise. Mill rate changes are worked out municipality by municipality from each town’s own valuation return, so the figures for all ${D.towns.length} municipalities are real. Household characteristics are not. The Census household survey places each household in one of ${D.puma_order.length} survey areas, each covering dozens of towns, and no finer.`),
    h('p', {}, 'So a household figure attached to a town, such as a worked-example household’s bill, describes what a scenario would do to a typical household of that area if it lived in that town. It does not describe the households who actually live there. That is why the charts report survey areas and never shade individual towns.'),
    exhibit({
      title: 'Maine’s ten survey areas, most rural to most urban',
      body: h('div', { class: 'geo-grid' },
        h('div', {}, dataTable(['Rank', 'Survey area', 'Households'], D.puma_order.map((p) => [String(p.rank), p.label, fmt.int(D.puma_cells.find((r) => r.puma === p.puma && r.s === '1').households)]), 2)),
        h('figure', { class: 'geo-map' }, h('img', { src: at('assets/maine-survey-areas-map.jpg'), width: 996, height: 915, loading: 'lazy', alt: 'Map of Maine divided into its ten Census survey areas, from Northeast Maine (Aroostook, Washington and northern Penobscot counties) to Southern Maine (York and western Cumberland).' }))),
      notes: ['<a href="https://felt.com/map/Maine-Municipalities-Classification-n301K9Cd1RK6I6HE9AYdyNSB?share=1&amp;loc=45.263,-69.017,6.97z" target="_blank" rel="noopener">See the survey areas and municipalities on an interactive map</a>.'],
    }),
    reg ? h('h4', {}, 'The four regions used for archetypes') : null,
    reg ? h('p', { html: reg.html.replace(/^<strong>Where each archetype lives<\/strong>\s*/, 'Where each archetype lives ') }) : null);
}
// ------------------------------------------------------------ boot
async function boot() {
  try {
    const [d, c, x, f] = await Promise.all([
      fetch(at('data/dashboard.json'), { cache: 'no-cache' }).then((r) => r.json()),
      fetch(at('data/copy.json'), { cache: 'no-cache' }).then((r) => r.json()),
      fetch(at('data/copy_x.json'), { cache: 'no-cache' }).then((r) => r.json()),
      fetch(at('data/findings.csv'), { cache: 'no-cache' }).then((r) => r.text()),
    ]);
    D = d; COPY = c; CX = x; FIND = parseCSV(f);
  } catch (e) {
    console.error(e);
    main.innerHTML = '<p>The model results could not be loaded. If you opened this file directly, serve the folder over HTTP instead.</p>';
    return;
  }
  SCEN = D.scenarios;
  buildArchetypes();
  if (!hasDecileFields()) warnings.push('Two of the income-decile views (per household, share of income) are not available in this version.');
  // Copy/bundle consistency checks report to the console, never to readers.
  for (const w of warnings) console.warn(w);
  $('#build-stamp').textContent = `Version of ${versionDate()}.`;
  readHash();
  render();
  if (state.go) { goTo('part-' + state.go); state.go = null; history.replaceState(null, '', hashFor()); }
}
boot();
})();
