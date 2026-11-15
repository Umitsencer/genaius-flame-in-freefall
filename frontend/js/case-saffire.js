/* SAFFIRE IV-VI Case Study ("What did the fire do to the air?") interactive client.
 * Story layer (hero facts, key finding, timeline clock, thin-vs-thick) for a first-time reader, plus the expert
 * panels (conditions, full table, limits, sources, export). Wired to GET /api/saffire/case/schema,
 * POST /api/saffire/case, POST /api/saffire/case/export and case-scoped questions ({ scope: 'saffire_case' }).
 * Missing V-3/V-4 values stay null; the timeline shows published events only. */
(function (root) {
  'use strict';

  var FF = root.FF || (root.FF = {});
  if (FF.chat) {
    FF.chat.defaultContext = { scope: 'saffire_case' };
  }

  var state = {
    schema: null,
    data: null,
    selectedTestId: 'VI-3',
    filterFlight: '',
    filterFuel: '',
    clock: 0,          // experiment time shown on the story timeline (s)
    captionIdx: null,
    pausedAtThreshold: false,
    allRecords: null,  // unfiltered records: the story never changes with the expert filters
    vi3Timeline: null,
    timerId: null,
    loadSeq: 0,
    loadCtrl: null
  };

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function safeUrl(url) {
    if (!url || typeof url !== 'string') return '';
    try {
      var u = new URL(url, root.location ? root.location.href : 'http://127.0.0.1/');
      return (u.protocol === 'http:' || u.protocol === 'https:') ? u.href : '';
    } catch (_e) {
      return '';
    }
  }

  function fmtNum(v, unit, digits) {
    if (v === null || v === undefined || v === '') return null;
    var n = Number(v);
    if (!isFinite(n)) return null;
    var text = typeof digits === 'number' ? n.toFixed(digits) : (Number.isInteger(n) ? String(n) : String(n));
    return unit ? (text + ' ' + unit) : text;
  }

  function valOrUnreported(v, unit, digits) {
    var f = fmtNum(v, unit, digits);
    return f === null ? '<span class="v-dim">Unreported (null)</span>' : esc(f);
  }

  function activeRecord() {
    var recs = (state.data && state.data.records) || [];
    for (var i = 0; i < recs.length; i++) {
      if (recs[i].test_id === state.selectedTestId) return recs[i];
    }
    return recs[0] || null;
  }

  function syncUrlQuery() {
    if (!root.history || !root.history.replaceState || !root.location) return;
    var params = new URLSearchParams(root.location.search);
    if (state.selectedTestId) params.set('test', state.selectedTestId);
    if (state.filterFlight) params.set('flight', state.filterFlight); else params.delete('flight');
    if (state.filterFuel) params.set('fuel_group', state.filterFuel); else params.delete('fuel_group');
    var next = root.location.pathname + (params.toString() ? ('?' + params.toString()) : '') + (root.location.hash || '');
    root.history.replaceState(null, '', next);
  }

  function hydrateFromUrl() {
    if (!root.location) return;
    var params = new URLSearchParams(root.location.search);
    var t = params.get('test');
    if (t) state.selectedTestId = t.toUpperCase();
    var fl = params.get('flight');
    if (fl) state.filterFlight = fl;
    var fg = params.get('fuel_group');
    if (fg) state.filterFuel = fg;
  }

  function loadCaseData() {
    var outState = $('case-state');
    if (outState) {
      outState.innerHTML = '<p class="small">Loading verified SAFFIRE IV–VI case dataset...</p>';
    }
    var seq = ++state.loadSeq;
    if (state.loadCtrl && typeof state.loadCtrl.abort === 'function') state.loadCtrl.abort();
    state.loadCtrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var reqOpts = state.loadCtrl ? { signal: state.loadCtrl.signal } : undefined;
    var payload = {};
    if (state.filterFlight) payload.flight = state.filterFlight;
    if (state.filterFuel) payload.fuel_group = state.filterFuel;

    Promise.all([
      state.schema ? Promise.resolve({ data: state.schema }) : FF.api.saffireCaseSchema(reqOpts),
      FF.api.saffireCaseReference(payload, reqOpts)
    ]).then(function (pair) {
      if (seq !== state.loadSeq) return;
      state.schema = pair[0] && pair[0].data ? pair[0].data : state.schema;
      state.data = pair[1] && pair[1].data ? pair[1].data : null;
      if (state.data && !state.filterFlight && !state.filterFuel) {
        state.allRecords = state.data.records || [];
        state.vi3Timeline = state.data.summary && state.data.summary.vi3_timeline;
      } else if (!state.allRecords) {
        FF.api.saffireCaseReference({}).then(function (env) {
          var full = env && env.data;
          if (!full) return;
          state.allRecords = full.records || [];
          state.vi3Timeline = full.summary && full.summary.vi3_timeline;
          renderStory();
        }).catch(function () { /* story keeps the filtered subset */ });
      }
      if (outState) outState.innerHTML = '';
      populateSelects();
      ensureActiveRecordInSubset();
      renderAll();
    }).catch(function (err) {
      if (err && err.name === 'AbortError') return;
      if (seq !== state.loadSeq) return;
      if (outState) {
        outState.innerHTML = '<div class="callout gap"><strong>Unable to load case study data:</strong> ' +
          esc((err && err.message) || 'Backend error') +
          ' <button type="button" class="ghost sm" id="case-retry">Retry</button></div>';
        var btn = $('case-retry');
        if (btn) btn.addEventListener('click', loadCaseData);
      }
    });
  }

  function populateSelects() {
    if (!state.schema) return;
    var flightSel = $('case-flight');
    if (flightSel && flightSel.options.length <= 1) {
      (state.schema.available_flights || []).forEach(function (fl) {
        var opt = document.createElement('option');
        opt.value = fl;
        opt.textContent = fl;
        flightSel.appendChild(opt);
      });
      flightSel.value = state.filterFlight;
    }

    var testSel = $('case-test');
    if (testSel && state.data) {
      var recs = state.data.records || [];
      testSel.innerHTML = '';
      if (!recs.length) {
        var emptyOpt = document.createElement('option');
        emptyOpt.value = '';
        emptyOpt.textContent = 'No tests in current filter';
        testSel.appendChild(emptyOpt);
      } else {
        recs.forEach(function (r) {
          var opt = document.createElement('option');
          opt.value = r.test_id;
          opt.textContent = r.test_id + ' · ' + r.material;
          testSel.appendChild(opt);
        });
      }
    }
    if ($('case-fuel')) $('case-fuel').value = state.filterFuel;
  }

  function ensureActiveRecordInSubset() {
    var recs = (state.data && state.data.records) || [];
    if (!recs.length) return;
    var found = recs.some(function (r) { return r.test_id === state.selectedTestId; });
    if (!found) {
      state.selectedTestId = recs.some(function (r) { return r.test_id === 'VI-3'; }) ? 'VI-3' : recs[0].test_id;
    }
    if ($('case-test')) $('case-test').value = state.selectedTestId;
    syncUrlQuery();
  }

  function renderFactsAndRail() {
    var d = state.data;
    var factsEl = $('case-facts');
    var railEl = $('rail-active');
    if (!d) return;
    var sum = d.summary || {};
    var tl = sum.vi3_timeline || {};
    if (factsEl) {
      factsEl.innerHTML =
        '<span><b>' + esc(sum.total_condition_records || 0) + '</b>condition records in view</span>' +
        '<span><b>' + esc(sum.reported_gas_calorimetry_count || 0) + '</b>with Table 2 gas &amp; calorimetry</span>' +
        '<span><b>' + esc(tl.derived_elapsed_ignition_to_threshold_s || 344) + ' s</b>derived VI-3 Δt (981 − 637)</span>' +
        '<span><b>3</b>related detection cards (A/B/C)</span>';
      var covBox = $('case-cov');
      if (!covBox && factsEl.parentNode) {
        covBox = document.createElement('div');
        covBox.id = 'case-cov';
        factsEl.parentNode.insertBefore(covBox, factsEl.nextSibling);
      }
      if (covBox && d.coverage && FF.api && typeof FF.api.renderCoverageCard === 'function') {
        covBox.innerHTML = FF.api.renderCoverageCard(d.coverage, { title: 'SAFFIRE IV–VI Case Study' });
      }
    }
    if (FF.chat && typeof FF.chat.setContext === 'function') {
      var filterParts = [state.selectedTestId];
      if (state.filterFlight) filterParts.push(state.filterFlight);
      if (state.filterFuel) filterParts.push(state.filterFuel);
      FF.chat.setContext({
        scope: 'saffire_case',
        uiLabel: 'SAFFIRE IV–VI Case (' + filterParts.join(' · ') + ')'
      }, { clearOnChange: false });
    }
    var rec = activeRecord();
    if (!railEl) return;
    if (!rec) {
      railEl.innerHTML = '<p class="small">No active test matches the current flight/fuel filters.</p>';
      return;
    }
    var po2 = rec.derived && rec.derived.po2_kpa ? rec.derived.po2_kpa.value : null;
    railEl.innerHTML =
      '<div><strong>' + esc(rec.test_id + ' · ' + rec.material) + '</strong> (' + esc(rec.flight_date) + ')</div>' +
      '<div>Pressure / O₂: <b>' + esc(rec.ambient_pressure_kpa) + ' kPa</b> · <b>' + esc(rec.oxygen_mol_percent) + '%</b></div>' +
      '<div>Derived pO₂: <b>' + esc(po2 != null ? po2.toFixed(2) + ' kPa' : '—') + '</b> <span class="badge-tag tag-derived">derived</span></div>' +
      '<div>Free volume: <b>' + esc(rec.free_volume_m3) + ' m³</b> · Flow: <b>' + esc(rec.initial_air_flow_cm_s) + ' cm/s</b></div>' +
      '<div>ΔCO₂ / ΔCO (FFD): <b>' + valOrUnreported(rec.co2_partial_pressure_increase_mmhg, 'mmHg', 2) + '</b> / <b>' + valOrUnreported(rec.co_increase_ppm, 'ppm') + '</b></div>' +
      '<div class="small">Locators: ' + esc((rec.source_locators || []).join('; ')) + '</div>';
  }

  function renderConditions() {
    var d = state.data;
    var condEl = $('conditions-out');
    var flowEl = $('flow-protocol-out');
    if (!d || !condEl) return;
    var recs = d.records || [];
    if (!recs.length) {
      condEl.innerHTML = '<p class="empty">No SAFFIRE IV–VI tests match the selected flight/fuel filters. Reset filters to inspect all 7 tests.</p>';
      if (flowEl) flowEl.innerHTML = '';
      return;
    }

    condEl.innerHTML = '<div class="case-grid">' + recs.map(function (r) {
      var isSel = r.test_id === state.selectedTestId;
      var po2 = r.derived && r.derived.po2_kpa ? r.derived.po2_kpa.value : null;
      var hasGas = Boolean(r.gas_calorimetry_reported);
      return '<button type="button" class="cond-card' + (isSel ? ' active' : '') + '" data-test-id="' + esc(r.test_id) + '" aria-pressed="' + (isSel ? 'true' : 'false') + '">' +
        '<div class="ecard-head">' +
          '<span class="ecard-id">' + esc(r.test_id + ' · ' + r.flight) + '</span>' +
          '<span class="st ' + (hasGas ? 'st-measured' : 'st-none') + '">' + (hasGas ? 'Gas &amp; HRR reported' : 'Conditions only (null)') + '</span>' +
        '</div>' +
        '<div class="ecard-title">' + esc(r.material) + '</div>' +
        '<div class="ecard-meta">' + esc(r.material_detail) + '</div>' +
        '<div class="cond-kv">' +
          '<span>Pressure <b>' + esc(r.ambient_pressure_kpa) + ' kPa</b></span>' +
          '<span>O₂ conc. <b>' + esc(r.oxygen_mol_percent) + ' mol%</b></span>' +
          '<span>pO₂ (Derived) <b>' + esc(po2 != null ? po2.toFixed(2) + ' kPa' : '—') + '</b></span>' +
          '<span>Flow / Dir <b>' + esc(r.initial_air_flow_cm_s + ' cm/s ' + r.flow_direction) + '</b></span>' +
          '<span>Length <b>' + esc(r.sample_length_cm) + ' cm</b></span>' +
          '<span>Free vol. <b>' + esc(r.free_volume_m3) + ' m³</b></span>' +
        '</div>' +
      '</button>';
    }).join('') + '</div>';

    var active = activeRecord();
    if (flowEl && active) {
      var steps = active.flow_protocol || [];
      flowEl.innerHTML =
        '<div class="flow-strip">' +
          '<h3>Flow schedule &amp; experimental context for <span class="ecard-id">' + esc(active.test_id) + '</span></h3>' +
          '<div class="flow-steps">' +
          steps.map(function (st) {
            return '<div class="flow-step">' +
              '<div class="t">' + esc(st.time_label) + ' · ' + esc(st.flow_speed_cm_s) + ' cm/s</div>' +
              '<div>' + esc(st.note) + '</div>' +
              '<div class="small" style="margin-top:4px">' + esc(st.locator || '') + '</div>' +
            '</div>';
          }).join('') +
          '</div>' +
          (active.structured_notes && active.structured_notes.source_discrepancy_note
            ? '<div class="unres-box"><strong>Source audit note:</strong> ' + esc(active.structured_notes.source_discrepancy_note) + '</div>'
            : '') +
        '</div>';
    }
  }

  /* ---------- Story layer: plain-language view built on the same API records ---------- */

  var THIN_COLOR = '#58d1b8';
  var THICK_COLOR = '#ff9c87';

  function recordById(id) {
    var recs = (state.allRecords || (state.data && state.data.records) || []);
    for (var i = 0; i < recs.length; i++) if (recs[i].test_id === id) return recs[i];
    return null;
  }

  function mmss(sec) {
    var s = Math.max(0, Math.round(sec));
    var m = Math.floor(s / 60), r = s % 60;
    return (m < 10 ? '0' : '') + m + ':' + (r < 10 ? '0' : '') + r;
  }

  function minSec(sec) {
    var s = Math.round(sec), m = Math.floor(s / 60), r = s % 60;
    return m + ' min ' + r + ' s';
  }

  function timelineData() {
    return (state.data && state.data.summary && state.data.summary.vi3_timeline) || state.vi3Timeline || null;
  }

  // Plain-language caption per published event; the technical label/locator stays in the expert panel.
  var EVENT_STORY = {
    start: { icon: '🌬️', title: 'Fan on', text: 'A gentle breeze (20 cm/s) flows over the sample. Nothing is burning yet.' },
    ignition: { icon: '🔥', title: 'Ignition', text: 'A hot wire lights the plastic. The fire starts — and the smoke starts to build.' },
    alarm_threshold: { icon: '🚨', title: 'Smoke hits the selected smoke criterion', text: 'Smoke near the sensor crosses 1 mg/m³, the smoke-concentration criterion selected by the authors. By now, much of the harmful gas is already out.' },
    flow_reduced: { icon: '🔽', title: 'Breeze turned down', text: 'Air flow drops from 20 to 5 cm/s. With less fresh air mixing in, CO and CO₂ at the outlet climb.' },
    flow_terminated: { icon: '⏹', title: 'Fan off, test over', text: 'The fan stops. Saffire VI-3 is complete.' }
  };

  function renderSetupFacts() {
    var r = recordById('VI-3');
    if (!r) return;
    if ($('fx-volume') && r.free_volume_m3 != null) $('fx-volume').textContent = r.free_volume_m3 + ' m³';
    if ($('fx-pressure') && r.ambient_pressure_kpa != null) $('fx-pressure').textContent = r.ambient_pressure_kpa + ' kPa';
    if ($('fx-oxygen') && r.oxygen_mol_percent != null) $('fx-oxygen').textContent = r.oxygen_mol_percent + ' %';
  }

  function gauge(value, max, marks, color) {
    var pct = Math.min(100, (value / max) * 100);
    var ticks = marks.map(function (m) {
      var p = Math.min(100, (m.val / max) * 100);
      var edge = p > 75 ? ' end' : (p < 20 ? ' start' : '');
      return '<span class="cs-g-mark' + edge + '" style="left:' + p.toFixed(1) + '%"><i></i><em>' + esc(m.label) + '</em></span>';
    }).join('');
    return '<div class="cs-gauge" role="img" aria-label="' + esc(value + ' against ' + marks.map(function (m) { return m.label; }).join(', ')) + '">' +
      '<div class="cs-g-track"><div class="cs-g-fill" style="width:' + pct.toFixed(1) + '%;background:' + color + '"></div></div>' + ticks + '</div>';
  }

  function renderFinding() {
    var el = $('finding-stats');
    var tl = timelineData();
    var r = recordById('VI-3');
    if (!el || !tl || !r) return;
    var dt = tl.derived_elapsed_ignition_to_threshold_s || (tl.alarm_threshold_time_s - tl.ignition_time_s);
    var head = $('finding-headline');
    if (head) head.textContent = 'Elapsed from ignition: ' + minSec(dt) + ' to the selected smoke criterion.';
    var thr = (state.data && state.data.regulatory_reference_thresholds) || {};
    var co2Lim = thr.co2_partial_pressure_1h_mmhg ? thr.co2_partial_pressure_1h_mmhg.value : 3.0;
    var co24 = thr.co_smac_24h_ppm ? thr.co_smac_24h_ppm.value : 100;
    var co1h = thr.co_smac_1h_ppm ? thr.co_smac_1h_ppm.value : 425;
    var co2 = r.co2_partial_pressure_increase_mmhg, co = r.co_increase_ppm;
    var coRatio = co != null ? (co / co24) : null;

    el.innerHTML =
      '<article class="cs-stat hero">' +
        '<span class="cs-stat-k">Ignition to selected smoke criterion</span>' +
        '<span class="cs-stat-v">' + esc(dt) + '<small> s</small></span>' +
        '<span class="cs-stat-d">' + esc(minSec(dt)) + ' · from ignition (' + esc(tl.ignition_time_s) + ' s) to the 1 mg/m³ line (' + esc(tl.alarm_threshold_time_s) + ' s)</span>' +
        '<span class="cs-tag derived">Computed by us: ' + esc(tl.alarm_threshold_time_s) + ' − ' + esc(tl.ignition_time_s) + '</span>' +
        '<span class="cs-stat-d">Reported burn duration: ' + esc(r.burn_duration_s) + ' s</span>' +
      '</article>' +
      (co2 != null ?
      '<article class="cs-stat">' +
        '<span class="cs-stat-k">Rise in CO₂</span>' +
        '<span class="cs-stat-v">' + esc(co2) + '<small> mmHg</small></span>' +
        gauge(co2, 4, [{ val: co2Lim, label: 'NASA 1-h limit ' + Number(co2Lim).toFixed(1) }], THICK_COLOR) +
        '<span class="cs-stat-d">Above the 1-hour limit the authors compared it with.</span>' +
        '<span class="cs-tag reported">Reported · NTRS 20240002981 Table 2</span>' +
      '</article>' : '') +
      (co != null ?
      '<article class="cs-stat">' +
        '<span class="cs-stat-k">Rise in carbon monoxide (CO)</span>' +
        '<span class="cs-stat-v">' + esc(co) + '<small> ppm</small></span>' +
        gauge(co, 460, [{ val: co24, label: '24-h limit ' + co24 }, { val: co1h, label: '1-h limit ' + co1h }], THICK_COLOR) +
        '<span class="cs-stat-d">About ' + esc(coRatio.toFixed(1)) + '× the 24-hour limit, still below the 1-hour limit.</span>' +
        '<span class="cs-tag reported">Reported · JSC 20584 limits</span>' +
      '</article>' : '');
  }

  function rangeOf(recs, key) {
    var vals = recs.map(function (r) { return r[key]; }).filter(function (v) { return v !== null && v !== undefined; });
    if (!vals.length) return null;
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    return lo === hi ? String(lo) : (lo + '–' + hi);
  }

  function renderVersus() {
    var el = $('versus-out');
    var recs = (state.allRecords || []).filter(function (r) { return r.gas_calorimetry_reported; });
    if (!el || !recs.length) return;
    var thin = recs.filter(function (r) { return r.fuel_group === 'thin_textile'; });
    var thick = recs.filter(function (r) { return r.fuel_group === 'thick_pmma'; });
    function col(cls, icon, title, sub, group) {
      return '<div class="cs-vs-col ' + cls + '">' +
        '<div class="cs-vs-head"><span class="cs-ico" aria-hidden="true">' + icon + '</span><div><h3>' + esc(title) + '</h3>' +
        '<p>' + esc(sub) + ' · ' + esc(group.map(function (r) { return r.test_id; }).join(', ')) + '</p></div></div>' +
        '<dl>' +
          '<div><dt>Burned for</dt><dd>' + esc(rangeOf(group, 'burn_duration_s')) + ' <small>s</small></dd></div>' +
          '<div><dt>CO rise</dt><dd>' + esc(rangeOf(group, 'co_increase_ppm')) + ' <small>ppm</small></dd></div>' +
          '<div><dt>CO₂ rise</dt><dd>' + esc(rangeOf(group, 'co2_partial_pressure_increase_mmhg')) + ' <small>mmHg</small></dd></div>' +
        '</dl></div>';
    }
    el.innerHTML =
      col('thin', '🧵', 'Thin fabric', 'Cotton / SIBAL cloth', thin) +
      '<div class="cs-vs-mid" aria-hidden="true">vs</div>' +
      col('thick', '🧱', 'Thick plastic', 'Acrylic (PMMA)', thick);
  }

  function buildBarChartSvg(title, items, refLines, maxVal, unit) {
    var W = 520, rowH = 34, padL = 150, padR = 70, padT = 34, padB = 12;
    var H = padT + items.length * rowH + padB;
    var plotW = W - padL - padR;
    function xPos(val) { return padL + (Math.min(Math.max(val, 0), maxVal) / maxVal) * plotW; }

    var defs = '<defs><pattern id="tex-' + unit + '" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">' +
      '<line x1="0" y1="0" x2="0" y2="6" stroke="#050505" stroke-opacity=".35" stroke-width="2"/></pattern></defs>';

    var grid = '<line x1="' + padL + '" y1="' + (padT - 6) + '" x2="' + padL + '" y2="' + (H - padB) + '" stroke="#3a3a3d"/>';

    var bars = items.map(function (it, idx) {
      var y = padT + idx * rowH;
      var isSel = it.id === state.selectedTestId;
      var fill = it.isThin ? THIN_COLOR : THICK_COLOR;
      var lbl = '<text x="0" y="' + (y + 16) + '" font-size="12.5" font-weight="' + (isSel ? '700' : '500') + '" fill="' + (isSel ? '#f1eee8' : '#b0aca4') + '">' + esc(it.id) + '</text>' +
        '<text x="44" y="' + (y + 16) + '" font-size="11.5" fill="#8f8b84">' + esc(it.short) + '</text>';
      if (it.val === null || it.val === undefined) {
        return '<g><title>' + esc(it.id + ': not published') + '</title>' + lbl +
          '<rect x="' + padL + '" y="' + (y + 4) + '" width="' + (plotW * 0.55).toFixed(1) + '" height="16" rx="4" fill="none" stroke="#6e5a22" stroke-dasharray="3 3"/>' +
          '<text x="' + (padL + 8) + '" y="' + (y + 16) + '" font-size="11" fill="#e6c15a" stroke="#0b0b0c" stroke-width="4" paint-order="stroke">not published (gap, not zero)</text></g>';
      }
      var bw = Math.max(4, xPos(it.val) - padL);
      return '<g><title>' + esc(it.id + ' · ' + it.short + ': ' + it.val + ' ' + unit) + '</title>' + lbl +
        '<rect x="' + padL + '" y="' + (y + 4) + '" width="' + bw.toFixed(1) + '" height="16" rx="4" fill="' + fill + '" fill-opacity="' + (isSel ? '1' : '0.8') + '"/>' +
        (it.isThin ? '' : '<rect x="' + padL + '" y="' + (y + 4) + '" width="' + bw.toFixed(1) + '" height="16" rx="4" fill="url(#tex-' + unit + ')"/>') +
        (isSel ? '<rect x="' + (padL - 2) + '" y="' + (y + 2) + '" width="' + (bw + 4).toFixed(1) + '" height="20" rx="5" fill="none" stroke="#f1eee8" stroke-width="1.5"/>' : '') +
        '<text x="' + (padL + bw + 6).toFixed(1) + '" y="' + (y + 16) + '" font-size="12" fill="#f1eee8" stroke="#0b0b0c" stroke-width="4" paint-order="stroke">' + esc(String(it.val)) + '</text></g>';
    }).join('');

    var lines = refLines.map(function (rl) {
      var x = xPos(rl.val).toFixed(1);
      return '<line x1="' + x + '" y1="' + (padT - 10) + '" x2="' + x + '" y2="' + (H - padB) + '" stroke="' + rl.color + '" stroke-dasharray="4 3" stroke-width="1.5"/>' +
        '<text x="' + x + '" y="' + (padT - 16) + '" text-anchor="' + (rl.anchor || 'middle') + '" font-size="11" fill="' + rl.color + '">' + esc(rl.label) + '</text>';
    }).join('');

    return '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(title) + '">' + defs + grid + lines + bars + '</svg>';
  }

  function shortMaterial(r) {
    return { 'SIBAL Cloth': 'SIBAL cloth', 'Cotton Jersey': 'Cotton', 'One-Sided PMMA': 'PMMA 1-sided', 'Two-Sided PMMA': 'PMMA 2-sided', 'Structured PMMA': 'PMMA ribbed' }[r.material] || r.material;
  }

  function renderAirCharts() {
    var chartsEl = $('air-charts-out');
    var recs = state.allRecords || [];
    if (!chartsEl || !recs.length) return;
    function items(key) {
      return recs.map(function (r) { return { id: r.test_id, short: shortMaterial(r), val: r[key], isThin: r.fuel_group === 'thin_textile' }; });
    }
    var coSvg = buildBarChartSvg('Rise in CO per test, with JSC 20584 limits', items('co_increase_ppm'),
      [{ val: 100, label: '24-h limit 100', color: '#e6c15a' }, { val: 425, label: '1-h limit 425', color: '#ff7a9c', anchor: 'end' }], 460, 'ppm');
    var co2Svg = buildBarChartSvg('Rise in CO2 per test, with the NASA 1-hour limit', items('co2_partial_pressure_increase_mmhg'),
      [{ val: 3.0, label: '1-h limit 3.0', color: '#ff7a9c' }], 4.0, 'mmHg');
    chartsEl.innerHTML =
      '<div class="cs-legend"><span><i style="background:' + THIN_COLOR + '"></i>Thin fabric</span>' +
        '<span><i class="tex" style="background:' + THICK_COLOR + '"></i>Thick plastic (PMMA)</span>' +
        '<span><i class="gap"></i>Not published</span></div>' +
      '<div class="chart-pair cs-charts">' +
        '<div class="chart-panel"><h3>Rise in CO <small>(ppm)</small></h3>' + coSvg + '</div>' +
        '<div class="chart-panel"><h3>Rise in CO₂ <small>(mmHg)</small></h3>' + co2Svg + '</div>' +
      '</div>';
  }

  function renderAirTable() {
    var d = state.data;
    var tableEl = $('air-table-out');
    if (!d || !tableEl) return;
    var recs = d.records || [];
    if (!recs.length) {
      tableEl.innerHTML = '<p class="empty">No records in active filter.</p>';
      return;
    }
    var rowsHtml = recs.map(function (r) {
      var isSel = r.test_id === state.selectedTestId;
      return '<tr class="' + (isSel ? 'sel' : '') + '" data-row-test="' + esc(r.test_id) + '">' +
        '<td><strong>' + esc(r.test_id) + '</strong></td>' +
        '<td>' + esc(r.material) + '</td>' +
        '<td class="n">' + valOrUnreported(r.burn_duration_s, 's') + '</td>' +
        '<td class="n">' + valOrUnreported(r.o2_peak_heat_release_w, 'W') + '</td>' +
        '<td class="n">' + valOrUnreported(r.o2_total_heat_release_kj, 'kJ') + '</td>' +
        '<td class="n">' + valOrUnreported(r.fuel_avg_heat_release_w, 'W') + '</td>' +
        '<td class="n">' + valOrUnreported(r.fuel_total_heat_release_kj, 'kJ') + '</td>' +
        '<td class="n">' + valOrUnreported(r.max_temp_sfu_outlet_c, '°C') + '</td>' +
        '<td class="n">' + valOrUnreported(r.max_temp_ffd_c, '°C') + '</td>' +
        '<td class="n">' + valOrUnreported(r.co2_increase_ppm, 'ppm') + '</td>' +
        '<td class="n">' + valOrUnreported(r.co2_partial_pressure_increase_mmhg, 'mmHg', 2) + '</td>' +
        '<td class="n">' + valOrUnreported(r.co_increase_ppm, 'ppm') + '</td>' +
      '</tr>';
    }).join('');
    tableEl.innerHTML =
      '<div class="scroll"><table class="dt tt">' +
        '<thead><tr>' +
          '<th>Test</th><th>Material</th><th class="n">Burn (s)</th>' +
          '<th class="n">O₂ Peak HRR</th><th class="n">O₂ Total Heat</th>' +
          '<th class="n">Fuel Avg HRR</th><th class="n">Fuel Total Heat</th>' +
          '<th class="n">SFU Max °C</th><th class="n">FFD Max °C</th>' +
          '<th class="n">ΔCO₂ (ppm)</th><th class="n">ΔCO₂ (mmHg)</th><th class="n">ΔCO (ppm)</th>' +
        '</tr></thead>' +
        '<tbody>' + rowsHtml + '</tbody>' +
      '</table></div>' +
      '<div class="dual-cal"><strong>Why does Saffire VI-2 have two calorimetry columns?</strong> NTRS 20240002981 Table 2 (p.6) reports both <em>Oxygen Consumption Calorimetry</em> (<code>3217 W</code> peak, <code>580 kJ</code> total) and <em>Fuel Consumption Calorimetry</em> (<code>3650 W</code> avg, <code>409 kJ</code> total). Thick PMMA lacks the fuel-consumption column because surface regression cannot be tracked optically; on Saffire IV–V, outlet gas mixing prevented O₂ calorimetry. The authors state (p.4) the two VI-2 methods agree within ~15%.</div>';
  }

  /* ---------- Interactive timeline: a clock over published events only ---------- */

  var TL_MAX = 1500;

  function tlEnd() {
    var tl = timelineData();
    return (tl && tl.flow_terminated_time_s) || TL_MAX;
  }

  function renderTimeline() {
    var el = $('timeline-out');
    var tl = timelineData();
    if (!el || !tl) return;
    var events = tl.events || [];
    function pct(sec) { return (Math.min(Math.max(sec, 0), TL_MAX) / TL_MAX * 100).toFixed(2); }
    var ign = tl.ignition_time_s, thr = tl.alarm_threshold_time_s, end = tl.flow_terminated_time_s;

    var ticks = '';
    for (var m = 0; m <= 25; m += 5) {
      ticks += '<span class="cs-tick' + (m === 25 ? ' last' : '') + (m % 10 ? ' odd' : '') + '" style="left:' + pct(m * 60) + '%">' + m + ' min</span>';
    }
    var markers = events.map(function (ev, idx) {
      var st = EVENT_STORY[ev.event_id] || { icon: '•', title: ev.label };
      return '<button type="button" class="cs-ev ev-' + esc(ev.event_id) + '" data-ev="' + idx + '" style="left:' + pct(ev.time_s) + '%" aria-label="' + esc(st.title + ' at ' + mmss(ev.time_s)) + '">' +
        '<span class="cs-ev-dot" aria-hidden="true">' + st.icon + '</span>' +
        '<span class="cs-ev-t">' + mmss(ev.time_s) + '</span>' +
        '<span class="cs-ev-n">' + esc(st.title) + '</span>' +
      '</button>';
    }).join('');

    el.innerHTML =
      '<div class="cs-track" id="cs-track">' +
        '<div class="cs-band burn" style="left:' + pct(ign) + '%;width:' + (pct(end) - pct(ign)).toFixed(2) + '%"><span>ignition to flow stop</span></div>' +
        '<div class="cs-band silent" style="left:' + pct(ign) + '%;width:' + (pct(thr) - pct(ign)).toFixed(2) + '%"><span>' + esc(thr - ign) + ' s</span></div>' +
        '<div class="cs-rail"><div class="cs-rail-fill" id="cs-rail-fill"></div></div>' +
        '<div class="cs-head" id="cs-head"></div>' +
        markers +
        ticks +
      '</div>';
    if (!state.clockStarted) {
      state.clockStarted = true;
      setClock(tlEnd());
      var keyIdx = -1;
      events.forEach(function (ev, idx) { if (ev.event_id === 'alarm_threshold') keyIdx = idx; });
      if (keyIdx >= 0) showCaption(events, keyIdx);
      setPlayButton(false);
    } else {
      setClock(state.clock, true);
    }
  }

  function renderTimelineSources() {
    var el = $('timeline-sources');
    var tl = timelineData();
    if (!el || !tl) return;
    el.innerHTML = '<div class="tl-cards">' + (tl.events || []).map(function (ev) {
      return '<div class="tl-card active">' +
        '<div class="sec">' + esc(ev.time_s) + ' s · ' + esc(String(ev.kind).toUpperCase()) + '</div>' +
        '<div><strong>' + esc(ev.label) + '</strong></div>' +
        '<div style="margin-top:4px">' + esc(ev.detail) + '</div>' +
        '<div class="small" style="margin-top:4px">' + esc(ev.locator) + '</div>' +
      '</div>';
    }).join('') + '</div>';
  }

  // Move the clock to `sec` and light up everything that has happened by then.
  function setClock(sec, quiet) {
    var tl = timelineData();
    if (!tl) return;
    state.clock = sec;
    var events = tl.events || [];
    var ign = tl.ignition_time_s, thr = tl.alarm_threshold_time_s;
    var p = (Math.min(sec, TL_MAX) / TL_MAX * 100).toFixed(2) + '%';
    var head = $('cs-head'), fill = $('cs-rail-fill'), track = $('cs-track');
    if (head) head.style.left = p;
    if (fill) fill.style.width = p;
    if (track) {
      track.classList.toggle('lit-burn', sec >= ign);
      track.classList.toggle('lit-silent', sec >= ign);
      track.classList.toggle('lit-silent-done', sec >= thr);
    }
    var current = -1;
    events.forEach(function (ev, idx) {
      var btn = document.querySelector('.cs-ev[data-ev="' + idx + '"]');
      var on = sec >= ev.time_s;
      if (on) current = idx;
      if (btn) btn.classList.toggle('on', on);
    });
    events.forEach(function (_ev, idx) {
      var btn = document.querySelector('.cs-ev[data-ev="' + idx + '"]');
      if (btn) btn.classList.toggle('now', idx === current);
    });
    if ($('story-clock')) $('story-clock').textContent = mmss(sec);
    var silentBox = $('story-silent');
    if (silentBox) {
      silentBox.hidden = sec < ign;
      var silentFor = Math.max(0, Math.min(sec, thr) - ign);
      if ($('story-silent-val')) $('story-silent-val').textContent = Math.round(silentFor) + ' s';
      silentBox.classList.toggle('done', sec >= thr);
    }
    if (current !== state.captionIdx || !quiet) showCaption(events, current);
  }

  function showCaption(events, idx) {
    state.captionIdx = idx;
    var cap = $('story-caption');
    if (cap) {
      if (idx < 0) {
        cap.innerHTML = '<p class="cs-cap-hint">Press play, or tap any event on the line.</p>';
      } else {
        var ev = events[idx];
        var st = EVENT_STORY[ev.event_id] || { icon: '•', title: ev.label, text: ev.detail };
        cap.innerHTML = '<span class="cs-cap-ico" aria-hidden="true">' + st.icon + '</span>' +
          '<div><p class="cs-cap-t">' + esc(mmss(ev.time_s)) + ' · ' + esc(st.title) + '</p>' +
          '<p class="cs-cap-x">' + esc(st.text) + '</p>' +
          '<p class="cs-cap-src">' + esc(ev.locator) + '</p></div>';
      }
    }
    var lbl = $('tl-step-label');
    if (lbl) lbl.textContent = idx < 0 ? '' : ('Event ' + (idx + 1) + ' of ' + events.length);
  }

  function setPlayButton(playing) {
    var btn = $('tl-play');
    if (!btn) return;
    btn.classList.toggle('playing', playing);
    var ico = btn.querySelector('.cs-play-ico'), txt = btn.querySelector('.cs-play-txt');
    if (ico) ico.textContent = playing ? '❚❚' : '▶';
    if (txt) txt.textContent = playing ? 'Pause' : (state.clock >= tlEnd() - 1 ? 'Play from start' : 'Play');
    btn.setAttribute('aria-label', playing ? 'Pause the timeline' : 'Play the timeline');
  }

  function stopWalkthrough() {
    stopWalkthroughHard();
    setPlayButton(false);
  }

  function toggleWalkthrough() {
    if (state.timerId !== null) { stopWalkthrough(); return; }
    var tl = timelineData();
    if (!tl) return;
    var reduced = root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) { stepTimeline(1); return; }
    if (state.clock >= tlEnd() - 1) setClock(0);
    var SPEED = 95; // experiment seconds per real second (~16 s for the whole run)
    var last = null;
    setPlayButton(true);
    function frame(ts) {
      if (last === null) last = ts;
      var next = state.clock + (ts - last) / 1000 * SPEED;
      last = ts;
      // pause briefly on the key moment so the audience can read it
      var thr = tl.alarm_threshold_time_s;
      if (state.clock < thr && next >= thr && !state.pausedAtThreshold) {
        state.pausedAtThreshold = true;
        setClock(thr);
        state.timerId = setTimeout(function () { last = null; state.timerId = requestAnimationFrame(frame); }, 1800);
        return;
      }
      if (next >= tlEnd()) {
        setClock(tlEnd());
        state.timerId = null;
        state.pausedAtThreshold = false;
        setPlayButton(false);
        return;
      }
      setClock(next);
      state.timerId = requestAnimationFrame(frame);
    }
    state.pausedAtThreshold = state.clock >= tl.alarm_threshold_time_s;
    state.timerId = requestAnimationFrame(frame);
  }

  function stepTimeline(delta) {
    var tl = timelineData();
    var events = (tl && tl.events) || [];
    if (!events.length) return;
    stopWalkthroughHard();
    var cur = -1;
    events.forEach(function (ev, idx) { if (state.clock >= ev.time_s) cur = idx; });
    var nxt = Math.max(0, Math.min(events.length - 1, cur + delta));
    setClock(events[nxt].time_s);
    setPlayButton(false);
  }

  function stopWalkthroughHard() {
    if (state.timerId !== null) {
      cancelAnimationFrame(state.timerId);
      clearTimeout(state.timerId);
      state.timerId = null;
    }
  }

  function renderStory() {
    renderSetupFacts();
    renderFinding();
    renderVersus();
    renderAirCharts();
    if (!state.timelineDrawn) {
      renderTimeline();
      renderTimelineSources();
      state.timelineDrawn = true;
    }
  }

  function renderAll() {
    renderFactsAndRail();
    renderConditions();
    renderAirTable();
    renderStory();
    renderLimitsAndRelated();
  }

  function renderLimitsAndRelated() {
    var d = state.data;
    var limEl = $('limits-out');
    var relEl = $('related-out');
    var srcEl = $('sources-out');
    if (!d) return;

    if (limEl) {
      var doesNot = (d.what_this_does_not_establish || []).map(function (s) {
        return '<li>' + esc(s) + '</li>';
      }).join('');
      var unres = (d.unresolved_items || []).map(function (u) {
        return '<li><strong>' + esc(u.field) + ' (' + esc(u.status) + '):</strong> ' + esc(u.detail) + '</li>';
      }).join('');
      limEl.innerHTML =
        '<div class="limit-grid">' +
          '<div class="limit-box"><h3>What this does not establish</h3><ul>' + doesNot + '</ul></div>' +
          '<div class="limit-box"><h3>Unresolved source notes &amp; missing fields</h3><ul>' + unres + '</ul></div>' +
        '</div>';
    }

    if (relEl) {
      var cards = (d.detection_evidence || []).map(function (card) {
        return '<article class="ecard">' +
          '<div class="ecard-head"><span class="ecard-id">' + esc(card.evidence_id) + '</span><span class="st st-approx">' + esc(card.category) + '</span></div>' +
          '<div class="ecard-title">' + esc(card.title) + '</div>' +
          '<div class="ecard-reason">' + esc(card.summary) + '</div>' +
          (card.derived_note ? '<div class="unres-box"><strong>Derived note:</strong> ' + esc(card.derived_note) + '</div>' : '') +
          '<div class="ecard-limit"><strong>Limits:</strong> ' + esc(card.limitations) + '</div>' +
          '<div class="ecard-meta">Locators: ' + esc((card.locators || []).join('; ')) + '</div>' +
        '</article>';
      }).join('');
      relEl.innerHTML = '<div class="card-grid">' + cards + '</div>';
    }

    if (srcEl) {
      var srcCards = (d.verified_sources || []).map(function (s) {
        var href = safeUrl(s.url);
        return '<article class="pass-card">' +
          '<div class="ecard-head"><span class="ecard-id">' + esc(s.source_id) + ' · ' + esc(s.date) + '</span>' +
          '<span class="st ' + (s.access_status === 'paywalled_metadata_only' ? 'st-invalid' : 'st-measured') + '">' + esc(s.access_status) + '</span></div>' +
          '<div class="ecard-title">' + esc(s.title) + '</div>' +
          '<div class="ecard-meta">' + esc(s.authors) + ' · ' + esc(s.pages_verified) + '</div>' +
          '<div class="ecard-meta">' + (s.sha256 ? 'SHA-256 <code>' + esc(String(s.sha256).slice(0, 16)) + '...</code> · ' : '') +
            (href ? '<a class="lnk" href="' + esc(href) + '" target="_blank" rel="noopener noreferrer">Open primary citation ↗</a>' : '') +
          '</div>' +
        '</article>';
      }).join('');
      srcEl.innerHTML = '<h3 class="sh">Verified source audit ledger (inspected 2026-11-14)</h3>' + srcCards;
    }
  }

  function bindEvents() {
    if ($('case-test')) {
      $('case-test').addEventListener('change', function () {
        if (this.value) {
          state.selectedTestId = this.value;
          syncUrlQuery();
          renderAll();
        }
      });
    }
    if ($('case-flight')) {
      $('case-flight').addEventListener('change', function () {
        state.filterFlight = this.value || '';
        loadCaseData();
      });
    }
    if ($('case-fuel')) {
      $('case-fuel').addEventListener('change', function () {
        state.filterFuel = this.value || '';
        loadCaseData();
      });
    }
    if ($('case-reset')) {
      $('case-reset').addEventListener('click', function () {
        state.selectedTestId = 'VI-3';
        state.filterFlight = '';
        state.filterFuel = '';
        loadCaseData();
      });
    }

    if ($('conditions-out')) {
      $('conditions-out').addEventListener('click', function (e) {
        var btn = e.target && e.target.closest ? e.target.closest('[data-test-id]') : null;
        if (btn && btn.dataset && btn.dataset.testId) {
          state.selectedTestId = btn.dataset.testId;
          if ($('case-test')) $('case-test').value = state.selectedTestId;
          syncUrlQuery();
          renderAll();
        }
      });
    }
    if ($('air-table-out')) {
      $('air-table-out').addEventListener('click', function (e) {
        var row = e.target && e.target.closest ? e.target.closest('tr[data-row-test]') : null;
        if (row && row.dataset && row.dataset.rowTest) {
          state.selectedTestId = row.dataset.rowTest;
          if ($('case-test')) $('case-test').value = state.selectedTestId;
          syncUrlQuery();
          renderAll();
        }
      });
    }

    if ($('tl-prev')) $('tl-prev').addEventListener('click', function () { stepTimeline(-1); });
    if ($('tl-next')) $('tl-next').addEventListener('click', function () { stepTimeline(1); });
    if ($('tl-play')) $('tl-play').addEventListener('click', toggleWalkthrough);
    if ($('tl-reset')) {
      $('tl-reset').addEventListener('click', function () {
        stopWalkthrough();
        setClock(tlEnd());
        setPlayButton(false);
      });
    }
    if ($('timeline-out')) {
      $('timeline-out').addEventListener('click', function (e) {
        var btn = e.target && e.target.closest ? e.target.closest('[data-ev]') : null;
        var tl = timelineData();
        if (!btn || !tl) return;
        stopWalkthrough();
        var ev = (tl.events || [])[Number(btn.dataset.ev)];
        if (ev) setClock(ev.time_s);
      });
    }

    function runExport(fmt) {
      var msgEl = $('case-export-msg');
      if (msgEl) msgEl.textContent = 'Preparing ' + fmt.toUpperCase() + ' export...';
      var payload = { format: fmt };
      if (state.filterFlight) payload.flight = state.filterFlight;
      if (state.filterFuel) payload.fuel_group = state.filterFuel;
      FF.api.saffireCaseExportAndDownload(payload).then(function (env) {
        var d = env && env.data ? env.data : {};
        if (msgEl) msgEl.textContent = 'Downloaded ' + (d.filename || fmt) + ' (' + (d.record_count || 0) + ' records).';
      }).catch(function (err) {
        if (msgEl) msgEl.textContent = 'Export failed: ' + ((err && err.message) || 'error');
      });
    }

    if ($('case-export-json')) $('case-export-json').addEventListener('click', function () { runExport('json'); });
    if ($('case-export-csv')) $('case-export-csv').addEventListener('click', function () { runExport('csv'); });

    if ($('case-ask-chips')) {
      $('case-ask-chips').addEventListener('click', function (e) {
        var btn = e.target && e.target.closest ? e.target.closest('button[data-q]') : null;
        if (btn && btn.dataset && btn.dataset.q && FF.chat && typeof FF.chat.ask === 'function') {
          FF.chat.ask(btn.dataset.q, { scope: 'saffire_case' });
        }
      });
    }
  }

  hydrateFromUrl();
  bindEvents();
  loadCaseData();
})(window);
