/* What FLEX measured: interactive PSI-69 exploration wired to POST /api/analytics/flex and /api/export. */
(function () {
  'use strict';
  var ch = FF.charts;
  var esc = ch.esc, num = ch.num;
  var COLORS = FF.outcomeColors || { Extinction: '#2b7ea1', Disruption: '#8a5a7a', Completion: '#5f7a4a', 'Not reported': '#6c7682' };
  var OUTCOMES = ['Extinction', 'Disruption', 'Completion'];
  var YKEY = {
    dExt: { field: 'visible_flame_extinction_diameter_mm', unit: 'mm', label: 'Droplet width at flame-out (mm)', tip: 'droplet width when the flame went out', fmt: function (v) { return v.toFixed(2) + ' mm'; } },
    tBurn: { field: 'burn_time_s', unit: 's', label: 'Burn time (s)', tip: 'burn time', fmt: function (v) { return v.toFixed(1) + ' s'; } },
    rate: { field: 'burning_rate_mm2_s', unit: 'mm²/s', label: 'Burning rate (mm²/s)', tip: 'burning rate', fmt: function (v) { return v.toFixed(2) + ' mm²/s'; } }
  };

  var host = document.getElementById('flex-lab');
  if (!host) return;

  var S = {
    fuel: 'All',
    diluent: 'All',
    o2: [14, 30],
    p: [0.3, 3.1],
    yKey: 'dExt',
    pick: null,
    data: null,
    error: null,
    loading: false,
    exportMsg: '',
    seq: 0,
    ctrl: null
  };

  var el = {}, rsO2, rsP, built = false;

  function build() {
    if (built) return;
    built = true;
    host.innerHTML =
      '<div class="view-head"><h2>What FLEX measured</h2>' +
      '<p>The 274 burning-droplet tests (NASA PSI-69), filtered live via the verified backend. Counts and shares are exact descriptive values over the active subset (no confidence intervals or extrapolations).</p></div>' +
      '<div class="fx-ctl">' +
      '<label>Fuel <select id="fx-fuel"><option value="All">All</option><option value="Methanol">Methanol</option><option value="Heptane">Heptane</option></select></label>' +
      '<label>Diluent <select id="fx-dil"><option value="All">All</option><option value="N2_only">None, nitrogen only</option><option value="CO2">CO₂ added</option><option value="He">Helium added</option></select></label>' +
      '<div class="fx-rs" id="fx-o2"></div><div class="fx-rs" id="fx-p"></div>' +
      '<button type="button" class="ghost" id="fx-reset">Reset</button>' +
      '<button type="button" class="ghost" id="fx-csv">Export CSV</button>' +
      '<button type="button" class="ghost" id="fx-json">Export JSON</button>' +
      '</div>' +
      '<div id="fx-status" aria-live="polite"></div>' +
      '<div class="facts" id="fx-facts"></div>' +
      '<div id="fx-cov"></div>' +
      '<div id="fx-o2p-matrix"></div>' +
      '<p class="small" id="fx-export-msg"></p>' +
      '<h3 class="fx-h">How the tests ended, by oxygen level</h3><p class="how">Each bar is one oxygen band, 4 points wide. Hover a segment for exact counts and shares.</p><div id="fx-bands"></div>' +
      '<h3 class="fx-h">Size and time</h3><p class="how">Each dot is one PSI-69 run. Click a dot to pin it and open its verified row record in the Data Explorer.</p>' +
      '<div class="fx-ctl"><label>Vertical measure <select id="fx-y"><option value="dExt">Droplet width at flame-out</option><option value="tBurn">Burn time</option><option value="rate">Burning rate</option></select></label></div>' +
      '<div class="legend" id="fx-leg"></div><div id="fx-sc"></div><p class="stat" id="fx-st"></p>' +
      '<div class="picked" id="fx-pick" hidden></div>' +
      '<h3 class="fx-h">Does adding a diluent change the ending?</h3><p class="how">Nitrogen is always present. CO₂ and helium were added in some tests. In the NASA table the column is headed "CO" and the FLEX report lists CO₂ as the added gas.</p>' +
      '<div id="fx-dil-chart"></div>' +
      '<h3 class="fx-h">Exact figures</h3><div class="scroll" id="fx-tbl"></div>' +
      '<p class="small" id="fx-note"></p>';

    ['fuel', 'dil', 'o2', 'p', 'reset', 'csv', 'json', 'status', 'facts', 'cov', 'o2p-matrix', 'export-msg', 'bands', 'y', 'leg', 'sc', 'st', 'pick', 'dil-chart', 'tbl', 'note']
      .forEach(function (k) { el[k] = host.querySelector('#fx-' + k); });

    rsO2 = FF.range(el.o2, {
      min: 14, max: 30, step: 0.5, value: [S.o2[0], S.o2[1]], digits: 1, unit: '%', label: 'Oxygen',
      onChange: function (a, b) { S.o2 = [a, b]; S.pick = null; fetchData(); }
    });
    rsP = FF.range(el.p, {
      min: 0.3, max: 3.1, step: 0.1, value: [S.p[0], S.p[1]], digits: 1, unit: 'atm', label: 'Pressure',
      onChange: function (a, b) { S.p = [a, b]; S.pick = null; fetchData(); }
    });

    el.leg.innerHTML = OUTCOMES.map(function (o) {
      return '<span class="lg"><i style="background:' + (COLORS[o] || '#6c7682') + '"></i>' + esc(o) + '</span>';
    }).join('');

    el.fuel.addEventListener('change', function (e) { S.fuel = e.target.value; S.pick = null; fetchData(); });
    el.dil.addEventListener('change', function (e) { S.diluent = e.target.value; S.pick = null; fetchData(); });
    el.y.addEventListener('change', function (e) { S.yKey = e.target.value; render(); });
    el.reset.addEventListener('click', function () {
      S.fuel = 'All'; S.diluent = 'All'; S.o2 = [14, 30]; S.p = [0.3, 3.1]; S.pick = null;
      el.fuel.value = 'All'; el.dil.value = 'All';
      rsO2.set(14, 30); rsP.set(0.3, 3.1);
      fetchData();
    });
    el.csv.addEventListener('click', function () { runExport('csv'); });
    el.json.addEventListener('click', function () { runExport('json'); });

    el.sc.addEventListener('click', function (e) {
      var pt = e.target.closest && e.target.closest('[data-id]');
      if (!pt) return;
      S.pick = pt.dataset.id;
      render();
    });
  }

  function buildPayload() {
    var dilMap = { All: null, N2_only: 'None', CO2: 'CO2', He: 'Helium' };
    return {
      fuel: S.fuel === 'All' ? null : S.fuel,
      diluent: Object.prototype.hasOwnProperty.call(dilMap, S.diluent) ? dilMap[S.diluent] : null,
      o2_min_pct: S.o2[0],
      o2_max_pct: S.o2[1],
      p_min_atm: S.p[0],
      p_max_atm: S.p[1]
    };
  }

  function buildExportPayload(fmt) {
    var y = YKEY[S.yKey] || YKEY.dExt;
    var numericFilters = [
      { field_name: 'initial_o2_flex_mol_pct', unit: '% mol', min_value: S.o2[0], max_value: S.o2[1] },
      { field_name: 'ambient_pressure_kpa', unit: 'atm', min_value: S.p[0], max_value: S.p[1] }
    ];
    if (S.diluent === 'N2_only') {
      numericFilters.push({ field_name: 'initial_co2_flex_mol_pct', unit: '% mol', min_value: 0.0, max_value: 0.0 });
      numericFilters.push({ field_name: 'initial_he_flex_mol_pct', unit: '% mol', min_value: 0.0, max_value: 0.0 });
    } else if (S.diluent === 'CO2') {
      numericFilters.push({ field_name: 'initial_co2_flex_mol_pct', unit: '% mol', min_value: 0.001 });
    } else if (S.diluent === 'He') {
      numericFilters.push({ field_name: 'initial_he_flex_mol_pct', unit: '% mol', min_value: 0.001 });
    }
    return {
      investigation_id: 'PSI-69',
      field_name: y.field,
      unit: y.unit,
      fuel: S.fuel === 'All' ? null : S.fuel,
      numeric_filters: numericFilters,
      format: fmt
    };
  }

  function runExport(fmt) {
    if (!FF.api || typeof FF.api.exportAndDownload !== 'function') return;
    el['export-msg'].textContent = 'Preparing verified ' + fmt.toUpperCase() + ' export...';
    FF.api.exportAndDownload(buildExportPayload(fmt)).then(function (env) {
      var d = (env && env.data) || {};
      el['export-msg'].textContent = 'Exported ' + (d.total_runs || 0) + ' runs (' + (d.used_in_summary_count || 0) + ' used, ' + (d.excluded_count || 0) + ' excluded) -> ' + (d.filename || ('export.' + fmt));
    }).catch(function (err) {
      el['export-msg'].textContent = 'Export failed: ' + ((err && err.message) || 'Unknown error');
    });
  }

  function fetchData() {
    if (!FF.api || typeof FF.api.analyticsFlex !== 'function') {
      S.error = 'Backend API client not available.';
      render();
      return;
    }
    var seq = ++S.seq;
    if (S.ctrl && typeof S.ctrl.abort === 'function') S.ctrl.abort();
    S.ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    S.loading = true;
    S.error = null;
    render();
    FF.api.analyticsFlex(buildPayload(), S.ctrl ? { signal: S.ctrl.signal } : undefined).then(function (env) {
      if (seq !== S.seq) return;
      S.loading = false;
      S.error = null;
      S.data = env && env.data ? env.data : null;
      if (FF.chat && typeof FF.chat.setContext === 'function') {
        var ctxFilters = [
          { field_name: 'initial_o2_flex_mol_pct', unit: '% mol', min_value: S.o2[0], max_value: S.o2[1] },
          { field_name: 'ambient_pressure_kpa', unit: 'atm', min_value: S.p[0], max_value: S.p[1] }
        ];
        if (S.diluent === 'N2_only') {
          ctxFilters.push({ field_name: 'initial_co2_flex_mol_pct', unit: '% mol', min_value: 0.0, max_value: 0.0 });
          ctxFilters.push({ field_name: 'initial_he_flex_mol_pct', unit: '% mol', min_value: 0.0, max_value: 0.0 });
        } else if (S.diluent === 'CO2') {
          ctxFilters.push({ field_name: 'initial_co2_flex_mol_pct', unit: '% mol', min_value: 0.001 });
        } else if (S.diluent === 'He') {
          ctxFilters.push({ field_name: 'initial_he_flex_mol_pct', unit: '% mol', min_value: 0.001 });
        }
        FF.chat.setContext({
          investigation_id: 'PSI-69',
          fuel: S.fuel === 'All' ? null : S.fuel,
          numeric_filters: ctxFilters,
          uiLabel: 'FLEX Lab (PSI-69 · ' + S.fuel + ', ' + S.diluent + ', ' + S.o2[0] + '–' + S.o2[1] + '% O₂, ' + S.p[0] + '–' + S.p[1] + ' atm)'
        }, { clearOnChange: false });
      }
      render();
    }).catch(function (err) {
      if (err && err.name === 'AbortError') return;
      if (seq !== S.seq) return;
      S.loading = false;
      S.error = (err && err.message) ? err.message : 'Unable to reach /api/analytics/flex.';
      render();
    });
  }

  function toOutcomeParts(outcomes, total) {
    var map = {};
    (outcomes || []).forEach(function (o) { map[o.label] = o; });
    var ordered = [];
    OUTCOMES.forEach(function (name) {
      if (map[name]) ordered.push({ name: name, n: map[name].count, share: map[name].share, ci: [map[name].share, map[name].share] });
    });
    (outcomes || []).forEach(function (o) {
      if (OUTCOMES.indexOf(o.label) < 0) ordered.push({ name: o.label, n: o.count, share: o.share, ci: [o.share, o.share] });
    });
    return { n: total, parts: ordered };
  }

  function runValue(r, key) {
    if (key === 'dExt') return r.d_ext_mm > 0 ? r.d_ext_mm : null;
    if (key === 'tBurn') return r.burn_time_s;
    return r.burning_rate_mm2_s;
  }

  function drawFacts(d) {
    var total = d.total_runs || 0;
    var fs = d.field_summaries || {};
    var bt = fs.burn_time_s || {};
    var dx = d.d_ext_diagnostics || {};
    var br = fs.burning_rate_mm2_s || {};
    var items = [
      '<span><b>' + total + '</b>of 274 FLEX runs</span>',
      '<span><b>' + (br.used_total_count || 0) + '</b>burning rate measured' + (br.excluded_by_status && br.excluded_by_status.missing ? ' (' + br.excluded_by_status.missing + ' missing)' : '') + '</span>'
    ];
    if (br.mean_value != null) items.push('<span><b>' + br.mean_value.toFixed(3) + ' mm²/s</b>mean burning rate</span>');
    if (bt.median_value != null) items.push('<span><b>' + bt.median_value.toFixed(1) + ' s</b>median burn time (' + bt.used_total_count + ' used)</span>');
    if (dx.positive_median_mm != null) items.push('<span><b>' + dx.positive_median_mm.toFixed(2) + ' mm</b>median flame-out width (' + dx.positive_used_count + ' positive, ' + dx.raw_zero_count + ' raw zero excluded)</span>');
    el.facts.innerHTML = items.join('');
  }

  function drawBands(d) {
    var bands = d.oxygen_bands || [];
    if (!bands.length) {
      el.bands.innerHTML = '<p class="empty">No tests match these settings.</p>';
      return;
    }
    var rows = bands.map(function (b) {
      var o = toOutcomeParts(b.outcomes, b.count);
      return { label: b.label, sub: b.count < 5 ? 'Few' : '', n: o.n, parts: o.parts };
    });
    el.bands.innerHTML = ch.outcomeBars({ rows: rows, label: 'Outcome shares by oxygen band' });
  }

  function drawScatter(d) {
    var y = YKEY[S.yKey] || YKEY.dExt;
    var runs = d.runs || [];
    var pts = [];
    runs.forEach(function (r) {
      var xv = r.o2_mol_pct;
      var yv = runValue(r, S.yKey);
      if (xv == null || yv == null) return;
      var dilLabel = r.diluent === 'CO2' ? ', with CO₂' : r.diluent === 'He' ? ', with Helium' : '';
      pts.push({
        id: r.record_pk,
        x: xv,
        y: yv,
        color: COLORS[r.test_end] || '#6c7682',
        tip: r.flex_identifier + ' (' + r.fuel + ', ended in ' + (r.test_end || '').toLowerCase() + ', oxygen ' + xv + '%' + dilLabel + '; ' + y.tip + ' ' + y.fmt(yv) + ')'
      });
    });
    el.sc.innerHTML = ch.scatter({ points: pts, selected: S.pick, xLabel: 'Starting oxygen (%)', yLabel: y.label, label: y.label + ' against starting oxygen' });

    var fs = (d.field_summaries || {})[y.field] || {};
    var dx = d.d_ext_diagnostics || {};
    if (S.yKey === 'dExt') {
      el.st.innerHTML = pts.length >= 2
        ? 'Positive flame-out width summary: <b>' + dx.positive_used_count + ' positive runs</b>' +
          (dx.positive_median_mm != null ? ' · median <b>' + dx.positive_median_mm.toFixed(2) + ' mm</b>' : '') +
          ' · ' + (dx.raw_zero_count || 0) + ' raw zero (0.0 mm) runs excluded from positive median.'
        : 'Too few positive flame-out width measurements to summarize.';
    } else if (fs.used_total_count) {
      var exclMissing = (fs.excluded_by_status && fs.excluded_by_status.missing) || 0;
      el.st.innerHTML = 'Measured runs: <b>' + fs.used_total_count + '</b> used, <b>' + exclMissing + '</b> missing · mean <b>' +
        num(fs.mean_value, 3) + '</b>, median <b>' + num(fs.median_value, 3) + '</b>, range <b>' +
        num(fs.min_value, 3) + ' to ' + num(fs.max_value, 3) + ' ' + esc(y.unit) + '</b>.';
    } else {
      el.st.textContent = 'Too few tests with this measurement to describe a pattern.';
    }
  }

  function drawPick(d) {
    var runs = d.runs || [];
    var r = null;
    for (var i = 0; i < runs.length; i++) {
      if (runs[i].record_pk === S.pick) { r = runs[i]; break; }
    }
    if (!r) { el.pick.hidden = true; el.pick.innerHTML = ''; return; }
    el.pick.hidden = false;
    el.pick.innerHTML =
      '<span><b>' + esc(r.flex_identifier) + '</b> (' + esc(r.record_pk) + ')</span>' +
      '<span>' + esc(r.fuel) + ', ' + esc(r.test_end || '') + '</span>' +
      '<span>' + (r.o2_mol_pct != null ? esc(r.o2_mol_pct + '% O₂') : 'O₂ —') +
      (r.p_atm != null ? ', ' + r.p_atm.toFixed(2) + ' atm' : '') +
      (r.burning_rate_mm2_s != null ? ', ' + r.burning_rate_mm2_s.toFixed(2) + ' mm²/s' : '') + '</span>' +
      '<a class="lnk" href="data.html?exp=PSI-69&pick=' + encodeURIComponent(r.record_pk) + '#s-explorer">Open this test in the Data Explorer ↗</a>' +
      '<button type="button" class="lnk" id="fx-unpick">Clear</button>';
    var unpick = el.pick.querySelector('#fx-unpick');
    if (unpick) unpick.addEventListener('click', function () { S.pick = null; render(); });
  }

  function drawDiluents(d) {
    var groups = d.diluent_groups || [];
    if (!groups.length) {
      el['dil-chart'].innerHTML = '<p class="empty">No diluent breakdown matches these settings.</p>';
      return;
    }
    var rows = groups.map(function (g) {
      var o = toOutcomeParts(g.outcomes, g.count);
      return { label: g.label, sub: g.count < 5 ? 'Few' : '', n: o.n, parts: o.parts };
    });
    el['dil-chart'].innerHTML = ch.outcomeBars({ rows: rows, label: 'Outcome shares by diluent' });
  }

  function drawTable(d) {
    var bands = d.oxygen_bands || [];
    if (!bands.length) { el.tbl.innerHTML = ''; return; }
    var rows = bands.map(function (b) {
      var ext = null;
      (b.outcomes || []).forEach(function (o) { if (o.label === 'Extinction') ext = o; });
      return '<tr><td>' + esc(b.fuel) + '</td><td>' + b.o2_min_pct + ' to ' + b.o2_max_pct + '%</td>' +
        '<td class="n">' + b.count + (b.count < 5 ? '<span class="few">Few</span>' : '') + '</td>' +
        '<td class="n">' + (ext ? ext.count + ' (' + Math.round(ext.share * 100) + '%)' : '0') + '</td>' +
        '<td class="n">' + (b.median_burn_time_s != null ? b.median_burn_time_s.toFixed(1) : '—') + '</td>' +
        '<td class="n">' + (b.median_d_ext_positive_mm != null ? b.median_d_ext_positive_mm.toFixed(2) : '—') + '</td></tr>';
    }).join('');
    el.tbl.innerHTML = '<table class="dt"><thead><tr><th>Fuel</th><th>Oxygen band</th><th class="n">Tests</th><th class="n">Extinction</th><th class="n">Median burn time s</th><th class="n">Median width at flame-out mm (&gt;0)</th></tr></thead><tbody>' + rows + '</tbody></table>';
  }

  function drawCoverageAndMatrix(d) {
    if (el.cov) {
      el.cov.innerHTML = (FF.api && typeof FF.api.renderCoverageCard === 'function' && d.coverage)
        ? FF.api.renderCoverageCard(d.coverage, { title: 'PSI-69 FLEX Subset' })
        : '';
    }
    var o2p = d.o2_pressure_coverage;
    if (!el['o2p-matrix'] || !o2p || !Array.isArray(o2p.pressure_bins)) {
      if (el['o2p-matrix']) el['o2p-matrix'].innerHTML = '';
      return;
    }
    var totalCorpus = o2p.total_psi69_count || d.corpus_total_runs || 274;
    var pCols = o2p.pressure_bins || [];
    var o2Rows = o2p.o2_bins || [];
    var maxTotal = 1;
    (o2p.cells || []).forEach(function (c) {
      if ((c.total_psi69_count || 0) > maxTotal) maxTotal = c.total_psi69_count;
    });
    var cellMap = {};
    (o2p.cells || []).forEach(function (c) {
      cellMap[c.o2_bin + '|' + c.p_bin] = c;
    });
    var headCells = '<th>O₂ % mol \\ Pressure (atm)</th>' + pCols.map(function (pb) {
      return '<th>' + esc(pb) + '</th>';
    }).join('');
    var bodyRows = o2Rows.map(function (ob) {
      var tds = pCols.map(function (pb) {
        var c = cellMap[ob + '|' + pb] || { filtered_count: 0, total_psi69_count: 0 };
        var tot = c.total_psi69_count || 0;
        var fil = c.filtered_count || 0;
        if (tot === 0) {
          return '<td class="cov-cell-empty" title="' + esc(ob + ' · ' + pb + ': 0 / ' + totalCorpus + ' PSI-69 tests') + '">0</td>';
        }
        var alpha = (0.12 + 0.42 * (tot / maxTotal)).toFixed(2);
        var cls = 'cov-cell-active' + (fil > 0 ? ' cov-cell-hl' : '');
        return '<td class="' + cls + '" style="background:rgba(43,126,161,' + alpha + ')" title="' + esc(fil + ' matching / ' + tot + ' total PSI-69 runs in cell') + '">' +
          esc(fil + ' / ' + tot) + '</td>';
      }).join('');
      return '<tr><th>' + esc(ob) + '</th>' + tds + '</tr>';
    }).join('');
    var regimes = (o2p.cross_regime_separation || []).map(function (r) {
      return '<div class="cov-regime-card"><strong>' + esc(r.dataset) + '</strong><div>' + esc(r.coverage) + '</div><div class="small" style="margin-top:4px">' + esc(r.gap_note) + '</div></div>';
    }).join('');
    el['o2p-matrix'].innerHTML =
      '<div class="cov-matrix-wrap">' +
        '<h3 class="cov-matrix-title">PSI-69 Measured O₂ × Pressure Evidence Grid (Zero Gap Interpolation)</h3>' +
        '<p class="cov-matrix-sub">Each cell shows <strong>filtered / total PSI-69 tests</strong> out of <strong>' + esc(o2p.filtered_with_o2_p_count) + ' / ' + esc(totalCorpus) + '</strong> indexed PSI-69 FLEX runs. Blank/0 cells mean zero PSI-69 tests exist in that O₂–pressure bin.</p>' +
        '<div class="scroll"><table class="cov-matrix"><thead><tr>' + headCells + '</tr></thead><tbody>' + bodyRows + '</tbody></table></div>' +
        (regimes ? '<div class="cov-regime-grid">' + regimes + '</div>' : '') +
      '</div>';
  }

  function render() {
    if (!built) return;
    if (S.error) {
      el.status.innerHTML = '<div class="callout gap"><strong>Backend error:</strong> ' + esc(S.error) + ' <button type="button" class="ghost sm" id="fx-retry">Retry</button></div>';
      var retry = el.status.querySelector('#fx-retry');
      if (retry) retry.addEventListener('click', fetchData);
    } else if (S.loading) {
      el.status.innerHTML = '<p class="small">Loading live PSI-69 analytics from backend...</p>';
    } else {
      el.status.innerHTML = '';
    }

    var d = S.data;
    if (!d) {
      el.facts.innerHTML = '';
      if (el.cov) el.cov.innerHTML = '';
      if (el['o2p-matrix']) el['o2p-matrix'].innerHTML = '';
      el.bands.innerHTML = '';
      el.sc.innerHTML = '';
      el.st.textContent = '';
      el['dil-chart'].innerHTML = '';
      el.tbl.innerHTML = '';
      return;
    }

    drawFacts(d);
    drawCoverageAndMatrix(d);
    drawBands(d);
    drawScatter(d);
    drawPick(d);
    drawDiluents(d);
    drawTable(d);

    var dx = d.d_ext_diagnostics || {};
    el.note.textContent = (dx.note || '') + ' ' + (d.boundary_note || '');
  }

  build();
  fetchData();
})();
