/* Small statistics helpers (no DOM). Browser: FF.stats, Node: module.exports. */
(function (root) {
  'use strict';

  function clean(a) { return a.filter(function (x) { return x != null && !isNaN(x); }); }
  function sorted(a) { return clean(a).sort(function (x, y) { return x - y; }); }

  // Linear-interpolated quantile (type 7), q in [0,1]
  function quantile(a, q) {
    var v = sorted(a); if (!v.length) return null;
    var pos = (v.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
    return v[lo] + (v[hi] - v[lo]) * (pos - lo);
  }
  function median(a) { return quantile(a, 0.5); }
  function mean(a) { var v = clean(a); return v.length ? v.reduce(function (s, x) { return s + x; }, 0) / v.length : null; }

  function summary(a) {
    var v = sorted(a), n = v.length;
    if (!n) return { n: 0 };
    return { n: n, min: v[0], q1: quantile(v, 0.25), median: quantile(v, 0.5), q3: quantile(v, 0.75), max: v[n - 1], mean: mean(v) };
  }

  // Tukey box: whiskers reach the furthest point within 1.5 IQR of the box
  function box(a) {
    var s = summary(a); if (!s.n) return s;
    var iqr = s.q3 - s.q1, lo = s.q1 - 1.5 * iqr, hi = s.q3 + 1.5 * iqr, v = sorted(a);
    s.wLo = v.filter(function (x) { return x >= lo; })[0];
    s.wHi = v.filter(function (x) { return x <= hi; }).pop();
    s.outliers = v.filter(function (x) { return x < lo || x > hi; });
    return s;
  }

  function ranks(v) {
    var idx = v.map(function (x, i) { return [x, i]; }).sort(function (a, b) { return a[0] - b[0]; }), r = new Array(v.length), i = 0;
    while (i < idx.length) {
      var j = i; while (j + 1 < idx.length && idx[j + 1][0] === idx[i][0]) j++;
      var avg = (i + j) / 2 + 1; for (var k = i; k <= j; k++) r[idx[k][1]] = avg; i = j + 1;
    }
    return r;
  }
  function pearson(x, y) {
    var n = x.length, mx = mean(x), my = mean(y), sxy = 0, sxx = 0, syy = 0;
    for (var i = 0; i < n; i++) { sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) * (x[i] - mx); syy += (y[i] - my) * (y[i] - my); }
    return sxx && syy ? sxy / Math.sqrt(sxx * syy) : null;
  }
  // Spearman rank correlation on pairs where both values exist. Returns {rho, n}.
  function spearman(xs, ys) {
    var x = [], y = [];
    for (var i = 0; i < xs.length; i++) if (xs[i] != null && ys[i] != null && !isNaN(xs[i]) && !isNaN(ys[i])) { x.push(xs[i]); y.push(ys[i]); }
    if (x.length < 3) return { rho: null, n: x.length };
    return { rho: pearson(ranks(x), ranks(y)), n: x.length };
  }
  function describeRho(r) {
    if (r == null) return 'not enough pairs';
    var a = Math.abs(r), w = a < 0.2 ? 'very weak' : a < 0.4 ? 'weak' : a < 0.6 ? 'moderate' : a < 0.8 ? 'strong' : 'very strong';
    return w + (a < 0.2 ? '' : r > 0 ? ' positive' : ' negative');
  }

  // Round-number axis ticks covering [min, max]
  function ticks(min, max, count) {
    if (min === max) { max = min + 1; }
    var span = max - min, step = Math.pow(10, Math.floor(Math.log10(span / (count || 5)))), err = (count || 5) / span * step;
    if (err <= 0.15) step *= 10; else if (err <= 0.35) step *= 5; else if (err <= 0.75) step *= 2;
    var lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step, out = [];
    for (var v = lo; v <= hi + step / 2; v += step) out.push(Math.round(v / step * 1e6) / 1e6 * step);
    return out;
  }

  var api = { quantile: quantile, median: median, mean: mean, summary: summary, box: box, spearman: spearman, describeRho: describeRho, ticks: ticks };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else { root.FF = root.FF || {}; root.FF.stats = api; }
})(typeof window !== 'undefined' ? window : globalThis);
