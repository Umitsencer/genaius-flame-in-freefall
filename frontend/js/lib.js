/* Saf mantık (DOM yok): ön ayarlar, FLEX kanıt özeti, malzeme kanıt sıralaması.
 * Tarayıcıda window.FF.lib, Node'da module.exports olarak kullanılır. */
(function (root) {
  'use strict';

  // Araştırma senaryoları: kesin habitat tasarımı DEĞİL. Yerçekimi g biriminde.
  var GRAVITY = [
    { id: 'micro', label: 'Microgravity (ISS)', g: 0 },
    { id: 'moon', label: 'Moon', g: 0.166 },
    { id: 'mars', label: 'Mars', g: 0.378 },
    { id: 'earth', label: 'Earth', g: 1 }
  ];
  var PRESETS = [
    { id: 'iss', label: 'ISS cabin', o2: 21, p: 1.0, g: 0, hypothetical: false, note: 'Normal air at 1 atm in orbit.' },
    { id: 'expl-moon', label: 'Moon habitat (hypothetical)', o2: 34, p: 0.558, g: 0.166, hypothetical: true, note: 'Hypothetical exploration scenario (34% O₂ at 8.2 psi / 0.558 atm); NOT NASA Lunar 1/6g test evidence or a flight design.' },
    { id: 'expl-mars', label: 'Mars habitat (hypothetical)', o2: 34, p: 0.558, g: 0.378, hypothetical: true, note: 'Hypothetical exploration scenario at Mars 3/8g; NOT NASA Mars 3/8g experimental combustion evidence.' },
    { id: 'earth', label: 'Earth (reference)', o2: 21, p: 1.0, g: 1, hypothetical: false, note: 'Sea-level air, for comparison.' },
    { id: 'custom', label: 'Custom', o2: 21, p: 1.0, g: 0, hypothetical: false, note: 'Set your own values.' }
  ];

  function median(a) {
    var v = a.filter(function (x) { return x != null && !isNaN(x); }).sort(function (x, y) { return x - y; });
    if (!v.length) return null;
    var m = v.length >> 1;
    return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
  }

  // %95 Wilson güven aralığı
  function wilson(k, n) {
    if (!n) return null;
    var z = 1.96, p = k / n, d = 1 + z * z / n;
    var c = (p + z * z / (2 * n)) / d, h = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d;
    return [Math.max(0, c - h), Math.min(1, c + h)];
  }

  /* FLEX kanıtı: yakıt + O2 + basınç penceresi. Eşleşme azsa pencere genişletilir ve bu bildirilir. */
  function flexEvidence(rows, q) {
    var o2Win = q.o2Win || 2, pWin = q.pWin || 0.1, minN = q.minN || 5, widen = 0, sel = [];
    for (; widen <= 3; widen++) {
      var f = Math.pow(2, widen);
      sel = rows.filter(function (r) {
        return r.fuel === q.fuel && r.o2 != null && Math.abs(r.o2 - q.o2) <= o2Win * f &&
          (r.p_atm == null || Math.abs(r.p_atm - q.p) <= pWin * f);
      });
      if (sel.length >= minN) break;
    }
    var level = 'matched';
    if (sel.length < minN) {
      sel = rows.filter(function (r) { return r.fuel === q.fuel; });
      level = 'fuel-wide';
      widen = null;
    }
    var counts = {};
    sel.forEach(function (r) { var e = r.end || 'Not reported'; counts[e] = (counts[e] || 0) + 1; });
    var outcomes = Object.keys(counts).map(function (k) {
      return { name: k, n: counts[k], share: counts[k] / sel.length, ci: wilson(counts[k], sel.length) };
    }).sort(function (a, b) { return b.n - a.n; });
    return {
      n: sel.length, level: level, o2Win: widen == null ? null : o2Win * Math.pow(2, widen),
      pWin: widen == null ? null : pWin * Math.pow(2, widen), outcomes: outcomes, top: outcomes[0] || null,
      d0: median(sel.map(function (r) { return r.d0; })), dExt: median(sel.map(function (r) { return r.d_ext; })),
      k: median(sel.map(function (r) { return r.k; })), tBurn: median(sel.map(function (r) { return r.t_burn; })),
      o2Range: [Math.min.apply(null, sel.map(function (r) { return r.o2; })), Math.max.apply(null, sel.map(function (r) { return r.o2; }))]
    };
  }

  function testO2(t) {
    if (t.o2 != null) return [t.o2, t.o2];
    if (t.o2_range) return t.o2_range;
    return null;
  }

  /* Malzeme kanıt sıralaması. Güvenlik puanı DEĞİL: yalnızca "bu O2'ye yakın hangi testler var,
   * orada ölçülen CO artışı ne" bilgisini sıralar. */
  function materialEvidence(tests, q) {
    var win = q.win || 3, groups = {};
    tests.forEach(function (t) {
      if (/soot cleaning/i.test(t.material)) return;
      (groups[t.material] = groups[t.material] || []).push(t);
    });
    var out = Object.keys(groups).map(function (name) {
      var ts = groups[name], withO2 = ts.filter(function (t) { return testO2(t); });
      var near = withO2.filter(function (t) { var r = testO2(t); return q.o2 >= r[0] - win && q.o2 <= r[1] + win; });
      var nearest = null;
      withO2.forEach(function (t) {
        var r = testO2(t), d = q.o2 < r[0] ? r[0] - q.o2 : q.o2 > r[1] ? q.o2 - r[1] : 0;
        if (nearest == null || d < nearest.dist) nearest = { dist: d, test: t };
      });
      var co = near.map(function (t) { return t.d_co; }).filter(function (x) { return x != null; });
      var all = withO2.reduce(function (a, t) { var r = testO2(t); return [Math.min(a[0], r[0]), Math.max(a[1], r[1])]; }, [Infinity, -Infinity]);
      return {
        name: name, nTotal: ts.length, nNoConditions: ts.length - withO2.length, nNear: near.length,
        coMedian: median(co), nCo: co.length, nCoOver: near.filter(function (t) { return t.co_over; }).length,
        dO2Median: median(near.map(function (t) { return t.d_o2; })),
        nearestDist: nearest ? nearest.dist : null, o2Range: withO2.length ? all : null,
        sources: Array.from(new Set(ts.map(function (t) { return t.src; }))), near: near, tests: ts,
        forms: Array.from(new Set(ts.map(function (t) { return t.form; })))
      };
    });
    // Sıra: yakın testte >=3 CO okuması olanlar (en düşük CO artışı önce), sonra az okumalılar, sonra yakın testi olmayanlar.
    function tier(g) { return g.nNear === 0 ? 2 : (g.nCo >= 3 ? 0 : 1); }
    out.sort(function (a, b) {
      var ta = tier(a), tb = tier(b);
      if (ta !== tb) return ta - tb;
      if (ta === 0) return a.coMedian - b.coMedian;
      if (ta === 1) return b.nNear - a.nNear;
      if ((a.nearestDist == null) !== (b.nearestDist == null)) return a.nearestDist == null ? 1 : -1;
      return (a.nearestDist || 0) - (b.nearestDist || 0);
    });
    var maxTested = Math.max.apply(null, tests.map(function (t) { var r = testO2(t); return r ? r[1] : -Infinity; }));
    return { win: win, groups: out, maxTestedO2: maxTested, beyond: q.o2 > maxTested + win };
  }

  var lib = { GRAVITY: GRAVITY, PRESETS: PRESETS, median: median, wilson: wilson, flexEvidence: flexEvidence, materialEvidence: materialEvidence };
  if (typeof module !== 'undefined' && module.exports) module.exports = lib;
  else { root.FF = root.FF || {}; root.FF.lib = lib; }
})(typeof window !== 'undefined' ? window : globalThis);
