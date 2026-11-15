/* Evidence assistant launcher: a round GeNAIus button in the bottom-right corner of every page.
 * Wired by default to POST /api/answer via FF.api when present.
 * External callers can trigger FF.chat.ask(question) or override FF.chat.handler(question). */
(function (root) {
  'use strict';
  root.FF = root.FF || {};
  var hasDoc = typeof document !== 'undefined';
  var script = hasDoc ? document.currentScript : null, base = script ? script.src : '';
  function asset(rel) { try { return new URL(rel, base).href; } catch (e) { return rel; } }
  if (hasDoc && !document.querySelector('link[href*="chat.css"]')) {
    var l = document.createElement('link');
    l.rel = 'stylesheet';
    l.href = asset('../css/chat.css');
    document.head.appendChild(l);
  }
  var logo = asset('../assets/logo.jpg');

  var EXAMPLES = [
    'What happened in Saffire VI-3?',
    'Compare FLEX tests 10, 11 and 12.',
    'Show BASS-II tests using Nomex.',
    'Can BASS-II predict safety in Mars habitat?'
  ];

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function safeHref(url) {
    if (!url || typeof url !== 'string') return null;
    var trimmed = url.trim();
    if (/^(?:data\.html|fire\.html|material-lab\.html|case-saffire\.html|index\.html)(?:[?#].*)?$/i.test(trimmed)) {
      return trimmed;
    }
    try {
      var u = new URL(trimmed, root.location ? root.location.href : 'http://127.0.0.1/');
      if (u.protocol === 'http:' || u.protocol === 'https:') {
        return u.href;
      }
    } catch (_e) {
      return null;
    }
    return null;
  }

  function mapBackendSources(sources, query) {
    if (!Array.isArray(sources)) return [];
    var out = [];
    var seen = {};
    for (var i = 0; i < sources.length; i++) {
      var s = sources[i] || {};
      var label = s.locator_label || s.record_pk || s.document_id || s.citation_id || 'Source';
      var href = null;
      if (s.source_type === 'table_row' && s.record_pk) {
        var inv = s.investigation_id || (String(s.record_pk).split(':')[0]) || 'PSI-69';
        href = 'data.html?exp=' + encodeURIComponent(inv) + '&pick=' + encodeURIComponent(s.record_pk) + '#s-explorer';
      } else if (s.source_type === 'case_record' && s.record_pk) {
        href = 'case-saffire.html?test=' + encodeURIComponent(s.record_pk) + '#s-conditions';
      } else if (s.source_type === 'case_detection') {
        href = 'case-saffire.html#s-related';
      } else if (s.source_type === 'model_prediction') {
        href = 'fire.html#s-flex-predictor';
      } else if (s.source_type === 'document_chunk' && s.investigation_id === 'SAFFIRE-CASE') {
        href = safeHref(s.source_url) || 'case-saffire.html#s-limits';
      } else if (s.source_type === 'document_chunk') {
        var docInv = s.investigation_id || '';
        href = 'data.html?doc=1' + (docInv ? '&exp=' + encodeURIComponent(docInv) : '') + '&q=' + encodeURIComponent(query || label) + '#s-docs';
      } else if (s.source_url) {
        href = safeHref(s.source_url);
      }
      if (!href) continue;
      var key = href + '|' + label;
      if (seen[key]) continue;
      seen[key] = true;
      out.push({
        label: label,
        href: href,
        externalUrl: s.source_url ? safeHref(s.source_url) : null
      });
    }
    return out;
  }

  var ALLOWED_REQ_KEYS = [
    'investigation_id', 'fuel', 'test_end', 'numeric_filters',
    'include_approximate', 'summarize_field_name', 'summarize_unit',
    'compare_record_pks', 'compare_field_names', 'top_k',
    'use_bilingual_aliases', 'run_table_query', 'max_table_citations',
    'scope', 'flex_condition'
  ];

  function buildAnswerPayload(question, context) {
    var req = { query: question };
    if (context && typeof context === 'object') {
      ALLOWED_REQ_KEYS.forEach(function (k) {
        if (context[k] !== undefined) req[k] = context[k];
      });
    }
    return req;
  }

  function normalizeMsgKey(s) {
    return String(s == null ? '' : s).replace(/\s+/g, ' ').trim().toLowerCase();
  }

  function cleanAnswerText(value) {
    var text = String(value == null ? '' : value).trim();
    return /^[\s*•\-–—]*$/.test(text) ? '' : text;
  }

  function dedupeMessages(items, seedTexts) {
    var seen = [];
    if (Array.isArray(seedTexts)) {
      seedTexts.forEach(function (t) {
        var k = normalizeMsgKey(t);
        if (k) seen.push(k);
      });
    }
    var out = [];
    if (!Array.isArray(items)) return out;
    for (var i = 0; i < items.length; i++) {
      var raw = cleanAnswerText(items[i]);
      var key = normalizeMsgKey(raw);
      if (!key) continue;
      var dup = seen.some(function (prev) {
        return prev === key || prev.indexOf(key) !== -1;
      });
      if (dup) continue;
      seen.push(key);
      out.push(raw);
    }
    return out;
  }

  function resolveModeBadge(r, runtimeLlmEnabled) {
    var status = (r && r.status) ? String(r.status).toUpperCase() : 'OK';
    var rawMode = (r && r.mode) ? String(r.mode) : 'deterministic';
    var llmUsed = Boolean(r && r.llmUsed && rawMode === 'llm');
    if (llmUsed) return 'OpenRouter LLM · Cited only';
    if (rawMode === 'table_computed') return 'Computed from table records';
    if (rawMode === 'scenario_check') return 'Computed from table records · coverage check';
    if (rawMode === 'prevention_summary') return 'Computed from table records · sources labelled';
    if (rawMode === 'deterministic_fallback') return 'Fallback -> Deterministic (No LLM)';
    if (status === 'ABSTAINED' || status === 'NO_EVIDENCE') {
      return (runtimeLlmEnabled === true) ? 'Guardrail · Not sent to LLM' : 'Deterministic · Guardrail';
    }
    return 'Deterministic · No LLM';
  }

  function failureReasonBanner(reason, mode) {
    var r = String(reason || 'NONE').toUpperCase();
    if (r === 'LLM_QUOTA_EXCEEDED') {
      return 'OpenRouter returned HTTP 429 (rate limit). Showing deterministic NASA records below (no LLM synthesis).';
    }
    if (r === 'NUMERICAL_VALIDATION_FAILED') {
      return 'LLM draft rejected by numerical/unit check. Showing deterministic NASA records below (no LLM synthesis).';
    }
    if (r === 'OUTPUT_VALIDATION_FAILED') {
      return 'LLM draft rejected by schema/citation validation. Showing deterministic NASA records below (no LLM synthesis).';
    }
    if (r === 'INPUT_BUDGET_EXCEEDED') {
      return 'Evidence payload exceeded prompt cap. Showing deterministic NASA records below (no LLM synthesis).';
    }
    if (r === 'LLM_UNAVAILABLE') {
      return 'LLM provider unavailable. Showing deterministic NASA records below (no LLM synthesis).';
    }
    if (mode === 'deterministic_fallback') {
      return 'LLM output unavailable or rejected. Showing deterministic NASA records below (no LLM synthesis).';
    }
    return '';
  }

  function buildTechnicalDetails(r) {
    var lines = [];
    if (!r || typeof r !== 'object') return lines;
    var vd = r.validationDiagnostics;
    if (vd && typeof vd === 'object') {
      var head = [];
      if (vd.category) head.push('Category: ' + vd.category);
      if (vd.diagnosis_code) head.push('Code: ' + vd.diagnosis_code);
      if (vd.field_path) head.push('Path: ' + vd.field_path);
      if (head.length) lines.push(head.join(' · '));
      if (vd.expected) lines.push('Expected: ' + vd.expected);
      if (vd.observed) lines.push('Observed: ' + vd.observed);
      if (vd.message && (!vd.observed || vd.message.indexOf(vd.observed) === -1)) {
        lines.push('Detail: ' + vd.message);
      }
    } else if (r.failureReason && String(r.failureReason).toUpperCase() !== 'NONE') {
      lines.push('Fallback reason: ' + String(r.failureReason).toUpperCase());
    }
    var na = r.numericalAudit;
    if (na && typeof na === 'object' && na.status) {
      lines.push('Numerical audit: ' + na.status + (na.checked_facts_count != null ? (' (' + na.checked_facts_count + ' facts)') : ''));
      if (Array.isArray(na.issues) && na.issues.length && !vd) {
        lines.push('Audit issue: ' + String(na.issues[0]));
      }
    }
    if (r.llmUsed) {
      var scopeTech = (r.investigationId === 'SAFFIRE-CASE')
        ? 'Synthesis scope: isolated SAFFIRE IV–VI / SAME case bundle only (core 403, PSI-39 CFI, PSI-99 SAFFIRE-II excluded).'
        : ((r.investigationId === 'FLEX-PRED')
          ? 'Synthesis scope: FLEX prediction support gate + nearest PSI-69 tests only.'
          : 'Synthesis scope: retrieved PSI-25/PSI-69 evidence bundle only (CFI and SAFFIRE-II excluded).');
      lines.push(scopeTech);
    }
    if (Array.isArray(r.warnings)) {
      r.warnings.forEach(function (w) {
        var wt = String(w || '').trim();
        if (!wt) return;
        if (vd && wt.indexOf('llm_fallback:') === 0) return;
        lines.push(wt);
      });
    }
    var rawLim = Array.isArray(r.limitations) ? r.limitations : [];
    rawLim.forEach(function (lim) {
      var lt = String(lim || '').trim();
      if (lt && (lt.indexOf('BM25') !== -1 || lt.indexOf('lexical') !== -1 || lt.indexOf('truncated') !== -1 || lt.indexOf('index') !== -1)) {
        lines.push(lt);
      }
    });
    return dedupeMessages(lines, []);
  }

  function formatScopeName(scope) {
    if (scope === 'saffire_case') return 'SAFFIRE IV–VI Case Study';
    if (scope === 'flex_prediction') return 'FLEX Predictor (Active condition)';
    if (scope === 'core') return 'Core (PSI-25 + PSI-69)';
    return 'Auto (Smart route)';
  }

  function formatContextLabel(ctx) {
    if (!ctx || typeof ctx !== 'object') return 'Auto (Smart route)';
    if (ctx.uiLabel) return String(ctx.uiLabel);
    if (ctx.scope === 'saffire_case') return 'SAFFIRE IV–VI Case Study';
    if (ctx.scope === 'flex_prediction') {
      var fc = ctx.flex_condition || {};
      return 'FLEX Predictor (' + (fc.fuel || 'condition') + (fc.o2_mol_pct != null ? ', ' + fc.o2_mol_pct + '% O₂' : '') + ')';
    }
    var bits = [];
    if (ctx.investigation_id) bits.push(ctx.investigation_id);
    if (ctx.fuel) bits.push(ctx.fuel);
    if (Array.isArray(ctx.numeric_filters) && ctx.numeric_filters.length) bits.push(ctx.numeric_filters.length + ' filter(s)');
    if (bits.length) return 'Active scope: ' + bits.join(' · ');
    return formatScopeName(ctx.scope || 'auto');
  }

  function defaultBackendHandler(question, context, opts) {
    if (!root.FF.api || typeof root.FF.api.answer !== 'function') {
      return Promise.reject(new Error('API client not loaded'));
    }
    var req = buildAnswerPayload(question, context);
    return root.FF.api.answer(req, opts).then(function (env) {
      var d = (env && env.data) || {};
      var answerMode = String(d.answer_mode || env.mode || 'deterministic');
      var llmUsed = Boolean(d.llm_used === true && answerMode === 'llm');
      var routing = d.scope_routing || null;
      var effectiveScope = (routing && routing.resolved_scope) || req.scope || 'core';
      return {
        status: d.status || env.status || 'OK',
        mode: answerMode,
        llmUsed: llmUsed,
        investigationId: (effectiveScope === 'saffire_case') ? 'SAFFIRE-CASE' : (effectiveScope === 'flex_prediction' ? 'FLEX-PRED' : d.investigation_id),
        coverage: d.coverage || env.coverage || null,
        scopeRouting: routing,
        numericalAudit: d.numerical_audit || null,
        failureReason: d.failure_reason || 'NONE',
        validationDiagnostics: d.validation_diagnostics || null,
        answer: d.summary || env.message || 'No answer was returned.',
        findings: Array.isArray(d.findings) ? d.findings : [],
        limitations: Array.isArray(d.limitations) ? d.limitations : [],
        warnings: Array.isArray(d.warnings) ? d.warnings : [],
        abstention: d.abstention || null,
        sources: mapBackendSources(d.sources || [], question)
      };
    });
  }

  var existing = root.FF.chat || {};
  root.FF.chat = existing;
  if (typeof existing.handler !== 'function') {
    existing.handler = defaultBackendHandler;
  }

  function resolveActiveContext(explicitCtx) {
    var base = explicitCtx || lastContext || (root.FF.chat && root.FF.chat.defaultContext) || null;
    if (!base || typeof base !== 'object') {
      return { scope: 'auto', uiLabel: 'Auto (Smart route)' };
    }
    var copy = Object.assign({}, base);
    if (!copy.scope) copy.scope = 'auto';
    return copy;
  }

  root.FF.chat.helpers = {
    buildAnswerPayload: buildAnswerPayload,
    formatContextLabel: formatContextLabel,
    dedupeMessages: dedupeMessages,
    cleanAnswerText: cleanAnswerText,
    resolveModeBadge: resolveModeBadge,
    resolveActiveContext: resolveActiveContext,
    failureReasonBanner: failureReasonBanner,
    buildTechnicalDetails: buildTechnicalDetails
  };
  if (typeof document === 'undefined') return;

  var btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'gc-btn';
  btn.setAttribute('aria-label', 'Open the evidence assistant');
  btn.setAttribute('aria-expanded', 'false');
  btn.setAttribute('aria-controls', 'gc-panel');
  btn.innerHTML = '<svg class="gc-bubble" viewBox="0 0 76 70" aria-hidden="true" focusable="false"><path d="M19 3H57Q73 3 73 19V37Q73 53 57 53H56L60 66L42 53H19Q3 53 3 37V19Q3 3 19 3Z"/></svg>' +
    '<span class="gc-face"><img src="' + logo + '" alt=""></span>';

  var panel = document.createElement('section');
  panel.id = 'gc-panel';
  panel.className = 'gc-panel';
  panel.hidden = true;
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'Evidence assistant');
  panel.innerHTML = '<header class="gc-head"><span class="gc-mini"><img src="' + logo + '" alt=""></span><div><div class="gc-title">Evidence assistant</div><div class="gc-sub">NASA PSI grounded evidence assistant</div></div><button type="button" class="gc-x" aria-label="Close">&times;</button></header>' +
    '<div class="gc-ctx" id="gc-ctx"></div>' +
    '<div class="gc-body" id="gc-body" aria-live="polite"></div>' +
    '<div class="gc-ai-foot"><span>Numbers &amp; units audited in Python</span><a href="./docs/AI_USE.md" target="_blank" rel="noopener">How AI &amp; verification work</a></div>' +
    '<form class="gc-form" id="gc-form"><label class="gc-sr" for="gc-q">Ask a question about the NASA tests</label><input id="gc-q" type="text" autocomplete="off" placeholder="Ask about the NASA tests"><button type="submit" class="gc-send">Send</button></form>';

  var body = panel.querySelector('#gc-body');
  var ctxEl = panel.querySelector('#gc-ctx');
  var form = panel.querySelector('#gc-form');
  var input = panel.querySelector('#gc-q');
  var send = panel.querySelector('.gc-send');
  var subEl = panel.querySelector('.gc-sub');
  var lastQuery = '';
  var lastContext = null;
  var schemaChecked = false;
  var runtimeLlmEnabled = null;
  var chatSeq = 0;
  var chatCtrl = null;

  function renderContextBar() {
    if (!ctxEl) return;
    var active = resolveActiveContext(null);
    var curScope = active.scope || 'auto';
    var hasFlex = Boolean(active.flex_condition);
    var ctxLabel = formatContextLabel(active);
    var scopeLabel = formatScopeName(curScope);
    var showCtxTag = Boolean(ctxLabel && ctxLabel !== scopeLabel && ctxLabel !== 'Auto (Smart NASA scope)');
    ctxEl.innerHTML =
      '<label class="gc-scope-lbl" for="gc-scope">Scope:</label>' +
      '<select id="gc-scope" class="gc-scope-sel" aria-label="Search scope">' +
      '<option value="auto"' + (curScope === 'auto' ? ' selected' : '') + '>Auto (Smart route)</option>' +
      '<option value="core"' + (curScope === 'core' ? ' selected' : '') + '>Core (PSI-25 + PSI-69)</option>' +
      '<option value="saffire_case"' + (curScope === 'saffire_case' ? ' selected' : '') + '>SAFFIRE IV–VI Case Study</option>' +
      (hasFlex ? '<option value="flex_prediction"' + (curScope === 'flex_prediction' ? ' selected' : '') + '>FLEX Predictor (Active condition)</option>' : '') +
      '</select>' +
      (showCtxTag ? '<span class="gc-ctx-tag">' + esc(ctxLabel) + '</span>' : '');
  }

  function applyManualScope(nextScope) {
    var cur = resolveActiveContext(null);
    var next;
    if (nextScope === 'saffire_case') {
      next = { scope: 'saffire_case', uiLabel: 'SAFFIRE IV–VI Case Study' };
    } else if (nextScope === 'flex_prediction' && cur.flex_condition) {
      next = Object.assign({}, cur, { scope: 'flex_prediction' });
    } else if (nextScope === 'core') {
      next = Object.assign({}, cur, { scope: 'core' });
      delete next.flex_condition;
      if (!next.investigation_id && !next.fuel && !(Array.isArray(next.numeric_filters) && next.numeric_filters.length)) {
        next.uiLabel = 'Core (PSI-25 + PSI-69)';
      } else if (next.uiLabel === 'Auto (Smart route)' || next.uiLabel === 'Auto (Smart NASA scope)' || next.uiLabel === 'SAFFIRE IV–VI Case Study') {
        delete next.uiLabel;
      }
    } else {
      next = Object.assign({}, cur, { scope: 'auto' });
      delete next.flex_condition;
      if (!next.investigation_id && !next.fuel && !(Array.isArray(next.numeric_filters) && next.numeric_filters.length)) {
        next.uiLabel = 'Auto (Smart route)';
      }
    }
    root.FF.chat.defaultContext = next;
    lastContext = next;
    renderContextBar();
  }

  ctxEl.addEventListener('change', function (e) {
    if (e.target && e.target.id === 'gc-scope') {
      applyManualScope(e.target.value);
    }
  });

  function syncRuntimeSubtitle() {
    if (schemaChecked || !root.FF.api || typeof root.FF.api.schema !== 'function') return;
    schemaChecked = true;
    root.FF.api.schema().then(function (env) {
      runtimeLlmEnabled = Boolean(env && env.llm_enabled);
      if (!subEl) return;
      if (runtimeLlmEnabled) {
        var model = env.data && env.data.llm_model ? ' (' + env.data.llm_model + ')' : '';
        subEl.textContent = 'OpenRouter :free + deterministic NASA fallback' + model;
      } else {
        subEl.textContent = 'Offline deterministic NASA evidence (LLM disabled)';
      }
    }).catch(function () {
      runtimeLlmEnabled = false;
      if (subEl) subEl.textContent = 'Offline deterministic NASA evidence (LLM disabled)';
    });
  }

  function introMarkup() {
    var on = typeof root.FF.chat.handler === 'function';
    if (!on) {
      return '<div class="gc-note"><strong>Not connected yet.</strong> The evidence backend is unavailable. You can still browse local tables when served via the backend server.</div>';
    }
    return '<div class="gc-msg gc-bot">Ask a question about the NASA PSI combustion evidence. Supported answers cite exact test rows and documents, and unsupported extrapolations explicitly abstain.</div>' +
      '<div class="gc-ex"><div class="gc-exh">Try an example</div>' +
      EXAMPLES.map(function (q) {
        return '<button type="button" class="gc-q" data-q="' + esc(q) + '">' + esc(q) + '</button>';
      }).join('') +
      '</div>';
  }

  function paint() {
    var on = typeof root.FF.chat.handler === 'function';
    input.disabled = !on;
    send.disabled = !on;
    renderContextBar();
    if (!body.children.length) {
      body.innerHTML = introMarkup();
    }
  }

  function add(cls, html) {
    var d = document.createElement('div');
    d.className = 'gc-msg ' + cls;
    d.innerHTML = html;
    body.appendChild(d);
    body.scrollTop = body.scrollHeight;
    return d;
  }

  function renderResponseHtml(r) {
    var status = (r && r.status) ? String(r.status).toUpperCase() : 'OK';
    var rawMode = (r && r.mode) ? String(r.mode) : 'deterministic';
    var llmUsed = Boolean(r && r.llmUsed && rawMode === 'llm');
    var badgeClass = status === 'OK' ? 'gc-badge-ok' : 'gc-badge-abstained';
    var modeText = resolveModeBadge(r, runtimeLlmEnabled);
    var parts = [];
    parts.push('<div class="gc-badge-row"><span class="gc-badge ' + badgeClass + '">' + esc(status) + '</span><span class="gc-mode">' + esc(modeText) + '</span></div>');

    var cov = r && r.coverage;
    var routing = r && r.scopeRouting;
    var abst = r && r.abstention;
    var reasonCode = (abst && abst.reason_code) ? String(abst.reason_code) : '';
    if ((cov && typeof cov === 'object') || (routing && routing.requested_scope === 'auto')) {
      var covBits = [];
      if (routing && routing.requested_scope === 'auto' && routing.resolved_scope && routing.resolved_scope !== 'clarification') {
        covBits.push('<span class="gc-route-pill">Route: Auto &rarr; ' + esc(formatScopeName(routing.resolved_scope)) + '</span>');
      }
      if (cov && typeof cov === 'object') {
        var covSt = (root.FF.api && typeof root.FF.api.coverageStatusClass === 'function')
          ? root.FF.api.coverageStatusClass(cov.status)
          : 'unavailable';
        var isGuardrailBlock = Boolean(
          abst && abst.abstained && reasonCode && reasonCode !== 'NO_MATCHING_EVIDENCE' && covSt === 'no_match'
        );
        if (isGuardrailBlock) {
          covBits.push('<span class="gc-cov-pill gc-cov-related">NOT QUERIED IN THIS SCOPE · ' + esc(reasonCode) + '</span>');
        } else {
          var covCount = (cov.matching_count != null && cov.total_corpus_count != null)
            ? (' · ' + cov.matching_count + ' / ' + cov.total_corpus_count)
            : '';
          covBits.push('<span class="gc-cov-pill gc-cov-' + esc(covSt) + '">' + esc(cov.ui_label || covSt) + esc(covCount) + '</span>');
        }
      }
      if (covBits.length) parts.push('<div class="gc-cov">' + covBits.join('') + '</div>');
    }

    var na = r && r.numericalAudit;
    if (llmUsed && na && na.status === 'passed') {
      parts.push('<div class="gc-cov"><span class="gc-audit-ok" title="' + esc(na.disclaimer || '') + '">Numerical consistency checked (summary &amp; findings)</span></div>');
    }

    var failBanner = failureReasonBanner(r && r.failureReason, rawMode);
    if (failBanner) {
      parts.push('<div class="gc-fail-banner">' + esc(failBanner) + '</div>');
    }

    var summaryText = (r && r.answer) || 'No answer was returned.';
    parts.push('<div class="gc-summary">' + esc(summaryText) + '</div>');

    if (r && Array.isArray(r.findings) && r.findings.length) {
      var findingItems = r.findings.slice(0, 4).map(function (f) {
        var txt = cleanAnswerText(typeof f === 'string' ? f : (f && f.text) || '');
        return txt ? '<li>' + esc(txt) + '</li>' : '';
      }).filter(Boolean);
      if (findingItems.length) {
        parts.push('<ul class="gc-findings">' + findingItems.join('') + '</ul>');
      }
    }

    var rawNotes = [];
    if (abst && abst.abstained && abst.explanation) rawNotes.push(abst.explanation);
    if (r && Array.isArray(r.limitations)) {
      r.limitations.forEach(function (lim) {
        var lt = cleanAnswerText(lim);
        if (lt && lt.indexOf('BM25') === -1 && lt.indexOf('lexical') === -1 && lt.indexOf('truncated') === -1 && lt.indexOf('index') === -1) {
          rawNotes.push(lt);
        }
      });
    }
    var uniqueNotes = dedupeMessages(rawNotes, [summaryText]).slice(0, 2);
    uniqueNotes.forEach(function (noteText) {
      parts.push('<div class="gc-limit">' + esc(noteText) + '</div>');
    });

    var techLines = buildTechnicalDetails(r);
    if (techLines.length) {
      parts.push('<details class="gc-tech"><summary>Technical details</summary><ul class="gc-tech-list">' +
        techLines.map(function (line) { return '<li>' + esc(line) + '</li>'; }).join('') +
        '</ul></details>');
    }

    if (status === 'ABSTAINED' && (
      reasonCode === 'SCOPE_CLARIFICATION_REQUIRED' ||
      reasonCode === 'CROSS_STUDY_POOLING_NOT_SUPPORTED' ||
      reasonCode === 'V12_OUT_OF_SCOPE_STUDY'
    )) {
      var opts = (routing && Array.isArray(routing.scope_options) && routing.scope_options.length)
        ? routing.scope_options
        : [
          { scope: 'saffire_case', label: 'SAFFIRE IV–VI Case Study', action: 'requery' },
          { scope: 'core', label: 'Core (PSI-25 + PSI-69)', action: 'requery' },
          { scope: 'psi99_cards', label: 'PSI-99 SAFFIRE-II Cards', href: 'data.html#s-saffire', action: 'link' }
        ];
      var actionHtml = opts.map(function (opt) {
        if (opt.action === 'link' && opt.href) {
          var linkHref = safeHref(opt.href);
          return linkHref ? '<a class="gc-scope-act gc-scope-link" href="' + esc(linkHref) + '">' + esc(opt.label) + '</a>' : '';
        }
        return '<button type="button" class="gc-scope-act" data-scope-switch="' + esc(opt.scope) + '" data-scope-label="' + esc(opt.label) + '">Try: ' + esc(opt.label) + '</button>';
      }).filter(Boolean).join('');
      if (actionHtml) {
        parts.push('<div class="gc-scope-actions">' + actionHtml + '</div>');
      }
    }

    var srcList = (r && Array.isArray(r.sources)) ? r.sources.slice(0, 6) : [];
    if (srcList.length) {
      var links = srcList.map(function (s) {
        var href = safeHref(s.href);
        return href ? '<li><a href="' + esc(href) + '">' + esc(s.label || href) + '</a></li>' : '';
      }).filter(Boolean).join('');
      if (links) {
        parts.push('<div class="gc-src"><span>Sources (' + srcList.length + ')</span><ul class="gc-src-list">' + links + '</ul></div>');
      }
    }
    return parts.join('');
  }

  function resetThread() {
    if (chatCtrl && typeof chatCtrl.abort === 'function') chatCtrl.abort();
    chatSeq++;
    body.innerHTML = introMarkup();
    var enabled = typeof root.FF.chat.handler === 'function';
    send.disabled = !enabled;
    input.disabled = !enabled;
    renderContextBar();
  }

  function submitQuestion(rawQuestion, context) {
    var q = String(rawQuestion || '').trim();
    var h = root.FF.chat.handler;
    if (!q || typeof h !== 'function') return;
    lastQuery = q;
    var resolvedContext = resolveActiveContext(context);
    lastContext = resolvedContext;
    renderContextBar();
    var seq = ++chatSeq;
    if (chatCtrl && typeof chatCtrl.abort === 'function') chatCtrl.abort();
    chatCtrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var intro = body.querySelector('.gc-ex');
    if (intro) body.innerHTML = '';
    add('gc-user', esc(q));
    input.value = '';
    var wait = add('gc-bot gc-wait', 'Searching NASA evidence and documents...');
    send.disabled = true;
    input.disabled = true;
    var callOpts = chatCtrl ? { signal: chatCtrl.signal } : undefined;
    Promise.resolve().then(function () { return h(q, lastContext, callOpts); }).then(function (r) {
      if (seq !== chatSeq) return;
      wait.classList.remove('gc-wait');
      if (subEl && r && runtimeLlmEnabled === null) {
        if (r.llmUsed && r.mode === 'llm') {
          subEl.textContent = 'OpenRouter :free + deterministic NASA fallback';
        }
      }
      wait.innerHTML = renderResponseHtml(r);
      body.scrollTop = body.scrollHeight;
    }).catch(function (err) {
      if (err && err.name === 'AbortError') return;
      if (seq !== chatSeq) return;
      wait.classList.remove('gc-wait');
      var msg = (err && err.message) ? err.message : 'The evidence assistant is unavailable right now.';
      wait.innerHTML = '<div class="gc-badge-row"><span class="gc-badge gc-badge-error">ERROR</span></div>' +
        '<div>' + esc(msg) + '</div>' +
        '<button type="button" class="gc-retry">Retry</button>';
      var retryBtn = wait.querySelector('.gc-retry');
      if (retryBtn) {
        retryBtn.addEventListener('click', function () {
          submitQuestion(lastQuery, lastContext);
        });
      }
      body.scrollTop = body.scrollHeight;
    }).then(function () {
      if (seq !== chatSeq) return;
      var enabled = typeof root.FF.chat.handler === 'function';
      send.disabled = !enabled;
      input.disabled = !enabled;
      if (!panel.hidden) input.focus();
    });
  }

  body.addEventListener('click', function (e) {
    var chip = e.target && e.target.closest ? e.target.closest('button.gc-q') : null;
    if (chip && chip.dataset && chip.dataset.q) {
      submitQuestion(chip.dataset.q);
      return;
    }
    var sw = e.target && e.target.closest ? e.target.closest('button.gc-scope-act') : null;
    if (sw && sw.dataset && sw.dataset.scopeSwitch && lastQuery) {
      var targetScope = sw.dataset.scopeSwitch;
      applyManualScope(targetScope);
      submitQuestion(lastQuery, root.FF.chat.defaultContext);
    }
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    submitQuestion(input.value);
  });

  function open() {
    syncRuntimeSubtitle();
    paint();
    panel.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    btn.classList.add('on');
    (input.disabled ? panel.querySelector('.gc-x') : input).focus();
  }

  function close() {
    panel.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    btn.classList.remove('on');
    btn.focus();
  }

  btn.addEventListener('click', function () { panel.hidden ? open() : close(); });
  panel.querySelector('.gc-x').addEventListener('click', close);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !panel.hidden) {
      e.stopPropagation();
      close();
    }
  });

  function setContext(ctx, opts) {
    opts = opts || {};
    var prev = root.FF.chat.defaultContext || null;
    var next = (ctx && typeof ctx === 'object') ? Object.assign({}, ctx) : null;
    if (next && !next.scope && prev && (prev.scope === 'core' || prev.scope === 'auto')) {
      next.scope = prev.scope;
    }
    var prevScope = prev && (prev.scope || prev.investigation_id || 'auto');
    var nextScope = next && (next.scope || next.investigation_id || 'auto');
    var changed = JSON.stringify(prev || {}) !== JSON.stringify(next || {});
    root.FF.chat.defaultContext = next;
    lastContext = next;
    renderContextBar();
    if ((opts.clearOnChange === true && changed) || (opts.clearOnChange !== false && prev && prevScope !== nextScope)) {
      resetThread();
    }
  }

  root.FF.chat.open = open;
  root.FF.chat.close = close;
  root.FF.chat.setContext = setContext;
  root.FF.chat.ask = function (q, context) {
    if (context && typeof context === 'object') {
      setContext(context, { clearOnChange: true });
    }
    open();
    submitQuestion(q, context);
  };

  renderContextBar();

  document.body.appendChild(panel);
  document.body.appendChild(btn);
})(window);
