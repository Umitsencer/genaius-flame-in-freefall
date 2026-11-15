/* Material lab: PSI-25 (BASS-II) descriptive evidence explorer wired to /api/analytics/materials, /api/detail, and /api/export. */
(function () {
  'use strict';
  var lib = FF.lib, st = FF.stats, ch = FF.charts, esc = ch.esc, num = ch.num;
  var COLORS = ['#3a88a8', '#c9783e', '#5ca084', '#a86b99', '#8a9950', '#c46468', '#6882b8', '#b08e52'];

  var METRIC = {
    d_co: { apiKey: 'delta_co_ppm', runKey: 'delta_co_ppm', statusKey: 'delta_co_status', exportField: 'final_co_ppm', exportUnit: 'ppm', name: 'CO change', unit: 'ppm', label: 'CO change (ppm, final minus initial)', medLabel: 'Median CO change (ppm, final minus initial)' },
    d_o2: { apiKey: 'delta_o2_vol_pct', runKey: 'delta_o2_vol_pct', statusKey: 'delta_o2_status', exportField: 'final_o2_vol_pct', exportUnit: '% vol', name: 'Oxygen change', unit: 'vol%', label: 'Oxygen change (vol%, final minus initial)', medLabel: 'Median Oxygen change (vol%, final minus initial)' },
    d_co2: { apiKey: 'delta_co2_vol_pct', runKey: 'delta_co2_vol_pct', statusKey: 'delta_co2_status', exportField: 'final_co2_vol_pct', exportUnit: '% vol', name: 'CO₂ change', unit: 'vol%', label: 'CO₂ change (vol%, final minus initial)', medLabel: 'Median CO₂ change (vol%, final minus initial)' }
  };

  var AXIS = {
    o2v: { runKey: 'o2_pct', label: 'Starting oxygen (%)', unit: '%' },
    d_co: { runKey: 'delta_co_ppm', statusKey: 'delta_co_status', label: 'CO change (ppm, final minus initial)', unit: 'ppm' },
    d_o2: { runKey: 'delta_o2_vol_pct', statusKey: 'delta_o2_status', label: 'Oxygen change (vol%, final minus initial)', unit: 'vol%' },
    d_co2: { runKey: 'delta_co2_vol_pct', statusKey: 'delta_co2_status', label: 'CO₂ change (vol%, final minus initial)', unit: 'vol%' }
  };

  var $ = function (id) { return document.getElementById(id); };
  var S = {
    o2: 21,
    win: 3,
    preset: 'iss',
    metric: 'd_co',
    group: 'mat',
    aggMode: 'per_run',
    mats: [],
    allMats: [],
    restr: 'any',
    pi: 'any',
    pisPopulated: false,
    sx: 'o2v',
    sy: 'd_co',
    colorby: 'group',
    bands: true,
    onlyWin: false,
    bw: 3,
    ra: [15, 19],
    rb: [20, 24],
    sort: 'o2_pct',
    dir: 1,
    pick: null,
    hidden: {},
    data: null,
    error: null,
    loading: false,
    seq: 0,
    ctrl: null
  };

  var share = FF.api.makeShare(
    {
      o2: ['n', 21], win: ['n', 3], preset: ['s', 'iss'], metric: ['s', 'd_co'], group: ['s', 'mat'],
      aggMode: ['s', 'per_run'], mats: ['a', []], restr: ['s', 'any'], pi: ['s', 'any'],
      sx: ['s', 'o2v'], sy: ['s', 'd_co'], colorby: ['s', 'group'], bands: ['b', true],
      onlyWin: ['b', false], bw: ['n', 3], ra: ['a', [15, 19]], rb: ['a', [20, 24]]
    },
    function () { return S; },
    function (d) { Object.assign(S, d); }
  );

  var tipEl = $('tip');
  document.addEventListener('mouseover', function (e) {
    var t = e.target.closest && e.target.closest('[data-tip]');
    if (!t) { tipEl.hidden = true; return; }
    tipEl.textContent = t.dataset.tip;
    tipEl.hidden = false;
  });
  document.addEventListener('mousemove', function (e) {
    if (!tipEl.hidden) {
      tipEl.style.left = Math.min(window.innerWidth - 330, e.clientX + 14) + 'px';
      tipEl.style.top = (e.clientY + 14) + 'px';
    }
  });
  document.addEventListener('mouseout', function (e) {
    if (e.target.closest && e.target.closest('[data-tip]')) tipEl.hidden = true;
  });

  function statusTag(stCode) {
    if (!stCode || stCode === 'measured') return '';
    if (stCode === 'above_limit') return 'OR (>1000 ppm)';
    return stCode.replace(/_/g, ' ');
  }

  function runValue(r, axisKey) {
    var a = AXIS[axisKey];
    if (!a) return null;
    if (a.statusKey && r[a.statusKey] !== 'measured') return null;
    return r[a.runKey];
  }

  function formatMetricWithUnit(val, metricKey) {
    if (val == null) return '—';
    return num(val, 2) + ' ' + METRIC[metricKey].unit;
  }

  function buildPayload() {
    return {
      target_o2_pct: S.o2,
      window_pct: S.win,
      metric: METRIC[S.metric].apiKey,
      group_by: S.group === 'shape' ? 'material_shape' : 'material_family',
      flow_restrictor: S.restr === 'any' ? null : parseInt(S.restr, 10),
      pi: S.pi === 'any' ? null : S.pi,
      materials: (S.allMats.length && S.mats.length === S.allMats.length) ? null : (S.mats.length ? S.mats.slice() : null),
      dedupe_samples: S.aggMode === 'unique_sample_median'
    };
  }

  function fetchMaterials() {
    if (!FF.api || typeof FF.api.analyticsMaterials !== 'function') {
      S.error = 'Backend API client not available.';
      drawAll();
      return;
    }
    var seq = ++S.seq;
    if (S.ctrl && typeof S.ctrl.abort === 'function') S.ctrl.abort();
    S.ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    S.loading = true;
    S.error = null;
    drawAll();
    FF.api.analyticsMaterials(buildPayload(), S.ctrl ? { signal: S.ctrl.signal } : undefined).then(function (env) {
      if (seq !== S.seq) return;
      S.loading = false;
      S.error = null;
      S.data = env && env.data ? env.data : null;
      if (FF.chat && typeof FF.chat.setContext === 'function') {
        var o2Low = Math.max(0, Number((S.o2 - S.win).toFixed(4)));
        var o2High = Math.min(100, Number((S.o2 + S.win).toFixed(4)));
        var labCtx = {
          investigation_id: 'PSI-25',
          numeric_filters: [
            { field_name: 'initial_o2_vol_pct', unit: '% vol', min_value: o2Low, max_value: o2High }
          ],
          uiLabel: 'Material Lab (PSI-25 · ' + S.o2 + '% O₂ ±' + S.win + '%)'
        };
        if (S.mats.length === 1 && S.allMats.length > 1) {
          labCtx.fuel = S.mats[0];
        }
        FF.chat.setContext(labCtx, { clearOnChange: false });
      }
      syncAvailableFilters(S.data);
      drawAll();
    }).catch(function (err) {
      if (err && err.name === 'AbortError') return;
      if (seq !== S.seq) return;
      S.loading = false;
      S.error = (err && err.message) ? err.message : 'Unable to reach /api/analytics/materials.';
      drawAll();
    });
  }

  function syncAvailableFilters(d) {
    if (!d || !d.available_filters) return;
    var avail = d.available_filters;
    if (!S.allMats.length && Array.isArray(avail.materials)) {
      S.allMats = avail.materials.slice();
      if (!S.mats.length) S.mats = S.allMats.slice();
      $('f-mat').innerHTML = S.allMats.map(function (m) {
        var checked = S.mats.indexOf(m) >= 0 ? ' checked' : '';
        return '<label class="chk"><input type="checkbox" value="' + esc(m) + '"' + checked + '> ' + esc(m) + '</label>';
      }).join('');
      Array.prototype.forEach.call($('f-mat').querySelectorAll('input'), function (inp) {
        inp.addEventListener('change', function () {
          S.mats = Array.prototype.map.call($('f-mat').querySelectorAll('input:checked'), function (el) { return el.value; });
          S.pick = null;
          fetchMaterials();
        });
      });
    }
    if (!S.pisPopulated && Array.isArray(avail.pis)) {
      S.pisPopulated = true;
      $('f-pi').innerHTML = '<option value="any">Any</option>' + avail.pis.map(function (pi) {
        return '<option value="' + esc(pi) + '">' + esc(pi) + '</option>';
      }).join('');
      $('f-pi').value = S.pi;
    }
  }

  function syncInputs() {
    $('o2').value = S.o2;
    $('o2-out').textContent = S.o2 + '%';
    $('preset').value = S.preset;
    var pr = lib.PRESETS.filter(function (x) { return x.id === S.preset; })[0];
    $('preset-note').textContent = pr ? pr.note : '';
    $('win').value = String(S.win);
    $('metric').value = S.metric;
    $('group').value = S.group;
    $('agg-mode').value = S.aggMode;
    $('f-restr').value = S.restr;
    if (S.pisPopulated) $('f-pi').value = S.pi;
    $('sx').value = S.sx;
    $('sy').value = S.sy;
    $('colorby').value = S.colorby;
    $('sc-bands').checked = S.bands;
    $('only-win').checked = S.onlyWin;
    Array.prototype.forEach.call($('f-mat').querySelectorAll('input'), function (inp) {
      inp.checked = S.mats.indexOf(inp.value) >= 0;
    });
  }

  function enrichRuns(runs, groups) {
    var colorMap = {};
    (groups || []).forEach(function (g, i) { colorMap[g.label] = COLORS[i % COLORS.length]; });
    return (runs || []).map(function (r) {
      var col = colorMap[r.group_label] || '#3a88a8';
      var coTxt = r.delta_co_status === 'measured'
        ? 'CO change ' + num(r.delta_co_ppm, 1) + ' ppm'
        : 'CO excluded (' + statusTag(r.delta_co_status) + ')';
      var tip = r.test_id + ' · ' + r.fuel_norm + ' (O₂ ' + (r.o2_pct != null ? r.o2_pct + '%' : '—') +
        ', ' + coTxt + ', O₂ change ' + num(r.delta_o2_vol_pct, 2) + ' vol%)';
      return Object.assign({}, r, { o2: r.o2_pct, __id: r.record_pk, __tip: tip, __col: col });
    });
  }

  function buildGroupBuckets(d, runs) {
    var byLabel = {};
    runs.forEach(function (r) {
      var k = r.group_label;
      if (!byLabel[k]) byLabel[k] = [];
      byLabel[k].push(r);
    });
    return (d.groups || []).map(function (g, i) {
      return {
        label: g.label,
        color: COLORS[i % COLORS.length],
        meta: g,
        tests: byLabel[g.label] || []
      };
    });
  }

  function drawHeader(d) {
    var m = METRIC[S.metric];
    var excl = d.excluded_by_reason || {};
    var exclParts = [];
    if (excl.paired_excluded_above_limit) exclParts.push(excl.paired_excluded_above_limit + ' above sensor limit (>1000 ppm OR)');
    if (excl.paired_excluded_invalid) exclParts.push(excl.paired_excluded_invalid + ' negative invalid CO');
    if (excl.paired_excluded_missing) exclParts.push(excl.paired_excluded_missing + ' missing endpoint');

    $('ov').innerHTML =
      '<span><b>' + d.total_runs + '</b>PSI-25 runs (' + d.unique_sample_count + ' unique Sample #)</span>' +
      '<span><b>' + d.used_count + '</b>paired ' + esc(m.name) + ' used</span>' +
      '<span><b>' + d.excluded_count + '</b>excluded from ' + esc(m.name) + '</span>' +
      '<span><b>' + d.min_tested_o2_pct + '%–' + d.max_tested_o2_pct + '%</b>tested O₂ range</span>';

    var callout = $('callout');
    if (d.beyond_tested_range) {
      callout.className = 'callout gap';
      callout.innerHTML = '<strong>Evidence gap at ' + S.o2 + '% O₂:</strong> The highest tested PSI-25 oxygen level is <strong>' +
        d.max_tested_o2_pct + '%</strong>. Nothing here was tested at 34% O₂ or exploration cabin levels — charts show nearest evidence only.';
    } else {
      callout.className = 'callout';
      callout.innerHTML = '<strong>' + S.o2 + '% O₂</strong> (window ±' + S.win + ' pts) · Aggregation: <strong>' +
        esc(d.aggregation_mode === 'unique_sample_median' ? 'Unique Sample # median' : 'Per test run') +
        '</strong>. Condition comparison only — not a flammability or safety ranking.';
    }

    var covEl = $('lab-cov');
    if (!covEl && callout && callout.parentNode) {
      covEl = document.createElement('div');
      covEl.id = 'lab-cov';
      callout.parentNode.insertBefore(covEl, callout.nextSibling);
    }
    if (covEl && d.coverage && FF.api && typeof FF.api.renderCoverageCard === 'function') {
      covEl.innerHTML = FF.api.renderCoverageCard(d.coverage, { title: 'PSI-25 Material Lab' });
    }

    $('note-over').textContent = (exclParts.length ? 'Excluded from active metric without zero-coercion: ' + exclParts.join(' · ') + '. ' : '') +
      (d.boundary_note || '');
  }

  function drawMap(d, groups) {
    var m = METRIC[S.metric];
    var hdr = '<div class="map-hdr"><div>Group</div><div>' + d.min_tested_o2_pct + '%–' + d.max_tested_o2_pct +
      '% tested O₂ strip (red = ' + S.o2 + '%, amber = untested)</div><div>Near median (' + esc(m.unit) + ') · Condition comparison only</div></div>';
    var rows = groups.map(function (g) {
      var meta = g.meta;
      var med = meta.near_stats && meta.near_stats.median != null ? num(meta.near_stats.median, 2) + ' ' + m.unit : '—';
      var sub = meta.run_count + ' runs (' + meta.unique_sample_count + ' samples) · ' +
        (meta.near_used_count ? meta.near_used_count + ' near used' : '0 near within ±' + S.win + ' pts');
      return '<div class="map-row">' +
        '<div><strong>' + esc(g.label) + '</strong><span class="sub">' + esc(sub) + '</span></div>' +
        '<div>' + ch.strip({ label: g.label, color: g.color, tests: g.tests }, { untestedFrom: d.max_tested_o2_pct + 0.1, userX: S.o2, selected: S.pick }) + '</div>' +
        '<div class="med">' + esc(med) + '</div></div>';
    }).join('');
    $('map').innerHTML = hdr + rows + '<div class="map-row"><div></div><div>' + ch.stripAxis(d.max_tested_o2_pct + 0.1) + '</div><div></div></div>';
  }

  function drawScatter(d, groups, runs) {
    var ax = AXIS[S.sx], ay = AXIS[S.sy];
    var colorGroups = [];
    if (S.colorby === 'group') {
      colorGroups = groups.map(function (g) { return { key: g.label, label: g.label, color: g.color }; });
    } else if (S.colorby === 'pi') {
      var pis = [];
      runs.forEach(function (r) { if (r.pi && pis.indexOf(r.pi) < 0) pis.push(r.pi); });
      colorGroups = pis.sort().map(function (pi, i) { return { key: pi, label: pi, color: COLORS[i % COLORS.length] }; });
    } else {
      colorGroups = [
        { key: '0', label: 'Restriction 0', color: COLORS[0] },
        { key: '1', label: 'Restriction 1', color: COLORS[1] },
        { key: '2', label: 'Restriction 2', color: COLORS[2] }
      ];
    }
    var cmap = {};
    colorGroups.forEach(function (c) { cmap[c.key] = c.color; });
    $('legend').innerHTML = colorGroups.map(function (c) {
      var off = S.hidden[c.key] ? ' off' : '';
      return '<button type="button" class="lg' + off + '" data-k="' + esc(c.key) + '"><i style="background:' + c.color + '"></i>' + esc(c.label) + '</button>';
    }).join('');

    var pts = [];
    runs.forEach(function (r) {
      var ck = S.colorby === 'group' ? r.group_label : (S.colorby === 'pi' ? (r.pi || '—') : String(r.flow_restrictor));
      if (S.hidden[ck]) return;
      var xv = runValue(r, S.sx), yv = runValue(r, S.sy);
      if (xv == null || yv == null) return;
      pts.push({ id: r.__id, x: xv, y: yv, color: cmap[ck] || '#3a88a8', tip: r.__tip });
    });

    var lines = [];
    if (S.bands && S.sx === 'o2v') {
      groups.forEach(function (g) {
        if (S.colorby === 'group' && S.hidden[g.label]) return;
        var bins = {};
        g.tests.forEach(function (r) {
          var xv = r.o2_pct, yv = runValue(r, S.sy);
          if (xv == null || yv == null) return;
          var lo = Math.floor(xv / S.bw) * S.bw;
          if (!bins[lo]) bins[lo] = [];
          bins[lo].push(yv);
        });
        var lpts = Object.keys(bins).map(Number).sort(function (a, b) { return a - b; })
          .filter(function (lo) { return bins[lo].length >= 2; })
          .map(function (lo) { return [lo + S.bw / 2, st.median(bins[lo])]; });
        if (lpts.length >= 2) lines.push({ color: g.color, pts: lpts });
      });
    }

    $('scatter').innerHTML = ch.scatter({
      points: pts,
      lines: lines,
      selected: S.pick,
      xDomain: S.sx === 'o2v' ? [12, Math.max(25, S.o2 + 2)] : null,
      untestedFrom: S.sx === 'o2v' ? d.max_tested_o2_pct + 0.1 : null,
      userX: S.sx === 'o2v' ? S.o2 : null,
      userLabel: S.sx === 'o2v' ? S.o2 + '% O₂' : null,
      xLabel: ax.label,
      yLabel: ay.label,
      label: ay.label + ' against ' + ax.label
    });

    var correlation = st.spearman(pts.map(function (p) { return p.x; }), pts.map(function (p) { return p.y; }));
    var rho = correlation.rho;
    $('sc-stat').textContent = rho != null
      ? 'Spearman rank correlation over ' + correlation.n + ' paired points: ' + num(rho, 2) + '. Descriptive only — sample sizes, airflow, and shapes vary across tests.'
      : 'Too few paired measured points to compute rank correlation.';
  }

  function drawSpread(d, groups) {
    var m = METRIC[S.metric];
    var boxGroups = groups.map(function (g) {
      var vals = [], pts = [];
      g.tests.forEach(function (r) {
        if (S.onlyWin && (r.o2_pct == null || Math.abs(r.o2_pct - S.o2) > S.win)) return;
        if (r.selected_status !== 'measured' || r.selected_value == null) return;
        vals.push(r.selected_value);
        pts.push({ id: r.__id, y: r.selected_value, tip: r.__tip });
      });
      return { label: g.label, color: g.color, values: vals, pts: pts };
    });
    $('spread').innerHTML = ch.boxplot({ groups: boxGroups, selected: S.pick, xLabel: m.label, label: m.name + ' by group' });

  }

  function drawCompareAndCoverage(d, groups) {
    var m = METRIC[S.metric];
    var rows = groups.map(function (g) {
      var aVals = [], bVals = [];
      g.tests.forEach(function (r) {
        if (r.o2_pct == null || r.selected_status !== 'measured' || r.selected_value == null) return;
        if (r.o2_pct >= S.ra[0] && r.o2_pct <= S.ra[1]) aVals.push(r.selected_value);
        if (r.o2_pct >= S.rb[0] && r.o2_pct <= S.rb[1]) bVals.push(r.selected_value);
      });
      return {
        label: g.label,
        color: g.color,
        a: { n: aVals.length, median: aVals.length ? st.median(aVals) : null },
        b: { n: bVals.length, median: bVals.length ? st.median(bVals) : null }
      };
    });
    $('compare').innerHTML = ch.dumbbell({
      rows: rows,
      labelA: S.ra[0] + '–' + S.ra[1] + '% O₂',
      labelB: S.rb[0] + '–' + S.rb[1] + '% O₂',
      xLabel: m.medLabel,
      label: 'Median ' + m.name + ' across two oxygen ranges'
    });
    var both3 = rows.filter(function (r) { return r.a.n >= 3 && r.b.n >= 3; }).length;
    $('cmp-note').textContent = both3
      ? both3 + ' group(s) have at least 3 paired readings in both ranges.'
      : 'No group has at least 3 paired readings in both ranges; widen or shift the ranges.';

    var cols = [];
    for (var lo = 12; lo <= 34; lo += 2) cols.push({ lo: lo, hi: lo + 2 });
    var covRows = groups.map(function (g) {
      return {
        label: g.label,
        color: g.color,
        counts: cols.map(function (c) {
          return g.tests.filter(function (r) { return r.o2_pct != null && r.o2_pct >= c.lo && r.o2_pct < c.hi; }).length;
        })
      };
    });
    $('coverage').innerHTML = ch.heatmap({ rows: covRows, cols: cols, untestedFrom: d.max_tested_o2_pct + 0.1, userX: S.o2, label: 'Number of PSI-25 runs by group and 2% oxygen band' });
  }

  function drawStatsAndTests(d, groups, runs) {
    var m = METRIC[S.metric];
    var statRows = groups.map(function (g) {
      var xs = [], ys = [], allVals = [];
      g.tests.forEach(function (r) {
        if (r.selected_status === 'measured' && r.selected_value != null) {
          allVals.push(r.selected_value);
          if (r.o2_pct != null) { xs.push(r.o2_pct); ys.push(r.selected_value); }
        }
      });
      var b = allVals.length ? st.box(allVals) : null;
      var rho = xs.length >= 4 ? st.spearman(xs, ys).rho : null;
      return '<tr><td>' + esc(g.label) + '</td><td class="n">' + g.meta.run_count + ' (' + g.meta.all_used_count + ' used)</td>' +
        '<td class="n">' + (g.meta.all_stats ? num(g.meta.all_stats.mean, 2) : '—') + '</td>' +
        '<td class="n">' + (b ? num(b.median, 2) : '—') + '</td>' +
        '<td class="n">' + (b ? num(b.q1, 2) + '–' + num(b.q3, 2) : '—') + '</td>' +
        '<td class="n">' + (b ? num(b.min, 2) : '—') + '</td>' +
        '<td class="n">' + (b ? num(b.max, 2) : '—') + '</td>' +
        '<td class="n">' + (rho != null ? num(rho, 2) : '—') + '</td></tr>';
    }).join('');
    $('stats').innerHTML = '<table class="dt"><thead><tr><th>Group</th><th class="n">Runs (used)</th><th class="n">Mean</th><th class="n">Median</th><th class="n">Middle half</th><th class="n">Lowest</th><th class="n">Highest</th><th class="n">Spearman r with O₂</th></tr></thead><tbody>' + statRows + '</tbody></table>';

    var sorted = runs.slice().sort(function (a, b) {
      var av = a[S.sort], bv = b[S.sort];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return typeof av === 'string' ? av.localeCompare(bv) * S.dir : (av - bv) * S.dir;
    });

    var cols = [
      ['test_id', 'Test', false],
      ['sample_id', 'Sample #', false],
      ['material_family', 'Material', false],
      ['material_shape', 'Shape', false],
      ['pi', 'Investigator', false],
      ['flow_restrictor', 'Restriction', true],
      ['o2_pct', 'Oxygen %', true],
      ['delta_co_ppm', 'CO change ppm', true],
      ['delta_o2_vol_pct', 'O₂ change vol%', true],
      ['delta_co2_vol_pct', 'CO₂ change vol%', true]
    ];
    var thead = cols.map(function (c) {
      var arrow = S.sort === c[0] ? (S.dir > 0 ? ' ▲' : ' ▼') : '';
      return '<th' + (c[2] ? ' class="n"' : '') + ' data-sort="' + c[0] + '">' + esc(c[1] + arrow) + '</th>';
    }).join('');
    var tbody = sorted.map(function (r) {
      var coCell = r.delta_co_status === 'measured' ? esc(num(r.delta_co_ppm, 1)) : '<span class="few">' + esc(statusTag(r.delta_co_status)) + '</span>';
      var o2dCell = r.delta_o2_status === 'measured' ? esc(num(r.delta_o2_vol_pct, 2)) : '<span class="few">' + esc(statusTag(r.delta_o2_status)) + '</span>';
      var co2dCell = r.delta_co2_status === 'measured' ? esc(num(r.delta_co2_vol_pct, 2)) : '<span class="few">' + esc(statusTag(r.delta_co2_status)) + '</span>';
      var sampCell = esc(r.sample_id || '—') + (r.is_repeat_sample ? ' <span class="few">(x' + r.sample_run_count + ')</span>' : '');
      return '<tr data-id="' + esc(r.__id) + '"' + (r.__id === S.pick ? ' class="sel"' : '') + '>' +
        '<td>' + esc(r.test_id) + '</td><td>' + sampCell + '</td><td>' + esc(r.material_family) + '</td>' +
        '<td>' + esc(r.material_shape) + '</td><td>' + esc(r.pi || '—') + '</td>' +
        '<td class="n">' + (r.flow_restrictor != null ? r.flow_restrictor : '—') + '</td>' +
        '<td class="n">' + (r.o2_pct != null ? num(r.o2_pct, 1) : '—') + '</td>' +
        '<td class="n">' + coCell + '</td><td class="n">' + o2dCell + '</td><td class="n">' + co2dCell + '</td></tr>';
    }).join('');
    $('tests').innerHTML = '<table class="dt"><thead><tr>' + thead + '</tr></thead><tbody>' + tbody + '</tbody></table>';
  }

  function drawPicked(runs) {
    var box = $('picked');
    if (!S.pick) { box.hidden = true; box.innerHTML = ''; return; }
    var r = null;
    for (var i = 0; i < runs.length; i++) {
      if (runs[i].__id === S.pick) { r = runs[i]; break; }
    }
    if (!r) { box.hidden = true; box.innerHTML = ''; return; }
    box.hidden = false;
    box.innerHTML =
      '<strong>' + esc(r.record_pk) + ' · ' + esc(r.fuel_norm) + '</strong>' +
      '<span>Sample # ' + esc(r.sample_id || '—') + ' · O₂ ' + (r.o2_pct != null ? r.o2_pct + '%' : '—') +
      ' · CO change: ' + (r.delta_co_status === 'measured' ? esc(formatMetricWithUnit(r.delta_co_ppm, 'd_co')) : esc(statusTag(r.delta_co_status))) + '</span>' +
      '<span>' + esc(r.source_locator && r.source_locator.locator_label ? r.source_locator.locator_label : '') + '</span>' +
      '<a class="lnk" href="data.html?exp=PSI-25&pick=' + encodeURIComponent(r.record_pk) + '#s-explorer">Open row detail &amp; raw fields in Data Explorer ↗</a>' +
      '<button type="button" class="lnk" id="unpick">Clear selection</button>';
    var unpick = box.querySelector('#unpick');
    if (unpick) unpick.addEventListener('click', function () { S.pick = null; drawAll(); });
  }

  function drawAll() {
    syncInputs();
    if (S.error) {
      $('callout').className = 'callout gap';
      $('callout').innerHTML = '<strong>Backend error:</strong> ' + esc(S.error) + ' <button type="button" class="ghost sm" id="lab-retry">Retry</button>';
      var retry = $('callout').querySelector('#lab-retry');
      if (retry) retry.addEventListener('click', fetchMaterials);
      return;
    }
    if (S.loading && !S.data) {
      $('ov').innerHTML = '<span>Loading verified PSI-25 BASS-II records from backend...</span>';
      return;
    }
    var d = S.data;
    if (!d) return;
    var runs = enrichRuns(d.runs, d.groups);
    var groups = buildGroupBuckets(d, runs);
    drawHeader(d);
    drawMap(d, groups);
    drawScatter(d, groups, runs);
    drawSpread(d, groups);
    drawCompareAndCoverage(d, groups);
    drawStatsAndTests(d, groups, runs);
    drawPicked(runs);
    share.write();
  }

  function exportFiltered(fmt) {
    if (!FF.api || typeof FF.api.exportAndDownload !== 'function') return;
    var m = METRIC[S.metric];
    var o2Low = Math.max(0, Number((S.o2 - S.win).toFixed(4)));
    var o2High = Math.min(100, Number((S.o2 + S.win).toFixed(4)));
    var req = {
      investigation_id: 'PSI-25',
      field_name: m.exportField,
      unit: m.exportUnit,
      numeric_filters: [
        { field_name: 'initial_o2_vol_pct', unit: '% vol', min_value: o2Low, max_value: o2High }
      ],
      format: fmt
    };
    if (S.mats.length === 1 && S.allMats.length > 1) {
      req.fuel = S.mats[0];
    }
    $('export-msg').textContent = 'Preparing verified PSI-25 ' + fmt.toUpperCase() + ' export (' + o2Low + '–' + o2High + '% O₂)...';
    FF.api.exportAndDownload(req).then(function (env) {
      var d = (env && env.data) || {};
      $('export-msg').textContent = 'Exported ' + (d.total_runs || 0) + ' PSI-25 runs (' + (d.used_in_summary_count || 0) + ' measured ' + m.exportField + ', ' + (d.excluded_count || 0) + ' excluded) -> ' + (d.filename || '');
    }).catch(function (err) {
      $('export-msg').textContent = 'Export failed: ' + ((err && err.message) || 'Unknown error');
    });
  }

  function init() {
    share.read();
    $('preset').innerHTML = lib.PRESETS.map(function (p) { return '<option value="' + esc(p.id) + '">' + esc(p.label) + '</option>'; }).join('');
    $('preset').addEventListener('change', function (e) {
      var pr = lib.PRESETS.filter(function (x) { return x.id === e.target.value; })[0];
      S.preset = pr.id;
      if (pr.id !== 'custom') S.o2 = pr.o2;
      fetchMaterials();
    });
    $('o2').addEventListener('input', function (e) { S.o2 = parseFloat(e.target.value); S.preset = 'custom'; fetchMaterials(); });
    $('win').addEventListener('change', function (e) { S.win = parseFloat(e.target.value); fetchMaterials(); });
    $('metric').addEventListener('change', function (e) { S.metric = e.target.value; fetchMaterials(); });
    $('group').addEventListener('change', function (e) { S.group = e.target.value; fetchMaterials(); });
    $('agg-mode').addEventListener('change', function (e) { S.aggMode = e.target.value; S.pick = null; fetchMaterials(); });
    $('f-restr').addEventListener('change', function (e) { S.restr = e.target.value; S.pick = null; fetchMaterials(); });
    $('f-pi').addEventListener('change', function (e) { S.pi = e.target.value; S.pick = null; fetchMaterials(); });

    $('sx').addEventListener('change', function (e) { S.sx = e.target.value; drawAll(); });
    $('sy').addEventListener('change', function (e) { S.sy = e.target.value; drawAll(); });
    $('colorby').addEventListener('change', function (e) { S.colorby = e.target.value; S.hidden = {}; drawAll(); });
    $('sc-bands').addEventListener('change', function (e) { S.bands = e.target.checked; drawAll(); });
    $('only-win').addEventListener('change', function (e) { S.onlyWin = e.target.checked; drawAll(); });

    var rsA = FF.range($('rs-a'), { min: 13, max: 24, step: 0.5, from: S.ra[0], to: S.ra[1], label: 'First oxygen range (%)', format: function (a, b) { return a + ' to ' + b + '%'; }, onChange: function (a, b) { S.ra = [a, b]; drawAll(); } });
    var rsB = FF.range($('rs-b'), { min: 13, max: 24, step: 0.5, from: S.rb[0], to: S.rb[1], label: 'Second oxygen range (%)', format: function (a, b) { return a + ' to ' + b + '%'; }, onChange: function (a, b) { S.rb = [a, b]; drawAll(); } });

    $('legend').addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('button[data-k]');
      if (!b) return;
      S.hidden[b.dataset.k] = !S.hidden[b.dataset.k];
      drawAll();
    });

    $('main').addEventListener('click', function (e) {
      var th = e.target.closest && e.target.closest('th[data-sort]');
      if (th) {
        var col = th.dataset.sort;
        if (S.sort === col) S.dir = -S.dir;
        else { S.sort = col; S.dir = 1; }
        drawAll();
        return;
      }
      var pt = e.target.closest && e.target.closest('[data-id]');
      if (pt) {
        S.pick = S.pick === pt.dataset.id ? null : pt.dataset.id;
        drawAll();
        return;
      }
      var sv = e.target.closest && e.target.closest('button[data-svg]');
      if (sv) {
        var svgEl = $(sv.dataset.svg).querySelector('svg');
        if (svgEl) FF.api.triggerDownload('material-lab-' + sv.dataset.svg + '.svg', svgEl.outerHTML, 'image/svg+xml;charset=utf-8');
      }
    });

    $('reset').addEventListener('click', function () {
      Object.assign(S, { o2: 21, win: 3, preset: 'iss', metric: 'd_co', group: 'mat', aggMode: 'per_run', mats: S.allMats.slice(), restr: 'any', pi: 'any', sx: 'o2v', sy: 'd_co', colorby: 'group', bands: true, onlyWin: false, bw: 3, ra: [15, 19], rb: [20, 24], pick: null, hidden: {} });
      rsA.set(15, 19);
      rsB.set(20, 24);
      fetchMaterials();
    });
    $('copylink').addEventListener('click', function () { share.copy($('copylink')); });
    $('csv').addEventListener('click', function () { exportFiltered('csv'); });
    $('json').addEventListener('click', function () { exportFiltered('json'); });

    fetchMaterials();
  }

  init();
})();
