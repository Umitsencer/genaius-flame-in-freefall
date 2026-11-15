/* Shareable views and citations. Browser: FF.share, FF.cite. Node: module.exports (for tests). */
(function (root) {
  'use strict';

  function copy(text, btn) {
    function done() { if (btn) { var t = btn.getAttribute('data-label') || btn.textContent; btn.setAttribute('data-label', t); btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = t; }, 1400); } }
    function fallback() {
      var ta = document.createElement('textarea'); ta.value = text; ta.setAttribute('readonly', ''); ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
      document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); } catch (e) { /* ignore */ } ta.remove(); done();
    }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fallback); else fallback();
  }

  // The view lives in the query string so section anchors (#s-rows) keep working.
  function read() { return new URLSearchParams(location.search); }
  function write(obj) {
    var p = new URLSearchParams();
    Object.keys(obj).forEach(function (k) { if (obj[k] != null && obj[k] !== '') p.set(k, obj[k]); });
    var q = p.toString();
    try { history.replaceState(null, '', location.pathname + (q ? '?' + q : '') + location.hash); } catch (e) { /* file:// */ }
  }

  function tex(s) { return String(s).replace(/([&%#_$])/g, '\\$1'); }
  // e is an experiment from FF_DATA.unified.exps, r (optional) one row of it
  function text(e, r) {
    return 'NASA Physical Sciences Informatics. ' + e.title + ' (' + e.name + '), ' + e.id + ', version ' + e.version +
      (r ? ', experimental table row ' + r.row + ' of ' + r.file : '') + '. Data set, ' + e.license + '. https://doi.org/' + e.doi + '. Retrieved ' + e.retrieved + '.';
  }
  function bib(e, r) {
    var key = e.id.toLowerCase().replace('-', '') + '_v' + e.version + (r ? '_row' + r.row : '');
    return '@dataset{' + key + ',\n  title = {' + tex(e.title) + ' (' + tex(e.name) + ')},\n  publisher = {NASA Physical Sciences Informatics},\n  version = {' + e.version + '},\n  doi = {' + e.doi + '},\n  url = {https://doi.org/' + e.doi + '},\n' +
      '  note = {' + e.id + (r ? ', experimental table row ' + r.row + ' of ' + tex(r.file) : '') + '; license ' + e.license + '; retrieved ' + e.retrieved + '}\n}';
  }

  var api = { share: { copy: copy, read: read, write: write }, cite: { text: text, bib: bib } };
  if (typeof module !== 'undefined' && module.exports) module.exports = api.cite;
  else { root.FF = root.FF || {}; root.FF.share = api.share; root.FF.cite = api.cite; }
})(typeof window !== 'undefined' ? window : globalThis);
