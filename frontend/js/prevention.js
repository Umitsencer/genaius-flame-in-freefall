/* Prevention Evidence Summary (Data page). Renders /api/prevention/summary; all text escaped. */
(function (root) {
  'use strict';
  var doc = root.document;
  if (!doc) return;
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function list(items, fn) {
    if (!items || !items.length) return '<p class="muted">None in the selected sources.</p>';
    return '<ul>' + items.map(function (x) { return '<li>' + fn(x) + '</li>'; }).join('') + '</ul>';
  }
  function render(data) {
    var out = doc.getElementById('prevention-out');
    if (!out) return;
    var html = '<p class="how"><strong>' + esc(data.badge) + '</strong> · ' + esc(data.boundary) + '</p>';
    (data.topics || []).forEach(function (t) {
      html += '<article class="prev-topic" data-topic="' + esc(t.topic) + '"><h3>' + esc(t.title) + '</h3>' +
        '<h4>Computed from table records</h4>' + list(t.computed, function (c) { return esc(c.text); }) +
        '<h4>Source-document findings (labelled, not recomputed)</h4>' +
        list(t.source_findings, function (f) { return esc(f.text) + ' <em>— ' + esc(f.source) + '</em>'; }) +
        '<h4>Not in the selected sources</h4>' + list(t.not_in_sources, esc) +
        '<h4>Engineering interpretation</h4>' +
        list(t.engineering_interpretation, function (i) { return '<em>' + esc(i.label) + ':</em> ' + esc(i.text); }) +
        '</article>';
    });
    out.innerHTML = html;
  }
  function load() {
    if (!root.FF || !root.FF.api || typeof root.FF.api.preventionSummary !== 'function') return;
    root.FF.api.preventionSummary().then(function (env) { render((env && env.data) || {}); }).catch(function () {
      var out = doc.getElementById('prevention-out');
      if (out) out.innerHTML = '<p class="muted">Prevention summary is unavailable in this environment.</p>';
    });
  }
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', load); else load();
})(typeof window !== 'undefined' ? window : this);
