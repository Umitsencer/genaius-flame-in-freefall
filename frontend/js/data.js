/* Data, 24-Study Catalog, Separate CFI/SAFFIRE Modules & Document Passages wired directly to GenAIus backend. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function safeUrl(u) {
    if (!u || typeof u !== 'string') return null;
    try {
      var parsed = new URL(u, window.location.href);
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') return parsed.href;
    } catch (_e) {
      return null;
    }
    return null;
  }

  function statusChip(stCode) {
    var code = String(stCode || 'missing').toLowerCase();
    var cls = 'st-none';
    if (code === 'measured') cls = 'st-measured';
    else if (code === 'approximate') cls = 'st-approx';
    else if (code === 'invalid' || code === 'above_limit' || code === 'below_limit') cls = 'st-invalid';
    else if (code === 'meaning_unverified') cls = 'st-range';
    return '<span class="st ' + cls + '">' + esc(code.replace(/_/g, ' ')) + '</span>';
  }

  var DEFAULT_FIELD = {
    'PSI-69': { field_name: 'burning_rate_mm2_s', unit: 'mm²/s' },
    'PSI-25': { field_name: 'final_co_ppm', unit: 'ppm' }
  };

  var S = {
    exp: 'all',
    fuel: '',
    q: '',
    o2: [10, 40],
    p: [0.2, 3.2],
    o2Active: false,
    pActive: false,
    fieldName: 'burning_rate_mm2_s',
    unit: 'mm²/s',
    includeApprox: false,
    showAll: false,
    pick: null,
    cmp: [],
    schema: null,
    searchData: null,
    analyticsData: null,
    detailData: null,
    compareData: null,
    catFilters: null,
    catData: null,
    cfiSchema: null,
    cfiData: null,
    safSchema: null,
    safData: null,
    docsData: null,
    seq: { cat: 0, core: 0, an: 0, det: 0, cmp: 0, docs: 0 },
    ctrl: {}
  };

  function nextReq(key) {
    S.seq[key] = (S.seq[key] || 0) + 1;
    if (S.ctrl[key] && typeof S.ctrl[key].abort === 'function') {
      S.ctrl[key].abort();
    }
    S.ctrl[key] = typeof AbortController !== 'undefined' ? new AbortController() : null;
    return {
      seq: S.seq[key],
      opts: S.ctrl[key] ? { signal: S.ctrl[key].signal } : undefined
    };
  }

  var rsO2, rsP;

  var share = FF.api.makeShare(
    {
      exp: ['s', 'all'],
      fuel: ['s', ''],
      q: ['s', ''],
      o2: ['a', [10, 40]],
      p: ['a', [0.2, 3.2]],
      o2Active: ['b', false],
      pActive: ['b', false],
      includeApprox: ['b', false],
      pick: ['s', '']
    },
    function () { return S; },
    function (d) {
      Object.assign(S, d);
      if (!S.pick) S.pick = null;
    }
  );

  function getParam(name) {
    return new URLSearchParams(window.location.search).get(name);
  }

  function applyQueryParams() {
    var exp = getParam('exp');
    var pick = getParam('pick');
    var q = getParam('q');
    var docFlag = getParam('doc');
    if (exp && (exp === 'PSI-25' || exp === 'PSI-69' || exp === 'all')) {
      S.exp = exp;
    }
    if (pick) S.pick = pick;
    if (q && docFlag) {
      $('doc-q').value = q;
      if (exp === 'PSI-25' || exp === 'PSI-69') $('doc-exp').value = exp;
    } else if (q) {
      $('cat-q').value = q;
    }
  }

  function updateSidebarOptions() {
    if (!S.schema || !Array.isArray(S.schema.datasets)) return;
    var datasets = S.schema.datasets;
    var fuels = [];
    var fields = [];
    datasets.forEach(function (ds) {
      if (S.exp === 'all' || S.exp === ds.id) {
        (ds.fuels || []).forEach(function (f) {
          if (fuels.indexOf(f) < 0) fuels.push(f);
        });
      }
      var targetInv = S.exp === 'all' ? 'PSI-69' : S.exp;
      if (ds.id === targetInv) {
        fields = ds.fields || [];
      }
    });
    fuels.sort();
    $('f-fuel').innerHTML = '<option value="">All fuels &amp; materials</option>' +
      fuels.map(function (f) { return '<option value="' + esc(f) + '">' + esc(f) + '</option>'; }).join('');
    $('f-fuel').value = fuels.indexOf(S.fuel) >= 0 ? S.fuel : '';

    var prevKey = S.fieldName + '|' + S.unit;
    var opts = [];
    fields.forEach(function (fld) {
      var u = (fld.units && fld.units[0]) || '';
      opts.push({ key: fld.name + '|' + u, field: fld.name, unit: u, label: fld.label + (u ? ' (' + u + ')' : '') });
    });
    $('f-field').innerHTML = opts.map(function (o) {
      return '<option value="' + esc(o.key) + '">' + esc(o.label) + '</option>';
    }).join('');
    var hasPrev = opts.some(function (o) { return o.key === prevKey; });
    if (hasPrev) {
      $('f-field').value = prevKey;
    } else if (opts.length) {
      var targetInv = S.exp === 'all' ? 'PSI-69' : S.exp;
      var def = DEFAULT_FIELD[targetInv];
      var match = def && opts.filter(function (o) { return o.field === def.field_name; })[0];
      var chosen = match || opts[0];
      S.fieldName = chosen.field;
      S.unit = chosen.unit;
      $('f-field').value = chosen.key;
    }
  }

  function buildNumericFilters() {
    var filters = [];
    if (S.o2Active) {
      var o2Field = S.exp === 'PSI-25' ? 'initial_o2_vol_pct' : 'initial_o2_flex_mol_pct';
      if (S.exp === 'PSI-25' || S.exp === 'PSI-69') {
        filters.push({
          field_name: o2Field,
          unit: S.exp === 'PSI-25' ? '% vol' : '% mol',
          min_value: S.o2[0],
          max_value: S.o2[1]
        });
      }
    }
    if (S.pActive && (S.exp === 'PSI-69' || S.exp === 'all')) {
      filters.push({
        field_name: 'ambient_pressure_kpa',
        unit: 'atm',
        min_value: S.p[0],
        max_value: S.p[1]
      });
    }
    return filters;
  }

  function buildSearchPayload() {
    return {
      investigation_id: S.exp === 'all' ? null : S.exp,
      fuel: S.fuel || null,
      numeric_filters: buildNumericFilters(),
      limit: 100,
      offset: 0
    };
  }

  function buildAnalyticsPayload(targetInv) {
    return {
      investigation_id: targetInv,
      field_name: S.fieldName,
      unit: S.unit,
      fuel: S.fuel || null,
      numeric_filters: buildNumericFilters(),
      include_approximate: S.includeApprox
    };
  }

  function paintHeaderFacts() {
    var totalCore = 0;
    if (S.schema && Array.isArray(S.schema.datasets)) {
      S.schema.datasets.forEach(function (d) { totalCore += d.run_count || 0; });
    }
    var matched = S.searchData ? S.searchData.total_runs : '—';
    var catTotal = S.catFilters ? S.catFilters.total_studies : 24;
    var chunks = S.schema ? S.schema.chunk_count : 503;
    $('ov').innerHTML =
      '<span><b>' + esc(catTotal) + '</b>catalogued NASA PSI studies</span>' +
      '<span><b>' + esc(matched) + ' / ' + esc(totalCore) + '</b>matching core runs (PSI-25 + PSI-69)</span>' +
      '<span><b>' + esc(chunks) + '</b>indexed report passages</span>' +
      '<span><b>' + esc(S.cmp.length) + ' / 4</b>selected to compare</span>';
  }

  /* ---- 24-Study Catalog ---- */
  function loadCatalog() {
    if (!FF.api) return;
    $('cat-status').innerHTML = '<p class="small">Searching 24-study catalog...</p>';
    var coreVal = $('cat-core').value;
    var payload = {
      query: $('cat-q').value.trim() || null,
      project_type: $('cat-type').value || null,
      sub_research_area: $('cat-area').value || null,
      queryable_in_core: coreVal === 'true' ? true : (coreVal === 'false' ? false : null),
      top_k: 24
    };
    var req = nextReq('cat');
    FF.api.catalogSearch(payload, req.opts).then(function (env) {
      if (req.seq !== S.seq.cat) return;
      S.catData = env && env.data ? env.data : null;
      paintCatalog();
    }).catch(function (err) {
      if (err && err.name === 'AbortError') return;
      if (req.seq !== S.seq.cat) return;
      $('cat-status').innerHTML = '<div class="callout gap"><strong>Catalog unavailable:</strong> ' + esc((err && err.message) || 'Error') + '</div>';
    });
  }

  function paintCatalog() {
    var d = S.catData;
    if (!d) return;
    var hits = d.hits || [];
    $('cat-status').innerHTML = '<p class="stat">Showing <b>' + hits.length + '</b> of <b>' + (d.total_catalog_studies || 24) +
      '</b> catalogued studies (' + esc(d.ranking_algorithm || '') + '). ' + esc(d.score_disclaimer || '') + '</p>';
    if (!hits.length) {
      $('catalog-list').innerHTML = '<p class="empty">No catalogued NASA PSI studies match your filter criteria.</p>';
      return;
    }
    $('catalog-list').innerHTML = '<div class="card-grid">' + hits.map(function (h) {
      var e = h.entry || {};
      var sup = e.support || {};
      var tierLabel = sup.support_tier || (sup.queryable_in_core ? 'queryable_in_core' : 'reviewed');
      var doiHref = safeUrl(e.doi ? ('https://doi.org/' + e.doi) : e.catalog_url);
      var deepBtn = '';
      if (e.psi_id === 'PSI-25' || e.psi_id === 'PSI-69') {
        deepBtn = '<button type="button" class="ghost sm" data-open-core="' + esc(e.psi_id) + '">Filter Core Explorer</button>';
      } else if (e.psi_id === 'PSI-39') {
        deepBtn = '<a class="ghost sm lk" href="#s-cfi">Open CFI Module</a>';
      } else if (e.psi_id === 'PSI-99') {
        deepBtn = '<a class="ghost sm lk" href="#s-saffire">Open SAFFIRE-II Cards</a>';
      }
      return '<article class="ecard">' +
        '<div class="ecard-head"><span class="ecard-id">' + esc(e.psi_id) + (e.acronym ? ' · ' + esc(e.acronym) : '') + '</span>' +
        '<span class="st ' + (sup.queryable_in_core ? 'st-measured' : 'st-approx') + '">' + esc(tierLabel) + '</span></div>' +
        '<div class="ecard-title">' + esc(e.title) + '</div>' +
        '<div class="ecard-meta">' + esc((e.project_type || '') + (e.sub_research_area ? ' · ' + e.sub_research_area : '')) + '</div>' +
        '<div class="ecard-reason">' + esc(h.ranking_reason || 'Catalog browse order') + '</div>' +
        (e.limitations ? '<div class="ecard-limit">' + esc(e.limitations) + '</div>' : '') +
        '<div class="ecard-act">' + deepBtn +
        (doiHref ? '<a class="ghost sm lk" href="' + esc(doiHref) + '" target="_blank" rel="noopener noreferrer">NASA / DOI ↗</a>' : '') +
        '</div></article>';
    }).join('') + '</div>';
  }

  /* ---- Core Search + Detail + Compare + Analytics/Export ---- */
  function loadCore() {
    if (!FF.api) return;
    $('rows').innerHTML = '<p class="small">Loading core records from /api/search...</p>';
    var coreReq = nextReq('core');
    FF.api.search(buildSearchPayload(), coreReq.opts).then(function (env) {
      if (coreReq.seq !== S.seq.core) return;
      S.searchData = env && env.data ? env.data : null;
      if (FF.chat && typeof FF.chat.setContext === 'function') {
        FF.chat.setContext({
          investigation_id: S.exp === 'all' ? null : S.exp,
          fuel: S.fuel || null,
          numeric_filters: buildNumericFilters(),
          include_approximate: Boolean(S.includeApprox),
          uiLabel: 'Explorer (' + (S.exp === 'all' ? 'PSI-25 + PSI-69' : S.exp) + (S.fuel ? ' · ' + S.fuel : '') + ')'
        }, { clearOnChange: false });
      }
      paintHeaderFacts();
      paintRows();
    }).catch(function (err) {
      if (err && err.name === 'AbortError') return;
      if (coreReq.seq !== S.seq.core) return;
      $('rows').innerHTML = '<div class="callout gap"><strong>Search failed:</strong> ' + esc((err && err.message) || 'Error') + '</div>';
    });

    if (S.exp === 'PSI-25' || S.exp === 'PSI-69') {
      $('quality').innerHTML = '<p class="small">Loading descriptive summary from /api/analytics...</p>';
      var anReq = nextReq('an');
      FF.api.analytics(buildAnalyticsPayload(S.exp), anReq.opts).then(function (env) {
        if (anReq.seq !== S.seq.an) return;
        S.analyticsData = env && env.data ? env.data : null;
        paintAnalytics();
      }).catch(function (err) {
        if (err && err.name === 'AbortError') return;
        if (anReq.seq !== S.seq.an) return;
        $('quality').innerHTML = '<div class="callout gap"><strong>Analytics failed:</strong> ' + esc((err && err.message) || 'Error') + '</div>';
      });
    } else {
      if (S.ctrl.an && typeof S.ctrl.an.abort === 'function') S.ctrl.an.abort();
      S.seq.an += 1;
      S.analyticsData = null;
      paintAnalytics();
    }

    if (S.pick) {
      loadDetail(S.pick);
    }
  }

  function loadDetail(pk) {
    if (!pk || !FF.api) {
      $('picked').hidden = true;
      $('picked').innerHTML = '';
      return;
    }
    S.pick = pk;
    $('picked').hidden = false;
    $('picked').innerHTML = '<p class="small">Fetching full row provenance for ' + esc(pk) + '...</p>';
    var detReq = nextReq('det');
    FF.api.detail({ record_pk: pk }, detReq.opts).then(function (env) {
      if (detReq.seq !== S.seq.det) return;
      S.detailData = env && env.data ? env.data : null;
      paintDetail();
    }).catch(function (err) {
      if (err && err.name === 'AbortError') return;
      if (detReq.seq !== S.seq.det) return;
      $('picked').innerHTML = '<div class="callout gap"><strong>Row detail failed:</strong> ' + esc((err && err.message) || 'Error') + '</div>';
    });
  }

  function paintDetail() {
    var d = S.detailData;
    var box = $('picked');
    if (!d) { box.hidden = true; return; }
    box.hidden = false;
    var mKeys = Object.keys(d.measurements || {}).sort();
    var mRows = mKeys.map(function (k) {
      var m = d.measurements[k];
      var norm = m.normalized_value != null ? (m.normalized_value + ' ' + (m.normalized_unit || '')) : '—';
      return '<tr><td>' + esc(m.field_name) + '</td><td class="v-raw">' + esc(m.raw_value || '—') + '</td><td>' + statusChip(m.status) + '</td><td class="cellv">' + esc(norm) + '</td><td>' + esc(m.provenance || '') + '</td></tr>';
    }).join('');
    var src = d.source || {};
    box.innerHTML =
      '<h3>' + esc(d.record_pk) + ' · ' + esc(d.fuel || '—') + '</h3>' +
      '<p class="sub2">' + esc(src.source_relpath || '') + ' · CSV row ' + esc(src.csv_record_index) + ' (lines ' + esc(src.physical_line_start) + '–' + esc(src.physical_line_end) + ') · SHA-256 <code>' + esc(String(src.source_sha256 || '').slice(0, 16)) + '...</code></p>' +
      '<div class="scroll"><table class="dt"><thead><tr><th>Field</th><th>Raw value</th><th>Status</th><th class="n">Normalized</th><th>Provenance</th></tr></thead><tbody>' + mRows + '</tbody></table></div>' +
      '<div class="meta"><span>' + esc(d.boundary || '') + '</span><button type="button" class="lnk" id="close-pick">Close detail</button></div>';
    var closeBtn = box.querySelector('#close-pick');
    if (closeBtn) closeBtn.addEventListener('click', function () { S.pick = null; S.detailData = null; box.hidden = true; paintRows(); });
    share.write();
  }

  function paintRows() {
    var d = S.searchData;
    if (!d) return;
    var covHtml = (d.coverage && FF.api && typeof FF.api.renderCoverageCard === 'function')
      ? FF.api.renderCoverageCard(d.coverage, { title: 'Core Table Search' })
      : '';
    var qText = S.q.trim().toLowerCase();
    var list = (d.records || []).filter(function (r) {
      if (!qText) return true;
      var hay = [r.record_pk, r.test_id, r.sample_id, r.flex_identifier, r.fuel_raw, r.fuel_norm, r.test_end].join(' ').toLowerCase();
      return hay.indexOf(qText) >= 0;
    });
    if (!list.length) {
      $('rows').innerHTML = covHtml + '<p class="empty">No matching core runs. Try widening filters or clearing the text filter.</p>';
      return;
    }
    var shown = S.showAll ? list : list.slice(0, 40);
    var body = shown.map(function (r) {
      var idLabel = r.flex_identifier || (r.sample_id ? 'Sample ' + r.sample_id : '—');
      var checked = S.cmp.indexOf(r.record_pk) >= 0 ? ' checked' : '';
      var dis = !checked && S.cmp.length >= 4 ? ' disabled' : '';
      var flags = (r.quality_flags || []).map(statusChip).join(' ');
      return '<tr class="pickable' + (S.pick === r.record_pk ? ' sel' : '') + '" data-pk="' + esc(r.record_pk) + '">' +
        '<td class="chkc"><input type="checkbox" class="cmp-cb" data-cmp="' + esc(r.record_pk) + '"' + checked + dis + ' aria-label="Compare ' + esc(r.record_pk) + '"></td>' +
        '<td><code>' + esc(r.record_pk) + '</code></td>' +
        '<td>' + esc(r.investigation_id) + '</td>' +
        '<td>' + esc(idLabel) + '</td>' +
        '<td>' + esc(r.fuel_norm || r.fuel_raw || '—') + '</td>' +
        '<td>' + esc(r.test_end || '—') + '</td>' +
        '<td>' + (flags || '<span class="mini">clean</span>') + '</td>' +
        '<td class="mini">line ' + esc(r.source && r.source.physical_line_start) + '</td></tr>';
    }).join('');
    var foot = list.length > shown.length ? '<p class="stat">Showing ' + shown.length + ' of ' + list.length + ' filtered runs (total ' + d.total_runs + ' in backend). <button type="button" class="lnk" id="show-all">Show all ' + list.length + '</button></p>' : '<p class="stat">Showing ' + list.length + ' runs (total ' + d.total_runs + ' matched in backend).</p>';
    $('rows').innerHTML = covHtml + foot + '<div class="scroll"><table class="dt tt"><thead><tr><th class="chkc">Compare</th><th>Record PK</th><th>Study</th><th>FLEX / Sample #</th><th>Fuel / Material</th><th>Test end</th><th>Flags</th><th>Locator</th></tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  function loadCompare() {
    if (S.cmp.length < 2) {
      S.compareData = null;
      paintCompare();
      return;
    }
    $('compare').innerHTML = '<p class="small">Loading comparison from /api/compare...</p>';
    FF.api.compare({ record_pks: S.cmp.slice(0, 4) }).then(function (env) {
      S.compareData = env && env.data ? env.data : null;
      paintCompare();
    }).catch(function (err) {
      $('compare').innerHTML = '<div class="callout gap"><strong>Compare failed:</strong> ' + esc((err && err.message) || 'Error') + '</div>';
    });
  }

  function paintCompare() {
    if (S.cmp.length < 2 || !S.compareData) {
      $('compare').innerHTML = '<p class="empty">Tick 2 to 4 rows in Core Test Rows above to compare them side by side (' + S.cmp.length + ' selected).</p>';
      return;
    }
    var cd = S.compareData;
    var rows = cd.rows || [];
    var fields = cd.field_names || [];
    var head = '<th>Measurement field</th>' + rows.map(function (r) {
      return '<th><div class="ch-t">' + esc(r.record_pk) + '</div><div class="ch-s">' + esc((r.fuel_norm || '') + (r.test_end ? ' · ' + r.test_end : '')) + '</div><button type="button" class="lnk rm-cmp" data-pk="' + esc(r.record_pk) + '">Remove</button></th>';
    }).join('');
    var trs = fields.map(function (fn) {
      var vals = rows.map(function (r) {
        var m = r.measurements && r.measurements[fn];
        if (!m) return '·';
        return m.normalized_value != null ? (m.normalized_value + ' ' + (m.normalized_unit || '') + ' (' + m.status + ')') : m.status;
      });
      var unique = {};
      vals.forEach(function (v) { unique[v] = true; });
      var differs = Object.keys(unique).length > 1;
      return '<tr' + (differs ? ' class="diff"' : '') + '><th>' + esc(fn) + (differs ? '<span class="dtag">differs</span>' : '') + '</th>' +
        vals.map(function (v) { return '<td>' + esc(v) + '</td>'; }).join('') + '</tr>';
    }).join('');
    $('compare').innerHTML = '<p class="stat">' + esc(cd.boundary_note || '') + '</p>' +
      '<div class="scroll"><table class="dt cmp"><thead><tr>' + head + '</tr></thead><tbody>' + trs + '</tbody></table></div>';
  }

  function paintAnalytics() {
    if (S.exp === 'all') {
      $('quality').innerHTML = '<div class="callout">Select <strong>PSI-69 (FLEX)</strong> or <strong>PSI-25 (BASS-II)</strong> in the left rail to view single-study descriptive analytics and same-scope CSV/JSON exports. PSI-25 and PSI-69 are never pooled together.</div>';
      return;
    }
    var d = S.analyticsData;
    if (!d) return;
    var sum = d.summary || {};
    var excl = sum.excluded_by_status || {};
    var exclHtml = Object.keys(excl).filter(function (k) { return excl[k] > 0; }).map(function (k) {
      return '<span class="st st-invalid">' + esc(k.replace(/_/g, ' ')) + ': ' + excl[k] + '</span>';
    }).join(' ');
    var stDist = ((d.charts || {}).measurement_status_distribution || {}).counts || [];
    var endDist = ((d.charts || {}).test_end_distribution || {}).counts || [];

    var aCov = (d.coverage && FF.api && typeof FF.api.renderCoverageCard === 'function')
      ? FF.api.renderCoverageCard(d.coverage, { title: 'Descriptive Analytics' })
      : '';
    $('quality').innerHTML =
      aCov +
      '<div class="facts">' +
      '<span><b>' + esc(d.total_runs) + '</b>matching runs in ' + esc(d.investigation_id) + '</span>' +
      '<span><b>' + esc(sum.used_total_count || 0) + '</b>used in summary</span>' +
      '<span><b>' + esc(sum.mean_value != null ? sum.mean_value : '—') + '</b>mean (' + esc(d.unit) + ')</span>' +
      '<span><b>' + esc(sum.median_value != null ? sum.median_value : '—') + '</b>median (' + esc(d.unit) + ')</span>' +
      '<span><b>' + esc(sum.min_value != null ? (sum.min_value + ' to ' + sum.max_value) : '—') + '</b>range (' + esc(d.unit) + ')</span>' +
      '</div>' +
      (exclHtml ? '<p class="stat">Excluded without zero-coercion: ' + exclHtml + '</p>' : '') +
      '<p class="stat">Status counts: ' + stDist.map(function (c) { return esc(c.status + '=' + c.count); }).join(' · ') +
      (endDist.length ? ' | Test end: ' + endDist.map(function (c) { return esc(c.label + '=' + c.count); }).join(' · ') : '') + '</p>' +
      '<p class="small">' + esc(d.boundary_note || '') + '</p>';
  }

  function exportActive(fmt) {
    if (S.exp !== 'PSI-25' && S.exp !== 'PSI-69') {
      $('export-msg').textContent = 'Choose a single investigation (PSI-69 or PSI-25) in Core Investigation before exporting.';
      return;
    }
    $('export-msg').textContent = 'Preparing verified ' + fmt.toUpperCase() + ' export from /api/export...';
    var req = buildAnalyticsPayload(S.exp);
    req.format = fmt;
    FF.api.exportAndDownload(req).then(function (env) {
      var d = (env && env.data) || {};
      $('export-msg').textContent = 'Downloaded ' + (d.filename || fmt) + ' (' + (d.total_runs || 0) + ' runs, ' + (d.used_in_summary_count || 0) + ' used, ' + (d.excluded_count || 0) + ' excluded).';
    }).catch(function (err) {
      $('export-msg').textContent = 'Export failed: ' + ((err && err.message) || 'Error');
    });
  }

  /* ---- Separate CFI Module ---- */
  function loadCfiAnalysis() {
    if (!FF.api) return;
    $('cfi-out').innerHTML = '<p class="small">Loading PSI-39 CFI cell...</p>';
    FF.api.cfiAnalysis({
      pressure_atm: parseFloat($('cfi-p').value),
      fiber: $('cfi-fiber').value,
      fuel: $('cfi-fuel').value || null,
      sensitivity_mode: $('cfi-sens').value || 'all_candidates'
    }).then(function (env) {
      S.cfiData = env && env.data ? env.data : null;
      paintCfi();
    }).catch(function (err) {
      $('cfi-out').innerHTML = '<div class="callout gap"><strong>CFI module error:</strong> ' + esc((err && err.message) || 'Error') + '</div>';
    });
  }

  function paintCfi() {
    var d = S.cfiData;
    if (!d) return;
    var groups = d.fuel_groups || [];
    var cards = groups.map(function (g) {
      var dx = g.dext_cool_mm || {};
      var kc = g.kcool || {};
      return '<article class="ecard">' +
        '<div class="ecard-head"><span class="ecard-id">' + esc(g.fuel) + '</span><span class="st st-measured">n=' + esc(g.n_candidates) + ' candidates</span></div>' +
        '<div class="ecard-meta">Kcool (finite=' + esc(kc.n_finite) + ', missing=' + esc(kc.n_missing) + '): median <b>' + esc(kc.median != null ? kc.median : '—') + '</b> (' + esc(kc.min) + '–' + esc(kc.max) + ' ' + esc(kc.unit || '') + ')</div>' +
        '<div class="ecard-meta">Dext,cool (&gt;0: ' + esc(dx.n_positive) + ', median=' + esc(dx.positive_median != null ? dx.positive_median : '—') + ' mm) · <b>Raw zero unresolved: ' + esc(dx.n_raw_zero_unresolved) + '</b>' +
        (dx.raw_zero_record_ids && dx.raw_zero_record_ids.length ? ' (IDs: ' + esc(dx.raw_zero_record_ids.join(', ')) + ')' : '') + ' · Empty: ' + esc(dx.n_empty) + '</div>' +
        '<div class="ecard-reason">' + esc(dx.interpretation_note || '') + '</div>' +
        '<div class="ecard-meta">Record IDs: ' + esc((g.record_ids || []).join(', ')) + '</div>' +
        '</article>';
    }).join('');
    var lims = (d.limitations || []).slice(0, 3).map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('');
    $('cfi-out').innerHTML =
      '<div class="facts"><span><b>' + esc(d.total_candidates_in_cell) + '</b>candidate runs in cell</span><span><b>' + esc((d.pool_summary || {}).candidate_pool_count || 144) + '</b>total CFI candidates</span><span><b>False</b>indexed in RAG (separate module)</span></div>' +
      '<div class="card-grid">' + (cards || '<p class="empty">No candidates in selected CFI cell.</p>') + '</div>' +
      (lims ? '<ul class="stat" style="margin-top:10px">' + lims + '</ul>' : '');
  }

  /* ---- Separate SAFFIRE-II Module ---- */
  function loadSaffire() {
    if (!FF.api) return;
    $('saffire-out').innerHTML = '<p class="small">Loading PSI-99 SAFFIRE-II cards...</p>';
    var sid = $('saf-id').value || null;
    FF.api.saffireReference(sid ? { sample_id: sid } : {}).then(function (env) {
      S.safData = env && env.data ? env.data : null;
      paintSaffire();
    }).catch(function (err) {
      $('saffire-out').innerHTML = '<div class="callout gap"><strong>SAFFIRE module error:</strong> ' + esc((err && err.message) || 'Error') + '</div>';
    });
  }

  function paintSaffire() {
    var d = S.safData;
    if (!d) return;
    var cards = (d.cards || []).map(function (c) {
      var mat = c.material || {};
      var res = c.results || {};
      var mg = res.microgravity || {};
      var ng = res.normal_gravity_reference || {};
      var unres = (c.unresolved_items || []).map(function (u) {
        return '<div class="unres-box"><strong>' + esc(u.field) + ' (' + esc(u.status) + '):</strong> ' + esc(u.detail) + '</div>';
      }).join('');
      return '<article class="ecard">' +
        '<div class="ecard-head"><span class="ecard-id">Sample ' + esc(c.sample_id) + '</span><span class="st ' + (mat.display_value ? 'st-measured' : 'st-approx') + '">' + esc(mat.display_value || 'Unresolved CSV empty') + '</span></div>' +
        '<div class="ecard-meta">µ-g burn length: <b>' + esc(mg.burn_length && mg.burn_length.raw_value ? mg.burn_length.raw_value : '—') + '</b> · µ-g spread: <b>' + esc(mg.spread_length_or_rate && mg.spread_length_or_rate.raw_value ? mg.spread_length_or_rate.raw_value : '—') + '</b></div>' +
        '<div class="ecard-meta">1-g ref (NASA-STD-6001, not ceteris paribus): ' + esc((ng.burn_length && ng.burn_length.raw_value) || '—') + ' / ' + esc((ng.spread_rate && ng.spread_rate.raw_value) || '—') + '</div>' +
        unres +
        '</article>';
    }).join('');
    $('saffire-out').innerHTML =
      '<div class="facts"><span><b>' + esc(d.total_sample_records) + '</b>physical sample cards (2-1..2-9)</span><span><b>' + esc(d.auxiliary_and_note_rows_excluded_from_sample_count) + '</b>auxiliary &amp; footnote rows separated</span><span><b>False</b>safety ranking enabled</span></div>' +
      '<div class="card-grid">' + cards + '</div>';
  }

  /* ---- Document Passages ---- */
  function loadDocs() {
    var q = $('doc-q').value.trim() || 'cool flame';
    var inv = $('doc-exp').value || null;
    $('doc-out').innerHTML = '<p class="small">Searching 503 NASA report passages...</p>';
    var docReq = nextReq('docs');
    FF.api.documents({ query: q, investigation_id: inv, top_k: 5 }, docReq.opts).then(function (env) {
      if (docReq.seq !== S.seq.docs) return;
      S.docsData = env && env.data ? env.data : null;
      paintDocs();
    }).catch(function (err) {
      if (err && err.name === 'AbortError') return;
      if (docReq.seq !== S.seq.docs) return;
      $('doc-out').innerHTML = '<div class="callout gap"><strong>Document search error:</strong> ' + esc((err && err.message) || 'Error') + '</div>';
    });
  }

  function paintDocs() {
    var d = S.docsData;
    if (!d || !d.hits || !d.hits.length) {
      $('doc-out').innerHTML = '<p class="empty">No matching passages found in indexed NASA documents.</p>';
      return;
    }
    $('doc-out').innerHTML = '<p class="stat">' + esc(d.boundary || '') + '</p>' + d.hits.map(function (h) {
      var ntrs = safeUrl(h.source_url);
      return '<article class="pass-card">' +
        '<div class="ecard-head"><span class="ecard-id">' + esc(h.investigation_id || '') + ' · ' + esc(h.document_id) + ' · printed p.' + esc(h.printed_page_start || h.pdf_page_start) + '</span>' +
        '<span class="st st-none">rank #' + esc(h.rank) + ' (BM25 ' + esc(Number(h.score).toFixed(2)) + ')</span></div>' +
        '<div class="ecard-title">' + esc(h.section_title || h.section_path || '') + '</div>' +
        '<pre>' + esc(h.source_text || '') + '</pre>' +
        '<div class="ecard-meta">SHA-256 <code>' + esc(String(h.source_sha256 || '').slice(0, 16)) + '...</code>' +
        (ntrs ? ' · <a class="lnk" href="' + esc(ntrs) + '" target="_blank" rel="noopener noreferrer">NASA NTRS citation ↗</a>' : '') +
        '</div></article>';
    }).join('');
  }

  /* ---- Provenance Sources Table ---- */
  function paintSources() {
    var rows = [];
    if (S.schema && Array.isArray(S.schema.datasets)) {
      S.schema.datasets.forEach(function (d) {
        rows.push({ id: d.id, name: d.name, role: 'Core experimental CSV (' + d.run_count + ' runs)', doi: d.doi ? 'https://doi.org/' + d.doi : '', sha: d.sha256 });
      });
    }
    if (S.cfiSchema && S.cfiSchema.workbook_provenance) {
      var wp = S.cfiSchema.workbook_provenance;
      rows.push({ id: 'PSI-39', name: 'Cool Flames Investigation (CFI) Summary Workbook', role: 'Separate CFI workbook module', doi: wp.relpath, sha: wp.sha256 });
    }
    if (S.safSchema) {
      rows.push({ id: 'PSI-99', name: 'SAFFIRE-II Experimental Table & ReadMe', role: 'Separate 9-sample reference module', doi: 'CC0-1.0', sha: (S.safSchema.provenance && S.safSchema.provenance.csv_sha256) || 'verified_at_load' });
    }
    $('sources').innerHTML = '<table class="dt"><thead><tr><th>Study</th><th>Title / Resource</th><th>Backend Tier</th><th>DOI / Relpath</th><th>SHA-256</th></tr></thead><tbody>' +
      rows.map(function (r) {
        var href = safeUrl(r.doi);
        return '<tr><td><code>' + esc(r.id) + '</code></td><td>' + esc(r.name) + '</td><td>' + esc(r.role) + '</td><td>' +
          (href ? '<a class="lnk" href="' + esc(href) + '" target="_blank" rel="noopener noreferrer">' + esc(r.doi) + '</a>' : esc(r.doi)) +
          '</td><td><code>' + esc(String(r.sha || '').slice(0, 20)) + '...</code></td></tr>';
      }).join('') + '</tbody></table>';
  }

  function wireEvents() {
    $('f-exp').addEventListener('change', function (e) {
      S.exp = e.target.value;
      S.fuel = '';
      updateSidebarOptions();
      loadCore();
    });
    $('f-fuel').addEventListener('change', function (e) { S.fuel = e.target.value; loadCore(); });
    $('f-q').addEventListener('input', function (e) { S.q = e.target.value; paintRows(); });
    $('f-field').addEventListener('change', function (e) {
      var parts = e.target.value.split('|');
      S.fieldName = parts[0] || '';
      S.unit = parts[1] || '';
      if (S.exp === 'PSI-25' || S.exp === 'PSI-69') loadCore();
    });
    $('f-approx').addEventListener('change', function (e) { S.includeApprox = e.target.checked; if (S.exp !== 'all') loadCore(); });

    rsO2 = FF.range($('rs-o2'), {
      min: 10, max: 40, step: 0.5, from: S.o2[0], to: S.o2[1], label: 'Oxygen (%)',
      format: function (a, b) { return S.o2Active ? (a + ' to ' + b + '%') : 'Any'; },
      onChange: function (a, b) { S.o2 = [a, b]; S.o2Active = true; loadCore(); }
    });
    rsP = FF.range($('rs-p'), {
      min: 0.2, max: 3.2, step: 0.1, from: S.p[0], to: S.p[1], label: 'Pressure (atm)',
      format: function (a, b) { return S.pActive ? (a.toFixed(1) + ' to ' + b.toFixed(1) + ' atm') : 'Any'; },
      onChange: function (a, b) { S.p = [a, b]; S.pActive = true; loadCore(); }
    });

    $('reset').addEventListener('click', function () {
      S.exp = 'all'; S.fuel = ''; S.q = ''; S.o2 = [10, 40]; S.p = [0.2, 3.2]; S.o2Active = false; S.pActive = false; S.includeApprox = false; S.pick = null; S.cmp = [];
      $('f-exp').value = 'all'; $('f-q').value = ''; $('f-approx').checked = false;
      rsO2.set(10, 40); rsP.set(0.2, 3.2);
      updateSidebarOptions();
      loadCore();
      paintCompare();
    });
    $('copylink').addEventListener('click', function () { share.copy($('copylink')); });
    $('csv-f').addEventListener('click', function () { exportActive('csv'); });
    $('json-f').addEventListener('click', function () { exportActive('json'); });

    $('cat-go').addEventListener('click', loadCatalog);
    $('cat-q').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); loadCatalog(); } });
    $('cat-type').addEventListener('change', loadCatalog);
    $('cat-area').addEventListener('change', loadCatalog);
    $('cat-core').addEventListener('change', loadCatalog);
    $('catalog-list').addEventListener('click', function (e) {
      var btn = e.target.closest && e.target.closest('[data-open-core]');
      if (!btn) return;
      S.exp = btn.dataset.openCore;
      $('f-exp').value = S.exp;
      updateSidebarOptions();
      loadCore();
      document.getElementById('s-explorer').scrollIntoView({ behavior: 'smooth' });
    });

    $('rows').addEventListener('click', function (e) {
      if (e.target && e.target.id === 'show-all') { S.showAll = true; paintRows(); return; }
      var cb = e.target.closest && e.target.closest('.cmp-cb');
      if (cb) {
        var pk = cb.dataset.cmp;
        var idx = S.cmp.indexOf(pk);
        if (cb.checked && idx < 0 && S.cmp.length < 4) S.cmp.push(pk);
        else if (!cb.checked && idx >= 0) S.cmp.splice(idx, 1);
        Array.prototype.forEach.call($('rows').querySelectorAll('.cmp-cb'), function (box) {
          var isOn = S.cmp.indexOf(box.dataset.cmp) >= 0;
          box.checked = isOn;
          box.disabled = !isOn && S.cmp.length >= 4;
        });
        paintHeaderFacts();
        loadCompare();
        return;
      }
      var tr = e.target.closest && e.target.closest('tr[data-pk]');
      if (tr) {
        loadDetail(tr.dataset.pk);
        paintRows();
      }
    });

    $('compare').addEventListener('click', function (e) {
      var rm = e.target.closest && e.target.closest('.rm-cmp');
      if (!rm) return;
      S.cmp = S.cmp.filter(function (pk) { return pk !== rm.dataset.pk; });
      paintHeaderFacts();
      paintRows();
      loadCompare();
    });

    ['cfi-p', 'cfi-fiber', 'cfi-fuel', 'cfi-sens'].forEach(function (id) {
      $(id).addEventListener('change', loadCfiAnalysis);
    });
    $('saf-id').addEventListener('change', loadSaffire);
    $('doc-form').addEventListener('submit', function (e) { e.preventDefault(); loadDocs(); });
  }

  function init() {
    share.read();
    applyQueryParams();
    $('f-exp').value = S.exp;
    $('f-q').value = S.q;
    $('f-approx').checked = S.includeApprox;
    wireEvents();

    if (!FF.api) return;
    Promise.all([
      FF.api.schema(),
      FF.api.catalogFilters(),
      FF.api.cfiSchema(),
      FF.api.saffireSchema()
    ]).then(function (res) {
      S.schema = res[0] && res[0].data;
      S.catFilters = res[1] && res[1].data;
      S.cfiSchema = res[2] && res[2].data;
      S.safSchema = res[3] && res[3].data;

      if (S.catFilters) {
        $('cat-type').innerHTML = '<option value="">All project types</option>' + (S.catFilters.project_types || []).map(function (t) { return '<option value="' + esc(t) + '">' + esc(t) + '</option>'; }).join('');
        $('cat-area').innerHTML = '<option value="">All sub-research areas</option>' + (S.catFilters.sub_research_areas || []).map(function (a) { return '<option value="' + esc(a) + '">' + esc(a) + '</option>'; }).join('');
      }
      if (S.cfiSchema && S.cfiSchema.filters) {
        $('cfi-fuel').innerHTML = '<option value="">All fuels in cell</option>' + (S.cfiSchema.filters.candidate_fuels_in_scope || []).map(function (f) { return '<option value="' + esc(f) + '">' + esc(f) + '</option>'; }).join('');
        $('cfi-sens').innerHTML = (S.cfiSchema.filters.sensitivity_modes || []).map(function (m) { return '<option value="' + esc(m.id) + '">' + esc(m.label) + '</option>'; }).join('');
      }
      if (S.safSchema && S.safSchema.row_separation) {
        $('saf-id').innerHTML = '<option value="">All 9 samples (2-1..2-9)</option>' + (S.safSchema.row_separation.sample_ids || []).map(function (id) { return '<option value="' + esc(id) + '">Sample ' + esc(id) + '</option>'; }).join('');
      }

      updateSidebarOptions();
      paintSources();
      loadCatalog();
      loadCore();
      paintCompare();
      loadCfiAnalysis();
      loadSaffire();
      loadDocs();
    }).catch(function (err) {
      $('ov').innerHTML = '<span style="color:#ff9c87">Failed to connect to local GenAIus backend: ' + esc((err && err.message) || 'Unknown error') + '</span>';
    });
  }

  init();
})();
