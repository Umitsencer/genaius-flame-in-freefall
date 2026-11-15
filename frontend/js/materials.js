/* Material screening view: which materials have test evidence near the chosen oxygen level. */
(function () {
  'use strict';
  var lib = FF.lib, DATA = window.FF_DATA.materials;
  var O2_MIN = 10, O2_MAX = 40, W = 440;
  var el = {};

  function x(o2) { return (Math.min(O2_MAX, Math.max(O2_MIN, o2)) - O2_MIN) / (O2_MAX - O2_MIN) * W; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function signed(v) { return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(Math.round(v)); }

  function axisSvg(maxTested) {
    var s = '<svg class="strip" style="height:30px" viewBox="0 0 ' + W + ' 30" role="img" aria-label="Oxygen axis from ' + O2_MIN + ' to ' + O2_MAX + ' percent">';
    s += '<rect x="' + x(maxTested) + '" y="0" width="' + (W - x(maxTested)) + '" height="30" fill="var(--gap-fill)"/>';
    for (var t = O2_MIN; t <= O2_MAX; t += 5) {
      s += '<text x="' + x(t) + '" y="12" font-size="11" fill="var(--muted)" text-anchor="' + (t === O2_MIN ? 'start' : t === O2_MAX ? 'end' : 'middle') + '">' + t + '%</text>';
      s += '<line x1="' + x(t) + '" x2="' + x(t) + '" y1="20" y2="30" stroke="var(--rule)"/>';
    }
    s += '<text x="' + (x(maxTested) + 6) + '" y="28" font-size="11" fill="var(--gap)">untested above ' + maxTested + '%</text></svg>';
    return s;
  }

  function stripSvg(g, o2, maxTested) {
    var s = '<svg class="strip" viewBox="0 0 ' + W + ' 44" role="img" aria-label="Test oxygen levels for ' + esc(g.name) + '">';
    s += '<rect x="' + x(maxTested) + '" y="0" width="' + (W - x(maxTested)) + '" height="44" fill="var(--gap-fill)" opacity=".55"/>';
    s += '<line x1="0" x2="' + W + '" y1="22" y2="22" stroke="var(--rule)"/>';
    g.tests.forEach(function (t, i) {
      var r = t.o2 != null ? [t.o2, t.o2] : t.o2_range;
      if (!r) return;
      var y = 12 + (i * 7 % 5) * 5;
      if (r[0] !== r[1]) s += '<line x1="' + x(r[0]) + '" x2="' + x(r[1]) + '" y1="' + y + '" y2="' + y + '" stroke="var(--ink)" stroke-width="3" stroke-linecap="round" opacity=".45"/>';
      else s += '<circle cx="' + x(r[0]) + '" cy="' + y + '" r="3" fill="var(--ink)" opacity=".5"/>';
    });
    s += '<line x1="' + x(o2) + '" x2="' + x(o2) + '" y1="0" y2="44" stroke="var(--accent)" stroke-width="2"/></svg>';
    return s;
  }

  function sources(g) { return g.sources.join(', '); }

  function row(g, o2, maxTested, win, i) {
    var near = g.nNear > 0, val;
    if (near && g.coMedian != null) {
      val = '<div class="big">' + signed(g.coMedian) + ' ppm</div><div class="small">median CO change over ' + g.nCo + ' test' + (g.nCo === 1 ? '' : 's') +
        (g.nCoOver ? ', ' + g.nCoOver + ' over range' : '') + '</div>';
    } else if (near) {
      val = '<div class="small">' + g.nNear + ' test' + (g.nNear === 1 ? '' : 's') + ' near this oxygen level, no CO reading</div>';
    } else if (g.nearestDist != null) {
      val = '<div class="none">No test within ' + win + ' points</div><div class="small">Nearest is ' + g.nearestDist.toFixed(1) + ' points away</div>';
    } else {
      val = '<div class="none">No oxygen level recorded</div>';
    }
    var extra = g.nNoConditions ? ' ' + g.nNoConditions + ' more with no oxygen level in the table.' : '';
    var h = '<div class="mrow' + (near ? '' : ' faint') + '"><div><div class="mname">' + esc(g.name) + '</div><div class="msub">' + g.nTotal +
      ' tests in ' + esc(sources(g)) + '.' + extra + '</div></div>' + stripSvg(g, o2, maxTested) + '<div class="mval">' + val + '</div>';
    if (near && g.near.length) {
      h += '<details class="tests"><summary>Show the ' + g.near.length + ' nearby tests</summary><table><thead><tr><th>Test</th><th>Oxygen %</th><th>Oxygen change</th><th>CO change ppm</th></tr></thead><tbody>';
      g.near.slice(0, 80).forEach(function (t) {
        var o = t.o2 != null ? t.o2 : (t.o2_range ? t.o2_range[0] + ' to ' + t.o2_range[1] : '');
        h += '<tr><td>' + esc(t.src + ' ' + t.test) + '</td><td>' + o + '</td><td>' + (t.d_o2 != null ? signed(t.d_o2 * 10) / 10 : '') +
          '</td><td>' + (t.co_over ? 'over range' : t.d_co != null ? signed(t.d_co) : '') + '</td></tr>';
      });
      h += '</tbody></table></details>';
    }
    return h + '</div>';
  }

  function headline(res, env) {
    var n = (env.o2 % 1 ? env.o2.toFixed(1) : env.o2) + '%';
    if (res.beyond) {
      return '<div class="callout gap"><strong>No material here was tested near ' + n + ' oxygen.</strong> The highest oxygen level in these tests is ' + res.maxTestedO2 +
        '%. Anything below is the nearest evidence, not evidence for your conditions.</div>';
    }
    var cands = res.groups.filter(function (g) { return g.nNear > 0 && g.nCo >= 3 && g.coMedian != null; });
    if (!cands.length) return '<div class="callout gap"><strong>Too few gas readings near ' + n + ' oxygen to rank materials.</strong> Rows below show what was tested.</div>';
    var b = cands[0];
    return '<div class="callout"><strong>Lowest CO release near ' + n + ' oxygen: ' + esc(b.name) + '</strong>, a median ' + signed(b.coMedian) + ' ppm over ' + b.nCo +
      ' tests. This orders gas readings only. It does not say a material is safe or fire resistant.</div>';
  }

  var mod = {
    id: 'materials', title: 'Material screening', uses: ['o2'],
    mount: function (root, env) {
      root.innerHTML = '<div class="view-head"><h2>Which materials have been tested near these conditions?</h2>' +
        '<p>Each dot is one NASA test at that oxygen level. Rows are ordered by the carbon monoxide released during the tests nearest your oxygen setting, lowest first.</p></div>' +
        '<div id="m-callout"></div><div class="axis-row"><div></div><div id="m-axis"></div><div></div></div><div id="m-rows"></div>';
      el.callout = root.querySelector('#m-callout'); el.rows = root.querySelector('#m-rows'); el.axis = root.querySelector('#m-axis');
      this.update(env);
    },
    update: function (env) {
      var res = lib.materialEvidence(DATA, { o2: env.o2, win: 3 });
      el.callout.innerHTML = headline(res, env) + (env.g > 0 ? '<p class="msub" style="margin:-10px 0 18px;max-width:66ch">Every test here ran in microgravity. Nothing in them applies directly to ' +
        (env.g < 0.2 ? 'Moon' : env.g < 0.5 ? 'Mars' : 'Earth') + ' gravity.</p>' : '');
      el.axis.innerHTML = axisSvg(res.maxTestedO2);
      el.rows.innerHTML = res.groups.map(function (g, i) { return row(g, env.o2, res.maxTestedO2, res.win, i); }).join('');
    },
    unmount: function () {}
  };
  FF.modules = FF.modules || {};
  FF.modules.materials = mod;
})();
