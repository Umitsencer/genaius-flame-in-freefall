/* Validated FLEX Pre-Test Condition Predictor, Support Gate, O2-Diluent Map & Evaluation Workbench.
 * Wired live to /api/flex/predict/schema, /api/flex/predict, /api/flex/predict/map,
 * /api/flex/predict/export, /api/flex/reconciliation, and scoped /api/answer ("Explain these results"). */
(function (root) {
  'use strict';
  root.FF = root.FF || {};

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function validateClientCondition(formState) {
    var fuel = formState.fuel;
    var o2 = Number(formState.o2Pct) / 100;
    var dilMode = formState.dilMode || 'Air';
    var co2 = dilMode === 'CO2' ? Number(formState.dilPct) / 100 : (dilMode === 'MIXED' ? Number(formState.mixCo2Pct) / 100 : 0);
    var he = dilMode === 'He' ? Number(formState.dilPct) / 100 : (dilMode === 'MIXED' ? Number(formState.mixHePct) / 100 : 0);
    var pVal = Number(formState.pressureVal);
    var pUnit = formState.pressureUnit || 'atm';
    var d0 = Number(formState.d0Mm);

    var errors = [];
    if (!isFinite(o2) || o2 < 0 || o2 > 1) errors.push('O2 must be between 0% and 100%.');
    if (!isFinite(co2) || co2 < 0 || co2 > 1) errors.push('CO2 must be between 0% and 100%.');
    if (!isFinite(he) || he < 0 || he > 1) errors.push('Helium must be between 0% and 100%.');
    if (!isFinite(pVal) || pVal <= 0) errors.push('Pressure must be strictly positive.');
    if (!isFinite(d0) || d0 <= 0 || d0 > 50) errors.push('Initial droplet diameter d0 must be in (0, 50] mm.');

    var sumOther = (isFinite(o2) ? o2 : 0) + (isFinite(co2) ? co2 : 0) + (isFinite(he) ? he : 0);
    var n2 = 1.0 - sumOther;
    if (isFinite(sumOther) && sumOther > 1.01) {
      errors.push('O2 + CO2 + He exceeds 101% (implied N2 remainder would be negative: ' + (n2 * 100).toFixed(1) + '%).');
    } else if (isFinite(n2) && n2 < 0) {
      errors.push('Implied N2 remainder is negative (' + (n2 * 100).toFixed(1) + '%).');
    }

    var payload = {
      fuel: fuel,
      o2_mol_frac: Math.round(o2 * 10000) / 10000,
      co2_mol_frac: Math.round(co2 * 10000) / 10000,
      he_mol_frac: Math.round(he * 10000) / 10000,
      droplet_initial_diameter_mm: Math.round(d0 * 1000) / 1000
    };
    if (pUnit === 'mmHg') payload.pressure_mmhg = pVal;
    else if (pUnit === 'kPa') payload.pressure_kpa = pVal;
    else payload.pressure_atm = pVal;

    return {
      valid: errors.length === 0,
      errors: errors,
      n2Frac: isFinite(n2) ? n2 : null,
      gasSumFrac: isFinite(sumOther) ? (sumOther + Math.max(0, n2)) : null,
      payload: payload,
      mapDiluentRegime: dilMode === 'CO2' ? 'CO2' : (dilMode === 'He' ? 'He' : 'Air')
    };
  }

  root.FF.flexPredictorHelpers = {
    validateClientCondition: validateClientCondition
  };

  if (typeof document === 'undefined') return;
  var host = document.getElementById('s-flex-predictor');
  if (!host) return;

  var S = {
    fuel: 'Methanol',
    o2Pct: '21.0',
    dilMode: 'Air',
    dilPct: '0.0',
    mixCo2Pct: '15.0',
    mixHePct: '15.0',
    pressureVal: '1.00',
    pressureUnit: 'atm',
    d0Mm: '2.50',

    schema: null,
    schemaError: null,
    schemaUnavailable: false,
    reconciliation: null,

    uiState: 'loading', // loading | ok | not_supported | invalid | unavailable | error
    predError: null,
    prediction: null,

    mapMetric: 'burning_rate_mm2_s',
    mapData: null,
    mapLoading: false,
    mapError: null,
    selectedMapItem: null,

    evalTab: 'benchmarks',
    exportMsg: '',

    predSeq: 0,
    predCtrl: null,
    mapSeq: 0,
    mapCtrl: null,
    debounceTimer: null
  };

  var el = {};
  var built = false;

  function build() {
    if (built) return;
    built = true;
    host.innerHTML =
      '<div class="view-head">' +
      '<p class="fp-kicker">Pre-Test Research Models · Validated PSI-69 Joint Support</p>' +
      '<h2>What FLEX condition models estimate — and where support stops</h2>' +
      '<p>Pre-test only (<em>fuel</em>, O₂, CO₂ or He diluent, N₂ remainder, pressure, <em>d₀</em>). ' +
      'Both models are regularized statistical fits selected among evaluated candidates—<strong>never a physics simulation, physical law, or spacecraft fire-safety probability</strong>. ' +
      'Changing inputs triggers zero LLM calls.</p>' +
      '</div>' +

      '<div class="fp-actions">' +
      '<span class="small" style="color:var(--muted)">Quick scenarios:</span>' +
      '<button type="button" class="ghost sm" data-preset="meth_air">Methanol 21% O₂ Air (Supported)</button>' +
      '<button type="button" class="ghost sm" data-preset="meth_he">Methanol + He dilution (Supported)</button>' +
      '<button type="button" class="ghost sm" data-preset="hep_co2">Heptane + CO₂ 2 atm (Supported)</button>' +
      '<button type="button" class="ghost sm" data-preset="air_3atm">Heptane Air 3 atm (OOD Blocked)</button>' +
      '<button type="button" class="ghost sm" data-preset="mixed_dil">Mixed CO₂ + He (Blocked)</button>' +
      '</div>' +

      '<form class="fp-form" id="fp-form" novalidate>' +
      '<label class="fp-fld">Fuel' +
      '<select id="fp-fuel"><option value="Methanol">Methanol</option><option value="Heptane">Heptane</option></select>' +
      '</label>' +
      '<label class="fp-fld">Initial O₂ (% mol)' +
      '<input id="fp-o2" type="number" step="0.5" min="0" max="100" value="21.0">' +
      '</label>' +
      '<label class="fp-fld">Added diluent regime' +
      '<select id="fp-dil-mode">' +
      '<option value="Air">None (N₂ balance only)</option>' +
      '<option value="CO2">CO₂ added (He = 0)</option>' +
      '<option value="He">Helium added (CO₂ = 0)</option>' +
      '<option value="MIXED">Test CO₂ + He mix (Blocked check)</option>' +
      '</select>' +
      '</label>' +
      '<label class="fp-fld" id="fp-dil-wrap">Added diluent (% mol)' +
      '<input id="fp-dil" type="number" step="1" min="0" max="85" value="0.0">' +
      '</label>' +
      '<div class="fp-fld" id="fp-mix-wrap" hidden>' +
      '<span>CO₂ % / He % (mixed check)</span>' +
      '<div class="fp-row-inline">' +
      '<input id="fp-mix-co2" type="number" step="1" min="0" max="80" value="15" aria-label="Mixed CO2 percent">' +
      '<input id="fp-mix-he" type="number" step="1" min="0" max="80" value="15" aria-label="Mixed He percent">' +
      '</div></div>' +
      '<label class="fp-fld">Ambient pressure' +
      '<div class="fp-row-inline">' +
      '<input id="fp-p" type="number" step="0.05" value="1.00" aria-label="Ambient pressure value">' +
      '<select id="fp-p-unit" aria-label="Pressure unit"><option value="atm">atm</option><option value="mmHg">mmHg</option><option value="kPa">kPa</option></select>' +
      '</div></label>' +
      '<label class="fp-fld">Initial droplet d₀ (mm)' +
      '<input id="fp-d0" type="number" step="0.1" min="0.1" max="50" value="2.50">' +
      '</label>' +
      '</form>' +

      '<div class="fp-actions">' +
      '<div class="fp-balance" id="fp-balance" aria-live="polite">N₂ remainder: 79.0%</div>' +
      '<button type="button" class="btn" id="fp-explain">Explain these results</button>' +
      '<button type="button" class="ghost" id="fp-exp-md">Download summary (.md)</button>' +
      '<button type="button" class="ghost" id="fp-exp-json">Download summary (.json)</button>' +
      '<span class="small" id="fp-export-msg" aria-live="polite"></span>' +
      '</div>' +

      '<div id="fp-status" aria-live="polite"></div>' +
      '<div id="fp-cov"></div>' +

      '<div class="fp-grid" id="fp-cards">' +
      '<article class="fp-card" id="fp-card-k"></article>' +
      '<article class="fp-card" id="fp-card-ext"></article>' +
      '</div>' +

      '<div class="fp-section" id="fp-nearest-wrap"></div>' +

      '<div class="fp-section">' +
      '<div class="fp-section-head">' +
      '<div><h3 class="fp-subhead">O₂–diluent condition support map (interpolations across gaps disabled)</h3>' +
      '<p class="fp-meta">Evaluated live via <code>check_flex_support</code>. Hatched dark cells fall outside joint PSI-69 experimental support (null predictions). Discrete dots show real PSI-69 tests.</p></div>' +
      '<label class="small">Surface metric: <select id="fp-map-metric"><option value="burning_rate_mm2_s">Burning-rate K estimate (mm²/s)</option><option value="extinction_score">Extinction model score (0–1)</option></select></label>' +
      '</div>' +
      '<div class="fp-map-shell">' +
      '<div class="fp-map-canvas" id="fp-map-canvas"></div>' +
      '<aside class="fp-card" id="fp-map-inspector" aria-live="polite"></aside>' +
      '</div>' +
      '</div>' +

      '<div class="fp-section fp-grid">' +
      '<article class="fp-card" id="fp-audit-panel"></article>' +
      '<article class="fp-card" id="fp-oof-panel"></article>' +
      '</div>' +

      '<div class="fp-section">' +
      '<div class="fp-tabs" role="group" aria-label="Model transparency tabs">' +
      '<button type="button" class="fp-tab" data-evaltab="benchmarks" aria-pressed="true">Grouped-CV benchmarks &amp; eligibility</button>' +
      '<button type="button" class="fp-tab" data-evaltab="structure" aria-pressed="false">Transformed feature weights</button>' +
      '<button type="button" class="fp-tab" data-evaltab="reconcile" aria-pressed="false">Table IX vs PSI-69 (276 vs 274)</button>' +
      '</div>' +
      '<div class="fp-card" id="fp-eval-body"></div>' +
      '</div>';

    ['fuel', 'o2', 'dil-mode', 'dil', 'dil-wrap', 'mix-wrap', 'mix-co2', 'mix-he', 'p', 'p-unit', 'd0',
      'balance', 'explain', 'exp-md', 'exp-json', 'export-msg', 'status', 'cov', 'card-k', 'card-ext',
      'nearest-wrap', 'map-metric', 'map-canvas', 'map-inspector', 'audit-panel', 'oof-panel', 'eval-body'
    ].forEach(function (k) { el[k] = host.querySelector('#fp-' + k); });

    host.addEventListener('click', function (e) {
      var presetBtn = e.target.closest && e.target.closest('[data-preset]');
      if (presetBtn) {
        applyPreset(presetBtn.dataset.preset);
        return;
      }
      var tabBtn = e.target.closest && e.target.closest('[data-evaltab]');
      if (tabBtn) {
        S.evalTab = tabBtn.dataset.evaltab;
        Array.prototype.forEach.call(host.querySelectorAll('[data-evaltab]'), function (b) {
          b.setAttribute('aria-pressed', String(b.dataset.evaltab === S.evalTab));
        });
        paintEvalPanel();
      }
    });

    function syncAndSchedule(updateMapAlso) {
      S.fuel = el.fuel.value;
      S.o2Pct = el.o2.value;
      S.dilMode = el['dil-mode'].value;
      S.dilPct = el.dil.value;
      S.mixCo2Pct = el['mix-co2'].value;
      S.mixHePct = el['mix-he'].value;
      S.pressureVal = el.p.value;
      S.pressureUnit = el['p-unit'].value;
      S.d0Mm = el.d0.value;

      if (S.dilMode === 'Air') {
        el.dil.value = '0.0';
        S.dilPct = '0.0';
        el.dil.disabled = true;
        el['dil-wrap'].hidden = false;
        el['mix-wrap'].hidden = true;
      } else if (S.dilMode === 'MIXED') {
        el['dil-wrap'].hidden = true;
        el['mix-wrap'].hidden = false;
      } else {
        el.dil.disabled = false;
        el['dil-wrap'].hidden = false;
        el['mix-wrap'].hidden = true;
      }
      schedulePredict(updateMapAlso);
    }

    ['fuel', 'dil-mode', 'p-unit'].forEach(function (id) {
      el[id].addEventListener('change', function () { syncAndSchedule(true); });
    });
    ['o2', 'dil', 'mix-co2', 'mix-he', 'p', 'd0'].forEach(function (id) {
      el[id].addEventListener('input', function () { syncAndSchedule(id === 'p' || id === 'd0'); });
    });

    el['map-metric'].addEventListener('change', function () {
      S.mapMetric = el['map-metric'].value;
      paintMap();
    });

    el.explain.addEventListener('click', function () {
      var check = validateClientCondition(S);
      if (!check.valid) return;
      if (!root.FF.chat || typeof root.FF.chat.ask !== 'function') return;
      var verdict = (S.prediction && S.prediction.status === 'OK')
        ? 'supported (' + S.fuel + ', ' + S.o2Pct + '% O2, ' + S.pressureVal + ' ' + S.pressureUnit + ', d0=' + S.d0Mm + ' mm)'
        : 'currently ' + (S.prediction ? S.prediction.status : S.uiState);
      root.FF.chat.ask(
        'Explain these FLEX model results (' + verdict + '), distinguish statistical estimates from nearest measured PSI-69 tests, and state scope and false-positive limits.',
        {
          scope: 'flex_prediction',
          flex_condition: check.payload
        }
      );
    });

    el['exp-md'].addEventListener('click', function () { runExport('md'); });
    el['exp-json'].addEventListener('click', function () { runExport('json'); });
  }

  function applyPreset(name) {
    var map = {
      meth_air: { fuel: 'Methanol', o2Pct: '21.0', dilMode: 'Air', dilPct: '0.0', pressureVal: '1.00', pressureUnit: 'atm', d0Mm: '2.50' },
      meth_he: { fuel: 'Methanol', o2Pct: '21.0', dilMode: 'He', dilPct: '39.0', pressureVal: '1.00', pressureUnit: 'atm', d0Mm: '2.50' },
      hep_co2: { fuel: 'Heptane', o2Pct: '21.0', dilMode: 'CO2', dilPct: '20.0', pressureVal: '2.00', pressureUnit: 'atm', d0Mm: '2.50' },
      air_3atm: { fuel: 'Heptane', o2Pct: '21.0', dilMode: 'Air', dilPct: '0.0', pressureVal: '3.00', pressureUnit: 'atm', d0Mm: '2.50' },
      mixed_dil: { fuel: 'Methanol', o2Pct: '21.0', dilMode: 'MIXED', mixCo2Pct: '15.0', mixHePct: '15.0', pressureVal: '1.00', pressureUnit: 'atm', d0Mm: '2.50' }
    }[name];
    if (!map) return;
    Object.assign(S, map);
    el.fuel.value = S.fuel;
    el.o2.value = S.o2Pct;
    el['dil-mode'].value = S.dilMode;
    el.dil.value = S.dilPct;
    if (map.mixCo2Pct) el['mix-co2'].value = S.mixCo2Pct;
    if (map.mixHePct) el['mix-he'].value = S.mixHePct;
    el.p.value = S.pressureVal;
    el['p-unit'].value = S.pressureUnit;
    el.d0.value = S.d0Mm;
    el.dil.disabled = S.dilMode === 'Air';
    el['dil-wrap'].hidden = S.dilMode === 'MIXED';
    el['mix-wrap'].hidden = S.dilMode !== 'MIXED';
    schedulePredict(true);
  }

  function runExport(fmt) {
    var check = validateClientCondition(S);
    if (!check.valid || !root.FF.api || typeof root.FF.api.flexPredictExportAndDownload !== 'function') return;
    el['export-msg'].textContent = 'Preparing condition summary (' + fmt.toUpperCase() + ')...';
    var req = Object.assign({ format: fmt }, check.payload);
    root.FF.api.flexPredictExportAndDownload(req).then(function (env) {
      var d = (env && env.data) || {};
      el['export-msg'].textContent = 'Downloaded ' + (d.filename || ('summary.' + fmt));
    }).catch(function (err) {
      el['export-msg'].textContent = 'Export failed: ' + ((err && err.message) || 'Unknown error');
    });
  }

  function schedulePredict(updateMapAlso) {
    clearTimeout(S.debounceTimer);
    var check = validateClientCondition(S);
    if (check.n2Frac != null) {
      el.balance.textContent = 'N₂ remainder: ' + (check.n2Frac * 100).toFixed(1) + '% · Sum: ' + ((check.gasSumFrac || 0) * 100).toFixed(1) + '%';
    } else {
      el.balance.textContent = 'N₂ remainder: invalid';
    }
    if (!check.valid) {
      if (S.predCtrl && typeof S.predCtrl.abort === 'function') S.predCtrl.abort();
      S.predSeq++;
      S.uiState = 'invalid';
      S.prediction = null;
      S.predError = check.errors.join(' ');
      paintPrediction();
      return;
    }
    if (S.schemaUnavailable) {
      S.uiState = 'unavailable';
      S.prediction = null;
      paintPrediction();
      return;
    }
    S.uiState = 'loading';
    paintStatusOnly();
    S.debounceTimer = setTimeout(function () {
      fetchPredict(check);
      if (updateMapAlso) fetchMap(check);
    }, 140);
  }

  function fetchPredict(check) {
    if (!root.FF.api || typeof root.FF.api.flexPredict !== 'function') return;
    var seq = ++S.predSeq;
    if (S.predCtrl && typeof S.predCtrl.abort === 'function') S.predCtrl.abort();
    S.predCtrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    root.FF.api.flexPredict(check.payload, S.predCtrl ? { signal: S.predCtrl.signal } : undefined)
      .then(function (env) {
        if (seq !== S.predSeq) return;
        var d = (env && env.data) || null;
        if (env && env.status === 'FLEX_PREDICTOR_UNAVAILABLE') {
          S.schemaUnavailable = true;
          S.uiState = 'unavailable';
          S.prediction = null;
          S.predError = env.message || 'Optional FLEX predictor is unavailable.';
        } else if (d && d.status === 'NOT_SUPPORTED') {
          S.uiState = 'not_supported';
          S.prediction = d;
          S.predError = null;
        } else if (d && d.status === 'OK') {
          S.uiState = 'ok';
          S.prediction = d;
          S.predError = null;
        } else {
          S.uiState = 'error';
          S.prediction = null;
          S.predError = (env && env.message) || 'Unexpected response from /api/flex/predict.';
        }
        if (root.FF && root.FF.chat && typeof root.FF.chat.setContext === 'function') {
          root.FF.chat.setContext({
            scope: 'flex_prediction',
            flex_condition: check.payload,
            uiLabel: 'FLEX Predictor (' + S.fuel + ', ' + S.o2Pct + '% O₂, ' + S.pressureVal + ' ' + S.pressureUnit + ')'
          }, { clearOnChange: false });
        }
        paintPrediction();
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        if (seq !== S.predSeq) return;
        if (err && (err.httpStatus === 503 || err.status === 'FLEX_PREDICTOR_UNAVAILABLE')) {
          S.schemaUnavailable = true;
          S.uiState = 'unavailable';
          S.prediction = null;
          S.predError = err.message;
        } else if (err && (err.httpStatus === 400 || err.status === 'INVALID_INPUT')) {
          S.uiState = 'invalid';
          S.prediction = null;
          S.predError = err.message;
        } else {
          S.uiState = 'error';
          S.prediction = null;
          S.predError = (err && err.message) || 'Network error reaching /api/flex/predict.';
        }
        paintPrediction();
      });
  }

  function fetchMap(check) {
    if (!root.FF.api || typeof root.FF.api.flexPredictMap !== 'function') return;
    var seq = ++S.mapSeq;
    if (S.mapCtrl && typeof S.mapCtrl.abort === 'function') S.mapCtrl.abort();
    S.mapCtrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    S.mapLoading = true;
    S.mapError = null;
    paintMap();
    var req = {
      fuel: check.payload.fuel,
      diluent_regime: check.mapDiluentRegime,
      droplet_initial_diameter_mm: check.payload.droplet_initial_diameter_mm,
      o2_steps: 13,
      y_steps: 9
    };
    if (check.payload.pressure_atm != null) req.pressure_atm = check.payload.pressure_atm;
    else if (check.payload.pressure_kpa != null) req.pressure_kpa = check.payload.pressure_kpa;
    else req.pressure_mmhg = check.payload.pressure_mmhg;

    root.FF.api.flexPredictMap(req, S.mapCtrl ? { signal: S.mapCtrl.signal } : undefined)
      .then(function (env) {
        if (seq !== S.mapSeq) return;
        S.mapLoading = false;
        S.mapData = (env && env.data) || null;
        S.mapError = null;
        paintMap();
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        if (seq !== S.mapSeq) return;
        S.mapLoading = false;
        S.mapError = (err && err.message) || 'Unable to load condition support map.';
        paintMap();
      });
  }

  function paintStatusOnly() {
    el.status.innerHTML = '<p class="small">Checking joint PSI-69 experimental support and running validated linear/logistic models...</p>';
  }

  function clearPredictionCards(reasonText) {
    el['card-k'].innerHTML =
      '<span class="fp-badge warn">A · Burning-rate constant (ridge_phys8)</span>' +
      '<h3>Estimate withheld</h3>' +
      '<div class="fp-bigval">—</div>' +
      '<p class="fp-meta">' + esc(reasonText) + '</p>';
    el['card-ext'].innerHTML =
      '<span class="fp-badge warn">B · Extinction score (logit_phys10)</span>' +
      '<h3>Score withheld</h3>' +
      '<div class="fp-bigval">—</div>' +
      '<p class="fp-meta">' + esc(reasonText) + '</p>';
  }

  function paintCoverageCard() {
    if (!el.cov || !root.FF.api || typeof root.FF.api.renderCoverageCard !== 'function') return;
    var d = S.prediction;
    var covPayload = (d && d.coverage) || ((S.uiState === 'unavailable' || S.uiState === 'error')
      ? {
          status: 'unavailable',
          ui_label: 'SOURCE UNAVAILABLE / ERROR',
          corpus_id: 'FLEX Condition Predictor',
          matching_count: 0,
          total_corpus_count: 274,
          tolerance_policy: { applied_tolerance: 'Predictor unavailable or errored.' },
          differing_or_missing_conditions: [S.predError || 'Predictor offline.']
        }
      : (S.uiState === 'invalid'
        ? {
            status: 'no_match',
            ui_label: 'NO MATCH IN INDEXED SOURCES',
            corpus_id: 'FLEX Condition Predictor',
            matching_count: 0,
            total_corpus_count: 274,
            tolerance_policy: { applied_tolerance: 'Client physical gas-sum/domain validation failed.' },
            differing_or_missing_conditions: [S.predError || 'Invalid condition input.']
          }
        : null));
    el.cov.innerHTML = covPayload
      ? root.FF.api.renderCoverageCard(covPayload, { title: 'FLEX Support & Prediction Gate', showAllLimitations: true })
      : '';
  }

  function paintPrediction() {
    var d = S.prediction;
    el.explain.disabled = S.uiState === 'invalid' || S.uiState === 'unavailable';
    el['exp-md'].disabled = S.uiState === 'invalid' || S.uiState === 'unavailable';
    el['exp-json'].disabled = S.uiState === 'invalid' || S.uiState === 'unavailable';

    if (S.uiState === 'loading') {
      paintStatusOnly();
      return;
    }
    paintCoverageCard();
    if (S.uiState === 'unavailable') {
      el.status.innerHTML = '<div class="fp-warnbox"><strong>Optional model artifact unavailable (HTTP 503):</strong> ' +
        esc(S.predError || 'Pre-test FLEX model service is offline.') +
        ' Empirical NASA PSI-69 charts above and Data Explorer remain operational.</div>';
      clearPredictionCards('No prediction generated while optional artifact is offline.');
      el['nearest-wrap'].innerHTML = '';
      paintAuditPanel();
      return;
    }
    if (S.uiState === 'invalid') {
      el.status.innerHTML = '<div class="fp-errbox"><strong>Invalid condition input:</strong> ' + esc(S.predError) + ' Prior estimates have been cleared.</div>';
      clearPredictionCards('Fix input validation error above to evaluate support.');
      el['nearest-wrap'].innerHTML = '';
      paintAuditPanel();
      return;
    }
    if (S.uiState === 'error') {
      el.status.innerHTML = '<div class="fp-errbox"><strong>Backend error:</strong> ' + esc(S.predError) +
        ' <button type="button" class="ghost sm" id="fp-retry">Retry</button></div>';
      var rbtn = el.status.querySelector('#fp-retry');
      if (rbtn) rbtn.addEventListener('click', function () { schedulePredict(true); });
      clearPredictionCards('Request failed; prior estimates cleared.');
      el['nearest-wrap'].innerHTML = '';
      paintAuditPanel();
      return;
    }
    if (S.uiState === 'not_supported' && d) {
      var sup = d.support || {};
      var reasonsHtml = (sup.reasons || []).map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('');
      el.status.innerHTML =
        '<div class="fp-errbox"><strong>NOT_SUPPORTED · Predictions withheld</strong> ' +
        '(nearest distance <code>' + esc(sup.nearest_distance_std) + ' std</code> &gt; threshold <code>' + esc(sup.distance_threshold_std) + ' std</code>, or outside joint fuel/diluent/pressure/d₀ bounds):' +
        '<ul style="margin:6px 0 0 18px">' + reasonsHtml + '</ul></div>';
      clearPredictionCards('Outside joint NASA PSI-69 experimental support. No extrapolation is emitted.');
      paintNearestRuns(sup);
      paintAuditPanel();
      return;
    }

    if (S.uiState === 'ok' && d && d.predictions) {
      var supOk = d.support || {};
      var preds = d.predictions;
      var k = preds.burning_rate_mm2_s || {};
      var ex = preds.extinction_likelihood || {};
      var scModels = (S.schema && S.schema.models) || {};
      var fpInfo = (scModels.extinction_classification && scModels.extinction_classification.non_extinction_fp_warning) || {};
      var fpByEnd = ex.false_positives_by_true_end || fpInfo.by_true_end || {};

      el.status.innerHTML =
        '<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center">' +
        '<span class="fp-badge ok">SUPPORTED · Joint PSI-69 Envelope</span>' +
        '<span class="small" style="color:var(--muted)">Nearest tested FLEX run: <code>' + esc(supOk.nearest_distance_std) + ' std</code> (gate &le; <code>' + esc(supOk.distance_threshold_std) + ' std</code>) · Model <code>' + esc(d.model_version) + '</code></span>' +
        '</div>';

      el['card-k'].innerHTML =
        '<span class="fp-badge">A · Burning-rate constant (ridge_phys8)</span>' +
        '<h3>' + esc(k.value != null ? k.value.toFixed(3) : '—') + ' mm²/s <span class="small" style="font-weight:400;color:var(--muted)">(estimated)</span></h3>' +
        '<p class="fp-meta">Selected among evaluated candidates (L2-regularized linear regression on 8 transformed features; raw output ' + esc(k.raw_model_output) + ' mm²/s).</p>' +
        '<p class="fp-meta"><strong>Grouped-CV error (atm+P):</strong> MAE <code>' + esc(k.group_cv_mae) + '</code> · RMSE <code>' + esc(k.group_cv_rmse) + '</code> mm²/s · R² <code>' + esc(k.group_cv_r2) + '</code> (explained variance, NOT "% accuracy") · fuel+atm+P R² <code>' + esc(k.group_fuel_cv_r2) + '</code>.</p>';

      el['card-ext'].innerHTML =
        '<span class="fp-badge">B · Extinction score (logit_phys10)</span>' +
        '<h3>' + esc(ex.score != null ? ex.score.toFixed(3) : '—') + ' · ' + esc(ex.predicted_label) + '</h3>' +
        '<p class="fp-meta">L2 logistic classification score on 10 transformed features (threshold <code>' + esc(ex.decision_threshold) + '</code>). Target: <code>Extinction</code> vs pooled <code>Completion + Disruption</code>.</p>' +
        '<p class="fp-meta"><strong>Grouped-CV discrimination (atm+P):</strong> ROC-AUC <code>' + esc(ex.group_cv_roc_auc) + '</code> (rank discrimination, NOT calibrated accuracy) · Brier <code>' + esc(ex.group_cv_brier) + '</code> · fuel+atm+P AUC <code>' + esc(ex.group_fuel_cv_roc_auc) + '</code>.</p>' +
        '<div class="fp-warnbox"><strong>Prominent Non-Extinction &amp; Calibration Warning:</strong> Score is NOT a spacecraft fire-safety probability. ' +
        'In grouped CV (atm+P), <strong>' + esc((fpInfo.fp != null ? fpInfo.fp : 33) + '/' + (fpInfo.negative_non_extinction != null ? fpInfo.negative_non_extinction : 82)) + ' (' +
        esc(ex.false_positive_rate_on_non_extinction != null ? (ex.false_positive_rate_on_non_extinction * 100).toFixed(1) : '40.2') + '%) Non-Extinction runs</strong> were false positives (Disruption <code>' +
        esc(fpByEnd.Disruption || '21/55') + '</code>, Completion <code>' + esc(fpByEnd.Completion || '12/27') + '</code>). NASA/TP-2015-216046 §5.2 notes fuel-needle contamination in Methanol Disruptions.</div>';

      paintNearestRuns(supOk);
      paintAuditPanel();
    }
  }

  function paintNearestRuns(sup) {
    var runs = (sup && Array.isArray(sup.nearest_experiments)) ? sup.nearest_experiments : [];
    if (!runs.length) {
      el['nearest-wrap'].innerHTML = '';
      return;
    }
    var rows = runs.map(function (r) {
      var dilStr = r.diluent_regime === 'Air' ? 'N₂ balance' : (r.diluent_regime === 'CO2' ? (r.co2_mol_frac * 100).toFixed(0) + '% CO₂' : (r.he_mol_frac * 100).toFixed(0) + '% He');
      var kStr = r.burning_rate_mm2_s != null ? r.burning_rate_mm2_s.toFixed(3) : '—';
      return '<tr>' +
        '<td><a class="lnk" href="data.html?exp=PSI-69&pick=' + encodeURIComponent(r.record_pk) + '#s-explorer">FLEX-' + esc(r.test_id) + '</a></td>' +
        '<td>' + esc(r.fuel) + '</td>' +
        '<td>' + esc((r.o2_mol_frac * 100).toFixed(1)) + '% O₂ · ' + esc(dilStr) + '</td>' +
        '<td class="n">' + esc((r.pressure_mmhg / 760).toFixed(2)) + ' atm</td>' +
        '<td class="n">' + esc(r.droplet_initial_diameter_mm.toFixed(2)) + ' mm</td>' +
        '<td>' + esc(r.test_end) + '</td>' +
        '<td class="n">' + esc(kStr) + '</td>' +
        '<td class="n"><code>' + esc(r.standardized_distance.toFixed(3)) + ' std</code></td>' +
        '</tr>';
    }).join('');
    el['nearest-wrap'].innerHTML =
      '<div class="fp-card"><h3 class="fp-subhead">Nearest real NASA PSI-69 tests (reference evidence, distinct from model predictions)</h3>' +
      '<p class="fp-meta">Distance reflects standardized Euclidean proximity in pre-test space. Nearby runs provide experimental context; they do not by themselves prove causal validity or cabin fire safety.</p>' +
      '<div class="scroll"><table class="dt"><thead><tr><th>Test</th><th>Fuel</th><th>Gas</th><th class="n">Pressure</th><th class="n">d₀</th><th>Measured outcome</th><th class="n">Measured K</th><th class="n">Distance</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div></div>';
  }

  function paintAuditPanel() {
    var d = S.prediction;
    var le = (d && d.local_explanations) || null;
    if (!le) {
      el['audit-panel'].innerHTML =
        '<span class="fp-badge warn">Explanation audit · Raw-6 Shapley DISABLED</span>' +
        '<h3>Why black-box Shapley bars are hidden</h3>' +
        '<p class="fp-meta">Evaluating an active supported condition shows exact additive transformed-feature terms in linear/logit space. Independent raw-6 Shapley swaps across all empirical FLEX rows generate physically invalid gas balances, negative implied N₂, zero-test CO₂+He mixtures, and out-of-envelope conditions—so they are withheld.</p>';
      return;
    }
    var aud = le.counterfactual_audit || {};
    var regTf = (le.transformed_feature_contributions && le.transformed_feature_contributions.burning_rate_mm2_s) || {};
    var contribs = (regTf.contributions || []).slice(0, 6);
    var maxAbs = Math.max.apply(null, contribs.map(function (c) { return Math.abs(c.linear_contribution); }).concat([0.05]));
    var barsHtml = contribs.map(function (c) {
      var w = Math.min(100, Math.round(Math.abs(c.linear_contribution) / maxAbs * 100));
      var cls = c.linear_contribution >= 0 ? 'pos' : 'neg';
      var sign = c.linear_contribution >= 0 ? '+' : '';
      return '<div class="fp-bar-row"><code>' + esc(c.feature) + '</code>' +
        '<div class="fp-bar-track"><div class="fp-bar-fill ' + cls + '" style="width:' + w + '%"></div></div>' +
        '<span style="text-align:right"><code>' + sign + c.linear_contribution.toFixed(3) + '</code></span></div>';
    }).join('');
    el['audit-panel'].innerHTML =
      '<span class="fp-badge bad">Raw-6 Shapley Audit · DISABLED_UNRELIABLE</span>' +
      '<h3>Model structure &amp; counterfactual audit</h3>' +
      '<p class="fp-meta">Across <code>' + esc(aud.total_coalition_evals) + '</code> empirical 2⁶ raw-6 Shapley coalitions for this point: ' +
      '<strong>' + esc(aud.any_violation_count) + ' (' + esc((aud.any_violation_share * 100).toFixed(1)) + '%)</strong> violated domain or physical bounds ' +
      '(neg N₂: <code>' + esc(aud.negative_n2_count) + '</code>, gas sum: <code>' + esc(aud.gas_sum_violation_count) + '</code>, mixed CO₂+He: <code>' + esc(aud.mixed_co2_he_count) + '</code>, OOD regime/bounds: <code>' + esc(aud.unsupported_regime_or_bounds_count) + '</code>). ' +
      'Misleading Shapley bar charts are therefore disabled.</p>' +
      '<p class="fp-meta"><strong>Validated ridge_phys8 transformed-feature shifts (mm²/s relative to intercept ' + esc(regTf.intercept != null ? regTf.intercept.toFixed(3) : '—') + '):</strong></p>' +
      barsHtml;
  }

  function paintOofPanel() {
    var sc = S.schema || {};
    var regCv = (sc.models && sc.models.burning_rate_regression && sc.models.burning_rate_regression.cv_group_atm_p) || {};
    var clfCv = (sc.models && sc.models.extinction_classification && sc.models.extinction_classification.cv_group_atm_p) || {};
    var cm = clfCv.confusion_matrix || {};
    el['oof-panel'].innerHTML =
      '<span class="fp-badge warn">Measured vs Predicted · Out-of-Fold Rows Unavailable</span>' +
      '<h3>Why individual predicted-vs-measured scatter is omitted</h3>' +
      '<p class="fp-meta">' + esc(sc.oof_unavailable_reason || 'Individual out-of-fold row predictions are not stored in the signed model/eval artifacts. Plotting full-sample training predictions as test generalization would misrepresent model error and is intentionally withheld.') + '</p>' +
      '<p class="fp-meta"><strong>Verified grouped-CV error summaries (atm+P, n=257 reg / 261 clf):</strong><br>' +
      '• <code>ridge_phys8</code> MAE: <code>' + esc(regCv.mae) + '</code> · RMSE: <code>' + esc(regCv.rmse) + ' mm²/s</code> · Fold R²: <code>' + esc(regCv.fold_r2 ? Math.min.apply(null, regCv.fold_r2) + ' .. ' + Math.max.apply(null, regCv.fold_r2) : '—') + '</code><br>' +
      '• <code>logit_phys10</code> CM: TP=<code>' + esc(cm.tp) + '</code>, FP=<code>' + esc(cm.fp) + '</code>, TN=<code>' + esc(cm.tn) + '</code>, FN=<code>' + esc(cm.fn) + '</code> · Fold AUC: <code>' + esc(clfCv.fold_auc ? Math.min.apply(null, clfCv.fold_auc) + ' .. ' + Math.max.apply(null, clfCv.fold_auc) : '—') + '</code></p>';
  }

  function cellColor(cell, metric) {
    if (!cell.supported) return 'url(#fp-hatch)';
    if (metric === 'extinction_score') {
      var s = Math.max(0, Math.min(1, Number(cell.extinction_score || 0)));
      var r = Math.round(43 + (215 - 43) * s);
      var g = Math.round(126 + (135 - 126) * (1 - s));
      var b = Math.round(161 * (1 - s) + 70 * s);
      return 'rgb(' + r + ',' + g + ',' + b + ')';
    }
    var k = Math.max(0, Math.min(1.4, Number(cell.burning_rate_mm2_s || 0)));
    var t = k / 1.4;
    var rk = Math.round(28 + (232 - 28) * t);
    var gk = Math.round(68 + (165 - 68) * t);
    var bk = Math.round(104 + (72 - 104) * (1 - t));
    return 'rgb(' + rk + ',' + gk + ',' + bk + ')';
  }

  function paintMap() {
    if (S.mapLoading && !S.mapData) {
      el['map-canvas'].innerHTML = '<p class="small">Computing joint support grid across O₂–diluent slice...</p>';
      el['map-inspector'].innerHTML = '<p class="fp-meta">Select any grid tile or real PSI-69 point to inspect exact support status and coordinates.</p>';
      return;
    }
    if (S.mapError) {
      el['map-canvas'].innerHTML = '<div class="fp-errbox">' + esc(S.mapError) + '</div>';
      return;
    }
    var md = S.mapData;
    if (!md || !md.cells) return;
    var xs = md.slice.x_axis.values;
    var ys = md.slice.y_axis.values;
    var yKey = md.slice.y_axis.key;
    var W = 600, H = 310, ml = 56, mr = 16, mt = 14, mb = 44;
    var pw = W - ml - mr, ph = H - mt - mb;
    var cw = pw / xs.length, ch = ph / ys.length;

    var cellsSvg = '';
    for (var row = 0; row < ys.length; row++) {
      for (var col = 0; col < xs.length; col++) {
        var idx = row * xs.length + col;
        var cell = md.cells[idx];
        var xPos = ml + col * cw;
        var yPos = mt + (ys.length - 1 - row) * ch;
        var fill = cellColor(cell, S.mapMetric);
        cellsSvg += '<rect class="fp-map-cell" tabindex="0" role="button" data-cell="' + idx + '" x="' + xPos.toFixed(1) + '" y="' + yPos.toFixed(1) + '" width="' + (cw - 1).toFixed(1) + '" height="' + (ch - 1).toFixed(1) + '" fill="' + fill + '" stroke="' + (cell.supported ? 'rgba(255,255,255,0.14)' : 'rgba(232,180,92,0.22)') + '" aria-label="Grid O2 ' + (cell.o2_mol_frac * 100).toFixed(1) + ' percent, ' + (cell.supported ? 'supported' : 'not supported') + '"/>';
      }
    }

    var xMin = xs[0], xMax = xs[xs.length - 1], yMin = ys[0], yMax = ys[ys.length - 1];
    var ptsSvg = '';
    (md.real_experiments || []).forEach(function (pt, i) {
      var rx = ml + ((pt.o2_mol_frac - xMin) / (xMax - xMin || 1)) * pw;
      var ry = mt + ph - ((pt.y_value - yMin) / (yMax - yMin || 1)) * ph;
      if (rx < ml - 4 || rx > ml + pw + 4 || ry < mt - 4 || ry > mt + ph + 4) return;
      var colMap = { Extinction: '#4cc9f0', Disruption: '#f087c8', Completion: '#98e07c' };
      var fillPt = colMap[pt.test_end] || '#f1eee8';
      var op = pt.within_slice_window ? '1' : '0.42';
      ptsSvg += '<circle class="fp-map-cell" tabindex="0" role="button" data-run="' + i + '" cx="' + rx.toFixed(1) + '" cy="' + ry.toFixed(1) + '" r="' + (pt.within_slice_window ? '4.5' : '3.2') + '" fill="' + fillPt + '" fill-opacity="' + op + '" stroke="#0b0b0c" stroke-width="1.3" aria-label="Real NASA FLEX-' + esc(pt.test_id) + ' ' + esc(pt.test_end) + '"/>';
    });

    var xTicks = [0, Math.floor(xs.length / 2), xs.length - 1].map(function (i) {
      var tx = ml + (i + 0.5) * cw;
      return '<text x="' + tx.toFixed(1) + '" y="' + (mt + ph + 16) + '" fill="#8f8b84" font-size="11" text-anchor="middle">' + (xs[i] * 100).toFixed(0) + '%</text>';
    }).join('');
    var yTicks = [0, ys.length - 1].map(function (i) {
      var ty = mt + (ys.length - 1 - i + 0.5) * ch + 4;
      var valTxt = yKey === 'pressure_atm' ? ys[i].toFixed(1) + ' atm' : (ys[i] * 100).toFixed(0) + '%';
      return '<text x="' + (ml - 6) + '" y="' + ty.toFixed(1) + '" fill="#8f8b84" font-size="11" text-anchor="end">' + valTxt + '</text>';
    }).join('');

    el['map-canvas'].innerHTML =
      '<svg class="fp-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="O2 versus ' + esc(md.slice.y_axis.label) + ' condition map">' +
      '<defs><pattern id="fp-hatch" width="6" height="6" patternTransform="rotate(45 0 0)" patternUnits="userSpaceOnUse"><rect width="6" height="6" fill="#101012"/><line x1="0" y1="0" x2="0" y2="6" stroke="rgba(232,180,92,0.22)" stroke-width="2"/></pattern></defs>' +
      cellsSvg + ptsSvg + xTicks + yTicks +
      '<text x="' + (ml + pw / 2) + '" y="' + (H - 6) + '" fill="#c9d3de" font-size="12" text-anchor="middle">Initial O₂ (% mol) · ' + esc(md.slice.fuel) + ' · d₀=' + esc(md.slice.droplet_initial_diameter_mm) + ' mm</text>' +
      '</svg>' +
      '<div class="fp-map-legend">' +
      '<span><i class="fp-sw" style="background:repeating-linear-gradient(45deg,#101012,#101012 3px,rgba(232,180,92,0.35) 3px,rgba(232,180,92,0.35) 5px)"></i>NOT_SUPPORTED (' + esc(md.masked_cells) + '/' + esc(md.total_cells) + ' masked, zero interpolation)</span>' +
      '<span><i class="fp-sw" style="background:#2b7ea1"></i>Supported model estimate (' + esc(md.supported_cells) + ' cells)</span>' +
      '<span><i class="fp-sw" style="border-radius:50%;background:#4cc9f0"></i>Measured PSI-69 Extinction</span>' +
      '<span><i class="fp-sw" style="border-radius:50%;background:#f087c8"></i>Measured Disruption</span>' +
      '<span><i class="fp-sw" style="border-radius:50%;background:#98e07c"></i>Measured Completion</span>' +
      '</div>';

    el['map-canvas'].querySelectorAll('[data-cell],[data-run]').forEach(function (node) {
      function inspect() {
        if (node.dataset.cell != null) paintMapInspector({ kind: 'cell', item: md.cells[Number(node.dataset.cell)], md: md });
        else if (node.dataset.run != null) paintMapInspector({ kind: 'run', item: md.real_experiments[Number(node.dataset.run)], md: md });
      }
      node.addEventListener('mouseenter', inspect);
      node.addEventListener('focus', inspect);
      node.addEventListener('click', inspect);
    });
    paintMapInspector(null);
  }

  function paintMapInspector(sel) {
    if (!sel || !sel.item) {
      el['map-inspector'].innerHTML =
        '<span class="fp-badge">Map Inspector</span>' +
        '<h3>Model surface vs measured dots</h3>' +
        '<p class="fp-meta">Hover or tab-focus any tile or circular dot to separate joint-supported model predictions, masked gaps, and real NASA PSI-69 runs.</p>';
      return;
    }
    if (sel.kind === 'run') {
      var r = sel.item;
      el['map-inspector'].innerHTML =
        '<span class="fp-badge ok">Measured NASA PSI-69 Test</span>' +
        '<h3>FLEX-' + esc(r.test_id) + ' (' + esc(r.test_end) + ')</h3>' +
        '<p class="fp-meta">O₂: <code>' + (r.o2_mol_frac * 100).toFixed(1) + '%</code> · CO₂: <code>' + (r.co2_mol_frac * 100).toFixed(1) + '%</code> · He: <code>' + (r.he_mol_frac * 100).toFixed(1) + '%</code><br>' +
        'P: <code>' + r.pressure_atm.toFixed(2) + ' atm</code> · d₀: <code>' + r.droplet_initial_diameter_mm.toFixed(2) + ' mm</code><br>' +
        'Measured K: <code>' + (r.burning_rate_mm2_s != null ? r.burning_rate_mm2_s.toFixed(3) + ' mm²/s' : 'missing') + '</code></p>' +
        '<a class="lnk" href="data.html?exp=PSI-69&pick=' + encodeURIComponent(r.record_pk) + '#s-explorer">Inspect CSV row in Data Explorer ↗</a>';
      return;
    }
    var c = sel.item;
    el['map-inspector'].innerHTML =
      '<span class="fp-badge ' + (c.supported ? 'ok' : 'bad') + '">' + (c.supported ? 'Model tile (SUPPORTED)' : 'Masked cell (NOT_SUPPORTED)') + '</span>' +
      '<h3>' + (c.o2_mol_frac * 100).toFixed(1) + '% O₂ · ' + esc(sel.md.slice.y_axis.key === 'pressure_atm' ? c.pressure_atm + ' atm' : (c.y_value * 100).toFixed(0) + '% ' + sel.md.slice.diluent_regime) + '</h3>' +
      (c.supported
        ? '<p class="fp-meta">Estimated K (<code>ridge_phys8</code>): <strong>' + esc(c.burning_rate_mm2_s.toFixed(3)) + ' mm²/s</strong><br>Extinction score (<code>logit_phys10</code>): <strong>' + esc(c.extinction_score.toFixed(3)) + '</strong></p>'
        : '<p class="fp-meta"><strong>Blocked:</strong> ' + esc((c.reasons || []).join('; ')) + '</p>');
  }

  function paintEvalPanel() {
    var sc = S.schema;
    if (!sc) {
      el['eval-body'].innerHTML = '<p class="fp-meta">' + esc(S.schemaError || 'Loading model schema and benchmarks...') + '</p>';
      return;
    }
    if (S.evalTab === 'reconcile') {
      var rec = S.reconciliation;
      if (!rec) {
        el['eval-body'].innerHTML = '<p class="fp-meta">Reconciliation summary unavailable.</p>';
        return;
      }
      var sum = rec.reconciliation_summary || {};
      var extraLabels = Array.isArray(sum.table_ix_only_labels) ? sum.table_ix_only_labels.join(', ') : 'FLEX-216, FLEX-230';
      el['eval-body'].innerHTML =
        '<span class="fp-badge">Table IX vs PSI-69 CSV Provenance</span>' +
        '<h3>' + esc(sum.psi69_csv_rows) + ' PSI-69 CSV rows vs ' + esc(sum.table_ix_rows) + ' NASA TP Table IX entries (' + esc(sum.psi69_helium_runs) + ' vs ' + esc(sum.table_ix_helium_runs) + ' He)</h3>' +
        '<p class="fp-meta">PSI-69 CSV matches ' + esc(sum.matched_shared_rows) + ' shared core rows (<code>' + esc(sum.shared_row_value_mismatches) + '</code> value mismatches). ' +
        'The ' + esc(sum.table_ix_only_rows) + ' Table IX-only rows (<code>' + esc(extraLabels) + '</code>) are tracked with source provenance rather than silently inserted into core tables.</p>' +
        '<p class="fp-meta"><strong>Tracked reconciliation details:</strong> Helium difference (' + esc(sum.psi69_helium_runs) + ' vs ' + esc(sum.table_ix_helium_runs) + ') explained by <code>' + esc(sum.helium_difference_explained_by || 'FLEX-230') + '</code> · FLEX-114 P=0 anomaly retained as documented CSV corruption (excluded from model eligibility).</p>';
      return;
    }

    if (S.evalTab === 'structure') {
      var regSt = (sc.models && sc.models.burning_rate_regression && sc.models.burning_rate_regression.structure) || {};
      var clfSt = (sc.models && sc.models.extinction_classification && sc.models.extinction_classification.structure) || {};
      function tblFor(st) {
        var rows = (st.coefficients || []).map(function (c) {
          return '<tr><td><code>' + esc(c.feature) + '</code></td><td class="n"><code>' + c.standardized_weight.toFixed(4) + '</code></td><td class="n">' + c.train_mean.toFixed(4) + '</td><td class="n">' + c.train_std.toFixed(4) + '</td></tr>';
        }).join('');
        return '<div style="margin-bottom:16px"><h4>' + esc(st.name) + ' (intercept = <code>' + esc(st.intercept) + '</code>, L2 = <code>' + esc(st.l2_penalty) + '</code>, n = <code>' + esc(st.n_train) + '</code>)</h4>' +
          '<p class="fp-meta"><code>' + esc(st.equation_hint) + '</code></p>' +
          '<div class="scroll"><table class="dt"><thead><tr><th>Transformed feature</th><th class="n">Std weight</th><th class="n">Train mean</th><th class="n">Train std</th></tr></thead><tbody>' + rows + '</tbody></table></div></div>';
      }
      el['eval-body'].innerHTML = tblFor(regSt) + tblFor(clfSt);
      return;
    }

    var elg = sc.eligibility || {};
    var eb = sc.evaluation_benchmarks || {};
    var bm = eb.benchmarks || {};
    var regAtm = (bm.regression_group_atm_p && bm.regression_group_atm_p.models) || {};
    var regFuel = (bm.regression_group_fuel_atm_p && bm.regression_group_fuel_atm_p.models) || {};
    var clfAtm = (bm.classification_group_atm_p && bm.classification_group_atm_p.models) || {};
    var clfFuel = (bm.classification_group_fuel_atm_p && bm.classification_group_fuel_atm_p.models) || {};
    var regRows = Object.keys(regAtm).map(function (m) {
      var a = regAtm[m], f = regFuel[m] || {};
      return '<tr><td><code>' + esc(m) + '</code></td><td class="n">' + a.mae + '</td><td class="n">' + a.rmse + '</td><td class="n">' + a.r2 + ' (±' + a.fold_r2_std + ')</td><td class="n">' + (f.r2 != null ? f.r2 + ' (±' + f.fold_r2_std + ')' : '—') + '</td></tr>';
    }).join('');
    var clfRows = Object.keys(clfAtm).map(function (m) {
      var a = clfAtm[m], f = clfFuel[m] || {};
      return '<tr><td><code>' + esc(m) + '</code></td><td class="n">' + a.roc_auc + ' (±' + a.fold_auc_std + ')</td><td class="n">' + a.brier_score + '</td><td class="n">' + a.confusion_matrix.fp + '/' + a.negative_non_extinction + '</td><td class="n">' + (f.roc_auc != null ? f.roc_auc : '—') + '</td></tr>';
    }).join('');
    var exclTxt = (elg.regression_excluded || []).map(function (x) { return 'FLEX-' + x.test_id + ' (' + x.reason + ')'; }).join(', ');

    el['eval-body'].innerHTML =
      '<span class="fp-badge">Eligibility &amp; Candidate Model Benchmarks (artifact-fed)</span>' +
      '<p class="fp-meta"><strong>Rows:</strong> <code>' + esc(elg.psi69_total_rows) + '</code> total PSI-69 · <code>' + esc(elg.classification_usable_rows) + '</code> classification usable · <code>' + esc(elg.regression_usable_rows) + '</code> regression usable. Post-test leakage columns excluded. Excluded: ' + esc(exclTxt) + '.</p>' +
      '<p class="fp-meta"><strong>Grouping caveat:</strong> ' + esc(eb.grouping_note || '') + ' Model selection evidence over PSI-69 CV, NOT independent external validation.</p>' +
      '<h4 style="margin:10px 0 4px">A · Burning-rate constant candidate comparison (n=257)</h4>' +
      '<div class="scroll"><table class="dt"><thead><tr><th>Candidate</th><th class="n">atm+P MAE</th><th class="n">atm+P RMSE</th><th class="n">atm+P R² (fold std)</th><th class="n">fuel+atm+P R²</th></tr></thead><tbody>' + regRows + '</tbody></table></div>' +
      '<h4 style="margin:14px 0 4px">B · Extinction classification candidate comparison (n=261)</h4>' +
      '<div class="scroll"><table class="dt"><thead><tr><th>Candidate</th><th class="n">atm+P AUC (fold std)</th><th class="n">Brier</th><th class="n">Non-Extinction FP</th><th class="n">fuel+atm+P AUC</th></tr></thead><tbody>' + clfRows + '</tbody></table></div>';
  }

  function bootstrap() {
    build();
    var check = validateClientCondition(S);
    schedulePredict(true);

    if (root.FF.api && typeof root.FF.api.flexPredictSchema === 'function') {
      root.FF.api.flexPredictSchema().then(function (env) {
        S.schema = env && env.data ? env.data : null;
        paintOofPanel();
        paintEvalPanel();
        if (S.uiState === 'ok') paintPrediction();
      }).catch(function (err) {
        if (err && (err.httpStatus === 503 || err.status === 'FLEX_PREDICTOR_UNAVAILABLE')) {
          S.schemaUnavailable = true;
          S.uiState = 'unavailable';
          S.predError = err.message;
          paintPrediction();
        }
        S.schemaError = (err && err.message) || 'Schema unavailable';
        paintEvalPanel();
      });
    }
    if (root.FF.api && typeof root.FF.api.flexReconciliation === 'function') {
      root.FF.api.flexReconciliation().then(function (env) {
        S.reconciliation = env && env.data ? env.data : null;
        if (S.evalTab === 'reconcile') paintEvalPanel();
      }).catch(function () {});
    }
    fetchMap(check);
  }

  bootstrap();
})(typeof window !== 'undefined' ? window : globalThis);
