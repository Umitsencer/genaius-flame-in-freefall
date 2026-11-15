/* Site language (Turkish / English). The pages are written in English. In Turkish mode this file translates the page as it is
 * drawn: static text, text the scripts build later (a MutationObserver watches), and tooltips. Translations live in
 * i18n-tr.js as [english, turkish] pairs. "{}" in the English part matches any text; in the Turkish part use {1}, {2}
 * for the matches in order. The chosen language is kept in localStorage and shared by every page, including the home page.
 *   FF.i18n.lang()  FF.i18n.set('tr'|'en')  FF.i18n.add([[en, tr], ...])  FF.i18n.missing() */
(function (root) {
  'use strict';
  root.FF = root.FF || {};
  var KEY = 'ff-lang', DEFAULT = 'en';          // English default unless visitor chose Turkish
  var exact = new Map(), rules = [], glossary = [], frags = [], customs = [], lang = DEFAULT;
  try { var saved = localStorage.getItem(KEY); if (saved === 'tr' || saved === 'en') lang = saved; } catch (e) { /* private mode */ }
  var ATTRS = ['placeholder', 'aria-label', 'title', 'alt', 'data-tip', 'aria-valuetext'];
  var SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, NOSCRIPT: 1, CODE: 1, PRE: 1 };
  var listeners = [];

  function esc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  function add(table) {
    table.forEach(function (p) {
      var en = p[0], tr = p[1];
      if (en.indexOf('{}') < 0 && en.indexOf('{#}') < 0) exact.set(en, tr);
      else rules.push({
        // {} matches any text, {#} matches a number without its % or unit
        re: new RegExp('^' + en.split(/(\{#\}|\{\})/).map(function (x) { return x === '{}' ? '([\\s\\S]+?)' : x === '{#}' ? '([-+−~]?\\d[\\d.,]*)' : esc(x); }).join('') + '$'),
        tr: tr,
        lit: en.replace(/\{#\}|\{\}/g, '').length          // how much fixed text the pattern has
      });
    });
    rules.sort(function (a, b) { return b.lit - a.lit; });   // specific patterns first, so a loose one like "{} ({})" never shadows them
  }
  function fragments(table) { table.forEach(function (p) { frags.push([p[0] instanceof RegExp ? p[0] : new RegExp(esc(p[0]), 'g'), p[1]]); }); }
  function custom(fn) { customs.push(fn); }   // fn(english) -> turkish or null, for strings no single pattern can describe
  function words(table) { table.forEach(function (p) { glossary.push([new RegExp('\\b' + p[0] + '\\b', 'g'), p[1]]); }); }
  function gloss(s) { glossary.forEach(function (g) { s = s.replace(g[0], g[1]); }); return s; }

  // English text -> Turkish, or null when there is nothing to change
  var missed = {};
  function translate(core, quiet) {
    var hit = exact.get(core);
    if (hit != null) return hit;
    for (var i = 0; i < rules.length; i++) {
      var m = rules[i].re.exec(core);
      if (m) return gloss(rules[i].tr.replace(/\{(\d)\}/g, function (_, k) { return m[+k] == null ? '' : m[+k]; }));
    }
    for (var c = 0; c < customs.length; c++) { var cv = customs[c](core); if (cv != null) return cv; }
    if (/\.\s/.test(core)) {                                   // several sentences: translate each one alone
      var parts = core.split(/(?<=\.)\s+/), outp = [];
      for (var j = 0; j < parts.length; j++) { var one = translate(parts[j], true); if (one == null) { outp = null; break; } outp.push(one); }
      if (outp) return outp.join(' ');
    }
    if (!quiet && /[A-Za-z]{3}/.test(core)) missed[core.replace(/\d+(\.\d+)?/g, '#')] = 1;
    return null;
  }
  // Hover text is assembled from many small pieces; when no whole-sentence rule fits, replace the pieces one by one.
  function tip(core) {
    var out = translate(core, true);
    if (out != null) return out;
    var s = core;
    frags.forEach(function (f) { s = s.replace(f[0], f[1]); });
    s = gloss(s);
    if (s === core) { if (/[A-Za-z]{3}/.test(core)) missed['@tip ' + core.replace(/\d+(\.\d+)?/g, '#')] = 1; return null; }
    return s;
  }

  var textRec = new WeakMap(), attrRec = new WeakMap();
  function doText(node) {
    var raw = node.nodeValue, rec = textRec.get(node);
    if (lang !== 'tr') { if (rec && rec.out === raw) node.nodeValue = rec.en; textRec.delete(node); return; }
    if (rec && rec.out === raw) return;                       // already translated and untouched
    if (!/[A-Za-z]{2}/.test(raw)) return;
    var lead = /^\s*/.exec(raw)[0], trail = /\s*$/.exec(raw)[0], core = raw.trim().replace(/\s+/g, ' ');   // HTML line breaks inside a sentence must not block a match
    var out = /^(FLEX|BASS|SAFFIRE|SAME|SPICE|CFI|ACME)\b.*[:;]/.test(core) ? tip(core) : translate(core);   // test descriptions are built like hover text
    if (out == null) { textRec.delete(node); return; }
    var val = lead + out + trail;
    textRec.set(node, { en: raw, out: val }); node.nodeValue = val;
  }
  function doAttrs(el) {
    var recs = attrRec.get(el) || {};
    ATTRS.forEach(function (a) {
      if (!el.hasAttribute || !el.hasAttribute(a)) return;
      var raw = el.getAttribute(a), rec = recs[a];
      if (lang !== 'tr') { if (rec && rec.out === raw) el.setAttribute(a, rec.en); delete recs[a]; return; }
      if (rec && rec.out === raw) return;
      var out = /[A-Za-z]{2}/.test(raw) ? (a === 'data-tip' ? tip(raw.trim()) : translate(raw.trim())) : null;
      if (out == null) { delete recs[a]; return; }
      recs[a] = { en: raw, out: out }; el.setAttribute(a, out);
    });
    attrRec.set(el, recs);
  }
  function skipped(el) { for (; el && el.nodeType === 1; el = el.parentNode) if (SKIP[el.tagName] || (el.hasAttribute && el.hasAttribute('data-no-i18n'))) return true; return false; }
  function walk(rootNode) {
    if (!rootNode) return;
    if (rootNode.nodeType === 3) { if (!skipped(rootNode.parentNode)) doText(rootNode); return; }
    if (rootNode.nodeType !== 1 && rootNode.nodeType !== 9) return;
    var base = rootNode.nodeType === 9 ? rootNode.documentElement : rootNode;
    if (skipped(base)) return;
    doAttrs(base);
    var tw = document.createTreeWalker(base, 5, null), n;      // 1 elements + 4 text
    while ((n = tw.nextNode())) {
      if (n.nodeType === 3) { if (!skipped(n.parentNode)) doText(n); } else if (!skipped(n)) doAttrs(n);
    }
  }

  var obs = null;
  function start() {
    walk(document);
    if (obs || !window.MutationObserver) return;
    obs = new MutationObserver(function (list) {
      list.forEach(function (r) {
        if (r.type === 'characterData') { if (!skipped(r.target.parentNode)) doText(r.target); }
        else if (r.type === 'attributes') { if (!skipped(r.target)) doAttrs(r.target); }
        else r.addedNodes.forEach(walk);
      });
      obs.takeRecords();                                       // drop the changes we just made ourselves
    });
    obs.observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  }

  function set(l) {
    if (l !== 'tr' && l !== 'en') return;
    lang = l;
    try { localStorage.setItem(KEY, l); } catch (e) { /* ignore */ }
    document.documentElement.lang = l;
    walk(document);
    listeners.forEach(function (f) { f(l); });
    window.dispatchEvent(new CustomEvent('ff-lang', { detail: l }));
  }
  document.documentElement.lang = lang;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();

  root.FF.i18n = {
    lang: function () { return lang; }, set: set, add: add, words: words, fragments: fragments, custom: custom, onChange: function (f) { listeners.push(f); },
    tr: function (en) { var r = translate(en, true); return r == null ? en : r; },
    t: function (en) { if (lang !== 'tr') return en; var r = translate(en); return r == null ? en : r; },
    missing: function () { return Object.keys(missed).sort(); }, refresh: function () { walk(document); }
  };
})(window);
