/* SVG chart builders for the Material lab. Pure functions: data in, SVG string out.
 * Hover text goes in data-tip, click target in data-id; lab.js wires both. */
(function (root) {
  'use strict';
  var st = root.FF.stats, W = 820;

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function num(v, d) { return v == null ? '' : (Math.abs(v) >= 100 ? Math.round(v) : Math.round(v * Math.pow(10, d == null ? 1 : d)) / Math.pow(10, d == null ? 1 : d)); }
  function lin(d0, d1, r0, r1) { return function (v) { return r0 + (v - d0) / ((d1 - d0) || 1) * (r1 - r0); }; }
  function svgOpen(h, label) { return '<svg viewBox="0 0 ' + W + ' ' + h + '" role="img" aria-label="' + esc(label) + '">'; }

  function xAxis(sx, tk, y, label, fmt) {
    var s = '<line class="axl" x1="' + sx(tk[0]) + '" x2="' + sx(tk[tk.length - 1]) + '" y1="' + y + '" y2="' + y + '"/>';
    tk.forEach(function (t) { s += '<line class="tick" x1="' + sx(t) + '" x2="' + sx(t) + '" y1="' + y + '" y2="' + (y + 5) + '"/><text class="tl" x="' + sx(t) + '" y="' + (y + 19) + '" text-anchor="middle">' + (fmt ? fmt(t) : t) + '</text>'; });
    if (label) s += '<text class="al" x="' + (sx(tk[0]) + sx(tk[tk.length - 1])) / 2 + '" y="' + (y + 40) + '" text-anchor="middle">' + esc(label) + '</text>';
    return s;
  }
  function gridX(sx, tk, y0, y1) { return tk.map(function (t) { return '<line class="grid" x1="' + sx(t) + '" x2="' + sx(t) + '" y1="' + y0 + '" y2="' + y1 + '"/>'; }).join(''); }
  function gridY(sy, tk, x0, x1) { return tk.map(function (t) { return '<line class="grid" x1="' + x0 + '" x2="' + x1 + '" y1="' + sy(t) + '" y2="' + sy(t) + '"/>'; }).join(''); }
  function yAxis(sy, tk, x, label, fmt) {
    var s = '';
    tk.forEach(function (t) { s += '<text class="tl" x="' + (x - 9) + '" y="' + (sy(t) + 4) + '" text-anchor="end">' + (fmt ? fmt(t) : t) + '</text>'; });
    if (label) s += '<text class="al" transform="translate(' + (x - 52) + ' ' + (sy(tk[0]) + sy(tk[tk.length - 1])) / 2 + ') rotate(-90)" text-anchor="middle">' + esc(label) + '</text>';
    return s;
  }
  function untested(sx, from, to, y0, y1) {
    if (from == null || from >= to) return '';
    return '<rect class="gap" x="' + sx(from) + '" y="' + y0 + '" width="' + (sx(to) - sx(from)) + '" height="' + (y1 - y0) + '"/>';
  }
  function userLine(sx, v, y0, y1, label) {
    return '<line class="me" x1="' + sx(v) + '" x2="' + sx(v) + '" y1="' + y0 + '" y2="' + y1 + '"/><text class="mel" x="' + (sx(v) + 6) + '" y="' + (y0 + 12) + '">' + esc(label) + '</text>';
  }
  function empty(msg, h) { return svgOpen(h || 120, msg) + '<text class="tl" x="' + W / 2 + '" y="' + (h || 120) / 2 + '" text-anchor="middle" font-size="14">' + esc(msg) + '</text></svg>'; }

  /* --- scatter with free axes ------------------------------------------------ */
  function scatter(o) {
    var pts = o.points;
    if (!pts.length) return empty('No tests have both values with the current filters.', 200);
    var m = { l: 76, r: 20, t: 20, b: 52 }, H = 380;
    var xs = pts.map(function (p) { return p.x; }), ys = pts.map(function (p) { return p.y; });
    var xd = o.xDomain || [Math.min.apply(null, xs), Math.max.apply(null, xs)], yMin = Math.min(0, Math.min.apply(null, ys)), yMax = Math.max.apply(null, ys);
    var xt = st.ticks(xd[0], xd[1], 6), yt = st.ticks(yMin, yMax, 6);
    var sx = lin(xt[0], xt[xt.length - 1], m.l, W - m.r), sy = lin(yt[0], yt[yt.length - 1], H - m.b, m.t);
    var s = svgOpen(H, o.label) + untested(sx, o.untestedFrom, xt[xt.length - 1], m.t, H - m.b) + gridY(sy, yt, m.l, W - m.r);
    if (yt[0] < 0) s += '<line class="zero" x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + sy(0) + '" y2="' + sy(0) + '"/>';
    (o.lines || []).forEach(function (ln) {
      s += '<polyline fill="none" stroke="' + ln.color + '" stroke-width="2.2" stroke-opacity=".9" points="' + ln.pts.map(function (p) { return sx(p[0]) + ',' + sy(p[1]); }).join(' ') + '"/>';
    });
    pts.forEach(function (p) {
      s += '<circle class="pt' + (p.id === o.selected ? ' sel' : '') + '" cx="' + sx(p.x) + '" cy="' + sy(p.y) + '" r="' + (p.id === o.selected ? 7 : 4.6) + '" fill="' + p.color + '" data-tip="' + esc(p.tip) + '" data-id="' + esc(p.id) + '"/>';
    });
    if (o.userX != null && o.userX >= xt[0] && o.userX <= xt[xt.length - 1]) s += userLine(sx, o.userX, m.t, H - m.b, o.userLabel);
    return s + xAxis(sx, xt, H - m.b, o.xLabel) + yAxis(sy, yt, m.l, o.yLabel) + '</svg>';
  }

  /* --- box plot, one row per group -------------------------------------------- */
  function boxplot(o) {
    var gs = o.groups.filter(function (g) { return g.values.length; });
    if (!gs.length) return empty('No values for the current filters.', 160);
    var rowH = 46, m = { l: 150, r: 24, t: 14, b: 52 }, H = m.t + m.b + gs.length * rowH;
    var all = []; gs.forEach(function (g) { all = all.concat(g.values); });
    var yt = st.ticks(Math.min(0, Math.min.apply(null, all)), Math.max.apply(null, all), 6), sx = lin(yt[0], yt[yt.length - 1], m.l, W - m.r);
    var s = svgOpen(H, o.label) + gridX(sx, yt, m.t, H - m.b);
    if (yt[0] < 0) s += '<line class="zero" x1="' + sx(0) + '" x2="' + sx(0) + '" y1="' + m.t + '" y2="' + (H - m.b) + '"/>';
    gs.forEach(function (g, i) {
      var cy = m.t + i * rowH + rowH / 2, b = st.box(g.values);
      s += '<text class="rl" x="' + (m.l - 12) + '" y="' + (cy + 4) + '" text-anchor="end">' + esc(g.label) + '</text><text class="rn" x="' + (m.l - 12) + '" y="' + (cy + 18) + '" text-anchor="end">' + b.n + ' tests</text>';
      s += '<line stroke="' + g.color + '" stroke-opacity=".7" x1="' + sx(b.wLo) + '" x2="' + sx(b.wHi) + '" y1="' + cy + '" y2="' + cy + '"/>' +
        '<rect x="' + sx(b.q1) + '" y="' + (cy - 11) + '" width="' + Math.max(1, sx(b.q3) - sx(b.q1)) + '" height="22" rx="3" fill="' + g.color + '" fill-opacity=".28" stroke="' + g.color + '" data-tip="' + esc(g.label + ': median ' + num(b.median) + ', middle half ' + num(b.q1) + ' to ' + num(b.q3) + ', range ' + num(b.min) + ' to ' + num(b.max) + ', ' + b.n + ' tests') + '"/>' +
        '<line stroke="' + g.color + '" stroke-width="3" x1="' + sx(b.median) + '" x2="' + sx(b.median) + '" y1="' + (cy - 11) + '" y2="' + (cy + 11) + '"/>';
      (g.pts || []).forEach(function (p, k) {
        s += '<circle class="pt' + (p.id === o.selected ? ' sel' : '') + '" cx="' + sx(p.y) + '" cy="' + (cy + ((k * 7) % 9 - 4) * 1.6) + '" r="2.6" fill="' + g.color + '" opacity=".75" data-tip="' + esc(p.tip) + '" data-id="' + esc(p.id) + '"/>';
      });
    });
    return s + xAxis(sx, yt, H - m.b, o.xLabel) + '</svg>';
  }

  /* --- median by oxygen band with middle-half bars ----------------------------- */
  function trend(o) {
    var live = o.series.filter(function (s) { return s.pts.length; });
    if (!live.length) return empty('No bands have enough tests for the current filters.', 200);
    var m = { l: 76, r: 20, t: 20, b: 52 }, H = 360, all = [];
    live.forEach(function (s) { s.pts.forEach(function (p) { all.push(p.q1, p.q3, p.median); }); });
    var xt = st.ticks(o.xDomain[0], o.xDomain[1], 6), yt = st.ticks(Math.min(0, Math.min.apply(null, all)), Math.max.apply(null, all), 6);
    var sx = lin(xt[0], xt[xt.length - 1], m.l, W - m.r), sy = lin(yt[0], yt[yt.length - 1], H - m.b, m.t);
    var s = svgOpen(H, o.label) + untested(sx, o.untestedFrom, xt[xt.length - 1], m.t, H - m.b) + gridY(sy, yt, m.l, W - m.r);
    live.forEach(function (ser, si) {
      var off = (si - (live.length - 1) / 2) * 5;
      var solid = ser.pts.filter(function (p) { return p.n >= o.minN; });
      if (solid.length > 1) s += '<polyline fill="none" stroke="' + ser.color + '" stroke-width="2" stroke-opacity=".7" points="' + solid.map(function (p) { return (sx(p.x) + off) + ',' + sy(p.median); }).join(' ') + '"/>';
      ser.pts.forEach(function (p) {
        var ok = p.n >= o.minN, x = sx(p.x) + off;
        var tip = ser.label + ', oxygen ' + p.lo + ' to ' + p.hi + '%: median ' + num(p.median) + ', middle half ' + num(p.q1) + ' to ' + num(p.q3) + ', ' + p.n + ' tests' + (ok ? '' : ' (too few to trust)');
        s += '<line stroke="' + ser.color + '" stroke-opacity="' + (ok ? .8 : .35) + '" x1="' + x + '" x2="' + x + '" y1="' + sy(p.q1) + '" y2="' + sy(p.q3) + '"/>' +
          '<circle cx="' + x + '" cy="' + sy(p.median) + '" r="' + (ok ? 5.2 : 4) + '" fill="' + (ok ? ser.color : 'var(--panel)') + '" stroke="' + ser.color + '" stroke-width="1.6" data-tip="' + esc(tip) + '"/>';
      });
    });
    if (o.userX != null && o.userX >= xt[0] && o.userX <= xt[xt.length - 1]) s += userLine(sx, o.userX, m.t, H - m.b, o.userLabel);
    return s + xAxis(sx, xt, H - m.b, 'Oxygen in the test chamber (%)') + yAxis(sy, yt, m.l, o.yLabel) + '</svg>';
  }

  /* --- dumbbell: same group, two oxygen ranges --------------------------------- */
  function dumbbell(o) {
    var rows = o.rows.filter(function (r) { return r.a.n || r.b.n; });
    if (!rows.length) return empty('Neither range has tests for the current filters.', 140);
    var rowH = 44, m = { l: 150, r: 110, t: 24, b: 52 }, H = m.t + m.b + rows.length * rowH, all = [];
    rows.forEach(function (r) { if (r.a.n) all.push(r.a.median); if (r.b.n) all.push(r.b.median); });
    var yt = st.ticks(Math.min(0, Math.min.apply(null, all)), Math.max.apply(null, all), 6), sx = lin(yt[0], yt[yt.length - 1], m.l, W - m.r);
    var s = svgOpen(H, o.label) + gridX(sx, yt, m.t, H - m.b);
    s += '<circle cx="' + (m.l) + '" cy="10" r="5" fill="var(--cream)"/><text class="tl" x="' + (m.l + 10) + '" y="14">' + esc(o.labelA) + '</text><circle cx="' + (m.l + 190) + '" cy="10" r="5" fill="none" stroke="var(--cream)" stroke-width="2"/><text class="tl" x="' + (m.l + 200) + '" y="14">' + esc(o.labelB) + '</text>';
    rows.forEach(function (r, i) {
      var cy = m.t + i * rowH + rowH / 2;
      s += '<text class="rl" x="' + (m.l - 12) + '" y="' + (cy + 4) + '" text-anchor="end">' + esc(r.label) + '</text>';
      if (r.a.n && r.b.n) s += '<line stroke="' + r.color + '" stroke-opacity=".6" stroke-width="3" x1="' + sx(r.a.median) + '" x2="' + sx(r.b.median) + '" y1="' + cy + '" y2="' + cy + '"/>';
      if (r.a.n) s += '<circle cx="' + sx(r.a.median) + '" cy="' + cy + '" r="7" fill="' + r.color + '" data-tip="' + esc(r.label + ', ' + o.labelA + ': median ' + num(r.a.median) + ' over ' + r.a.n + ' tests') + '"/>';
      if (r.b.n) s += '<circle cx="' + sx(r.b.median) + '" cy="' + cy + '" r="7" fill="var(--panel)" stroke="' + r.color + '" stroke-width="2.4" data-tip="' + esc(r.label + ', ' + o.labelB + ': median ' + num(r.b.median) + ' over ' + r.b.n + ' tests') + '"/>';
      s += '<text class="rn" x="' + (W - 2) + '" y="' + (cy + 4) + '" text-anchor="end">tests ' + r.a.n + ' and ' + r.b.n + '</text>';
    });
    return s + xAxis(sx, yt, H - m.b, o.xLabel) + '</svg>';
  }

  /* --- coverage heatmap: tests per group and oxygen band ------------------------- */
  function heatmap(o) {
    var rows = o.rows, cols = o.cols, rowH = 34, m = { l: 150, r: 24, t: 38, b: 38 }, H = m.t + m.b + rows.length * rowH;
    var cw = (W - m.l - m.r) / cols.length, max = 1;
    rows.forEach(function (r) { r.counts.forEach(function (c) { if (c > max) max = c; }); });
    var s = svgOpen(H, o.label);
    cols.forEach(function (c, j) {
      var x = m.l + j * cw, un = o.untestedFrom != null && c.lo >= o.untestedFrom;
      s += '<text class="tl" x="' + (x + cw / 2) + '" y="' + (m.t - 10) + '" text-anchor="middle" ' + (un ? 'fill="var(--amber)"' : '') + '>' + c.lo + '</text>';
    });
    s += '<text class="al" x="' + m.l + '" y="12">Oxygen band starts at (%)</text>';
    rows.forEach(function (r, i) {
      var y = m.t + i * rowH;
      s += '<text class="rl" x="' + (m.l - 12) + '" y="' + (y + rowH / 2 + 4) + '" text-anchor="end">' + esc(r.label) + '</text>';
      r.counts.forEach(function (c, j) {
        var x = m.l + j * cw, un = o.untestedFrom != null && cols[j].lo >= o.untestedFrom, a = c ? 0.18 + 0.82 * c / max : 0;
        s += '<rect x="' + (x + 1.5) + '" y="' + (y + 1.5) + '" width="' + (cw - 3) + '" height="' + (rowH - 3) + '" rx="3" ' +
          (c ? 'fill="' + r.color + '" fill-opacity="' + a.toFixed(2) + '"' : 'fill="' + (un ? 'var(--gap)' : 'none') + '" stroke="var(--line)" stroke-dasharray="3 3"') +
          ' data-tip="' + esc(r.label + ', oxygen ' + cols[j].lo + ' to ' + cols[j].hi + '%: ' + c + ' tests') + '"/>';
        if (c) s += '<text class="cell" x="' + (x + cw / 2) + '" y="' + (y + rowH / 2 + 4) + '" text-anchor="middle">' + c + '</text>';
      });
    });
    if (o.userX != null) {
      var j = cols.findIndex(function (c) { return o.userX >= c.lo && o.userX < c.hi; });
      if (j >= 0) s += '<rect class="mebox" x="' + (m.l + j * cw) + '" y="' + (m.t - 2) + '" width="' + cw + '" height="' + (rows.length * rowH + 4) + '" rx="4"/>';
    }
    return s + '</svg>';
  }

  /* --- evidence strip for one row (same idea as the first version) --------------- */
  function strip(g, o) {
    var Wd = 440, Hd = 40, x = function (v) { return (Math.min(40, Math.max(10, v)) - 10) / 30 * Wd; };
    var s = '<svg class="strip" viewBox="0 0 ' + Wd + ' ' + Hd + '" role="img" aria-label="' + esc(g.label) + ' tests along the oxygen axis">';
    if (o.untestedFrom != null) s += '<rect class="gap" x="' + x(o.untestedFrom) + '" y="0" width="' + (Wd - x(o.untestedFrom)) + '" height="' + Hd + '"/>';
    s += '<line class="axl" x1="0" x2="' + Wd + '" y1="' + Hd / 2 + '" y2="' + Hd / 2 + '"/>';
    g.tests.forEach(function (t, i) {
      var y = Hd / 2 - 9 + (i * 7 % 5) * 4.5, sel = t.__id === o.selected;
      s += '<circle class="pt' + (sel ? ' sel' : '') + '" cx="' + x(t.o2) + '" cy="' + y + '" r="' + (sel ? 5.5 : 3.2) + '" fill="' + g.color + '" opacity=".8" data-tip="' + esc(t.__tip) + '" data-id="' + esc(t.__id) + '"/>';
    });
    return s + '<line class="me" x1="' + x(o.userX) + '" x2="' + x(o.userX) + '" y1="0" y2="' + Hd + '"/></svg>';
  }
  function stripAxis(untestedFrom) {
    var Wd = 440, x = function (v) { return (v - 10) / 30 * Wd; }, s = '<svg class="strip" style="height:26px" viewBox="0 0 ' + Wd + ' 26" role="img" aria-label="Oxygen axis">';
    if (untestedFrom != null) s += '<rect class="gap" x="' + x(untestedFrom) + '" y="0" width="' + (Wd - x(untestedFrom)) + '" height="26"/>';
    for (var t = 10; t <= 40; t += 5) s += '<text class="tl" x="' + x(t) + '" y="11" text-anchor="' + (t === 10 ? 'start' : t === 40 ? 'end' : 'middle') + '">' + t + '%</text><line class="tick" x1="' + x(t) + '" x2="' + x(t) + '" y1="17" y2="26"/>';
    return s + '</svg>';
  }


  /* --- stacked outcome bars: one row per condition, one segment per outcome ------- */
  var OUT_COL = { Extinction: '#2b7ea1', Disruption: '#8a5a7a', Completion: '#5f7a4a', 'Not reported': '#6c7682' };
  function outcomeBars(o) {
    var rows = o.rows.filter(function (r) { return r.n; });
    if (!rows.length) return empty('No tests match these settings.', 140);
    var rowH = 46, m = { l: 190, r: 90, t: 8, b: 10 }, H = m.t + m.b + rows.length * rowH, bw = W - m.l - m.r;
    var s = svgOpen(H, o.label);
    rows.forEach(function (r, i) {
      var y = m.t + i * rowH, x = m.l;
      s += '<text class="rl" x="' + (m.l - 12) + '" y="' + (y + 22) + '" text-anchor="end">' + esc(r.label) + '</text>' + (r.sub ? '<text class="rn" x="' + (m.l - 12) + '" y="' + (y + 37) + '" text-anchor="end">' + esc(r.sub) + '</text>' : '');
      r.parts.forEach(function (p) {
        var w = bw * p.share, pct = Math.round(p.share * 100);
        s += '<rect x="' + x + '" y="' + (y + 8) + '" width="' + Math.max(0, w - 2) + '" height="28" rx="3" fill="' + (OUT_COL[p.name] || '#6c7682') + '" data-tip="' + esc(r.label + ', ' + p.name + ': ' + p.n + ' of ' + r.n + ' tests (' + pct + '%)') + '"/>';
        if (w > 120) s += '<text class="bl" x="' + (x + 8) + '" y="' + (y + 27) + '">' + esc(p.name) + ' ' + pct + '%</text>';
        else if (w > 38) s += '<text class="bl" x="' + (x + 8) + '" y="' + (y + 27) + '">' + pct + '%</text>';
        x += w;
      });
      s += '<text class="rn" x="' + (W - 2) + '" y="' + (y + 27) + '" text-anchor="end">' + r.n + (r.n === 1 ? ' test' : ' tests') + '</text>';
    });
    return s + '</svg>';
  }
  root.FF.outcomeColors = OUT_COL;

  root.FF.charts = { outcomeBars: outcomeBars, scatter: scatter, boxplot: boxplot, trend: trend, dumbbell: dumbbell, heatmap: heatmap, strip: strip, stripAxis: stripAxis, esc: esc, num: num };
})(window);
