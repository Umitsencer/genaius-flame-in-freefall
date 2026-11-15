/* GenAIus shared REST API client for all frontend pages.
 * Single shared transport layer over src/genaius/prototype/server.py. */
(function (root) {
  'use strict';

  root.FF = root.FF || {};

  function ApiError(message, options) {
    var opts = options || {};
    this.name = 'ApiError';
    this.message = message || 'Backend request failed.';
    this.status = opts.status || 'ERROR';
    this.httpStatus = opts.httpStatus || 0;
    this.payload = opts.payload || null;
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  var NON_FATAL_STATUSES = {
    OK: true,
    NO_EVIDENCE: true,
    ABSTAINED: true,
    NOT_SUPPORTED: true
  };

  function requestJson(method, path, body, opts) {
    var options = opts || {};
    var headers = { Accept: 'application/json' };
    var init = {
      method: method,
      headers: headers,
      cache: 'no-store'
    };
    if (options.signal) {
      init.signal = options.signal;
    }
    if (body !== undefined && body !== null) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }

    return fetch(path, init)
      .catch(function (err) {
        if (err && err.name === 'AbortError') {
          throw err;
        }
        throw new ApiError('Unable to reach the local GenAIus backend server.', {
          status: 'NETWORK_ERROR',
          httpStatus: 0
        });
      })
      .then(function (resp) {
        return resp.text().then(function (text) {
          var parsed = null;
          if (text) {
            try {
              parsed = JSON.parse(text);
            } catch (_e) {
              throw new ApiError('Backend returned a non-JSON response (' + resp.status + ').', {
                status: 'PARSE_ERROR',
                httpStatus: resp.status
              });
            }
          }
          if (!parsed || typeof parsed !== 'object') {
            throw new ApiError('Backend returned an empty response (' + resp.status + ').', {
              status: 'EMPTY_RESPONSE',
              httpStatus: resp.status
            });
          }

          var envStatus = parsed.status || (resp.ok ? 'OK' : 'ERROR');
          if (!resp.ok || !NON_FATAL_STATUSES[envStatus]) {
            throw new ApiError(parsed.message || ('Request failed (' + envStatus + ').'), {
              status: envStatus,
              httpStatus: resp.status,
              payload: parsed
            });
          }
          return parsed;
        });
      });
  }

  function triggerDownload(filename, content, mimeType) {
    var blob = new Blob([content], { type: mimeType || 'text/plain;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename || 'export.txt';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  function get(path, opts) {
    return requestJson('GET', path, null, opts);
  }

  function post(path, body, opts) {
    return requestJson('POST', path, body || {}, opts);
  }

  function exportAndDownload(payload, opts) {
    var req = Object.assign({ format: 'csv' }, payload || {});
    return post('/api/export', req, opts).then(function (env) {
      var d = env && env.data ? env.data : {};
      var fmt = String(d.format || req.format || 'csv').toLowerCase();
      var mime = fmt === 'json' ? 'application/json;charset=utf-8' : 'text/csv;charset=utf-8';
      var content = typeof d.content === 'string'
        ? d.content
        : JSON.stringify(d, null, 2);
      var fname = d.filename || ('genaius_export.' + fmt);
      triggerDownload(fname, content, mime);
      return env;
    });
  }

  function makeShare(spec, get, set) {
    return {
      read: function () {
        if (!root.FF || !root.FF.share || !root.FF.share.read) return;
        var params = root.FF.share.read();
        var patch = {};
        Object.keys(spec).forEach(function (k) {
          var v = params.get(k);
          if (v === null) return;
          var t = spec[k][0];
          if (t === 'n') {
            var num = parseFloat(v);
            if (!isNaN(num)) patch[k] = num;
          } else if (t === 'b') {
            patch[k] = (v === '1' || v === 'true');
          } else if (t === 'a') {
            patch[k] = v ? v.split(',').map(function (item) {
              var s = item.trim();
              return /^-?\d+(\.\d+)?$/.test(s) ? parseFloat(s) : s;
            }) : [];
          } else {
            patch[k] = v;
          }
        });
        set(patch);
      },
      write: function () {
        if (!root.FF || !root.FF.share || !root.FF.share.write) return;
        var cur = get();
        var out = {};
        Object.keys(spec).forEach(function (k) {
          var t = spec[k][0];
          var def = spec[k][1];
          var val = cur[k];
          if (t === 'b') {
            if (Boolean(val) !== Boolean(def)) out[k] = val ? '1' : '0';
          } else if (t === 'a') {
            var a = Array.isArray(val) ? val.join(',') : '';
            var d = Array.isArray(def) ? def.join(',') : '';
            if (a !== d) out[k] = a;
          } else if (val != null && val !== def) {
            out[k] = val;
          }
        });
        root.FF.share.write(out);
      },
      copy: function (btn) {
        if (root.FF && root.FF.share && root.FF.share.copy) {
          root.FF.share.copy(window.location.href, btn);
        }
      }
    };
  }

  root.FF.api = {
    ApiError: ApiError,
    requestJson: requestJson,
    triggerDownload: triggerDownload,
    makeShare: makeShare,
    schema: function (opts) { return get('/api/schema', opts); },
    catalogFilters: function (opts) { return get('/api/catalog/filters', opts); },
    preventionSummary: function (opts) { return get('/api/prevention/summary', opts); },
    catalogSearch: function (payload, opts) { return post('/api/catalog/search', payload, opts); },
    search: function (payload, opts) { return post('/api/search', payload, opts); },
    detail: function (payload, opts) { return post('/api/detail', payload, opts); },
    compare: function (payload, opts) { return post('/api/compare', payload, opts); },
    documents: function (payload, opts) { return post('/api/documents', payload, opts); },
    evidence: function (payload, opts) { return post('/api/evidence', payload, opts); },
    answer: function (payload, opts) {
      var src = (payload && typeof payload === 'object') ? payload : {};
      var clean = {};
      [
        'query',
        'investigation_id',
        'fuel',
        'test_end',
        'numeric_filters',
        'include_approximate',
        'summarize_field_name',
        'summarize_unit',
        'compare_record_pks',
        'compare_field_names',
        'top_k',
        'max_table_citations',
        'run_table_query',
        'use_bilingual_aliases',
        'scope',
        'flex_condition'
      ].forEach(function (key) {
        if (src[key] !== undefined) clean[key] = src[key];
      });
      return post('/api/answer', clean, opts);
    },
    analytics: function (payload, opts) { return post('/api/analytics', payload, opts); },
    exportSubset: function (payload, opts) { return post('/api/export', payload, opts); },
    exportAndDownload: exportAndDownload,
    analyticsFlex: function (payload, opts) { return post('/api/analytics/flex', payload, opts); },
    analyticsMaterials: function (payload, opts) { return post('/api/analytics/materials', payload, opts); },
    cfiSchema: function (opts) { return get('/api/cfi/schema', opts); },
    cfiAnalysis: function (payload, opts) { return post('/api/cfi/analysis', payload, opts); },
    saffireSchema: function (opts) { return get('/api/saffire/schema', opts); },
    saffireReference: function (payload, opts) { return post('/api/saffire/reference', payload, opts); },
    saffireCaseSchema: function (opts) { return get('/api/saffire/case/schema', opts); },
    saffireCaseReference: function (payload, opts) { return post('/api/saffire/case', payload, opts); },
    saffireCaseExportAndDownload: function (payload, opts) {
      var req = Object.assign({ format: 'json' }, payload || {});
      return post('/api/saffire/case/export', req, opts).then(function (env) {
        var d = env && env.data ? env.data : {};
        var fmt = String(d.format || req.format || 'json').toLowerCase();
        var mime = fmt === 'csv' ? 'text/csv;charset=utf-8' : 'application/json;charset=utf-8';
        var content = typeof d.content === 'string' ? d.content : JSON.stringify(d, null, 2);
        triggerDownload(d.filename || ('genaius_saffire_case_reference.' + fmt), content, mime);
        return env;
      });
    },
    flexPredictSchema: function (opts) { return get('/api/flex/predict/schema', opts); },
    flexPredict: function (payload, opts) { return post('/api/flex/predict', payload, opts); },
    flexPredictMap: function (payload, opts) { return post('/api/flex/predict/map', payload, opts); },
    flexPredictExportAndDownload: function (payload, opts) {
      var req = Object.assign({ format: 'md' }, payload || {});
      return post('/api/flex/predict/export', req, opts).then(function (env) {
        var d = env && env.data ? env.data : {};
        var fmt = String(d.format || req.format || 'md').toLowerCase();
        var mime = fmt === 'json' ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8';
        var content = typeof d.content === 'string' ? d.content : JSON.stringify(d, null, 2);
        triggerDownload(d.filename || ('flex_condition_summary.' + fmt), content, mime);
        return env;
      });
    },
    flexReconciliation: function (opts) { return get('/api/flex/reconciliation', opts); },
    coverageStatusClass: function (status) {
      var st = String(status || 'unavailable').toLowerCase();
      if (st === 'matching' || st === 'related' || st === 'no_match' || st === 'unavailable') return st;
      return 'unavailable';
    },
    renderCoverageCard: function (cov, opts) {
      if (!cov || typeof cov !== 'object') return '';
      opts = opts || {};
      var st = String(cov.status || 'unavailable').toLowerCase();
      var cls = (st === 'matching' || st === 'related' || st === 'no_match' || st === 'unavailable') ? st : 'unavailable';
      var labelMap = {
        matching: 'MATCHING TESTS FOUND',
        related: 'RELATED TESTS ONLY',
        no_match: 'NO MATCH IN INDEXED SOURCES',
        unavailable: 'SOURCE UNAVAILABLE / ERROR'
      };
      var uiLabel = cov.ui_label || labelMap[cls] || 'SOURCE UNAVAILABLE / ERROR';
      function e(s) {
        return String(s == null ? '' : s)
          .replace(/&/g, '&amp;').replace(/</g, '&lt;')
          .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }
      var matched = cov.matching_count != null ? cov.matching_count : '—';
      var total = cov.total_corpus_count != null ? cov.total_corpus_count : '—';
      var tol = cov.tolerance_policy || {};
      var diffs = Array.isArray(cov.differing_or_missing_conditions) ? cov.differing_or_missing_conditions : [];
      var lims = Array.isArray(cov.limitations) ? cov.limitations : [];
      var titlePrefix = opts.title ? ('<strong>' + e(opts.title) + '</strong> · ') : '';
      return '<div class="cov-card" data-cov-status="' + e(cls) + '">' +
        '<div class="cov-card-head">' +
          '<div>' + titlePrefix + '<span class="cov-badge cov-' + e(cls) + '">' + e(uiLabel) + '</span></div>' +
          '<span class="cov-counts">' + e(cov.corpus_id || cov.scope || '') + ' · <strong>' + e(matched) + ' / ' + e(total) + '</strong> records</span>' +
        '</div>' +
        (tol.applied_tolerance ? '<p class="cov-note"><strong>Basis:</strong> ' + e(tol.applied_tolerance) + (tol.rationale ? ' — ' + e(tol.rationale) : '') + '</p>' : '') +
        (diffs.length ? '<p class="cov-note"><strong>Scope &amp; differences:</strong> ' + e(diffs[0]) + '</p>' : '') +
        (opts.showAllLimitations && lims.length ? ('<ul class="cov-limit-list">' + lims.slice(0, 3).map(function (l) { return '<li>' + e(l) + '</li>'; }).join('') + '</ul>') : (lims.length ? '<p class="cov-note">' + e(lims[0]) + '</p>' : '')) +
        '<p class="cov-ai-foot"><a href="./docs/AI_USE.md" target="_blank" rel="noopener">How AI, numerical checks &amp; coverage work</a></p>' +
      '</div>';
    }
  };
})(typeof window !== 'undefined' ? window : globalThis);
