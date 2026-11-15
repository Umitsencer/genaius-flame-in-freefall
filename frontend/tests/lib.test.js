// Çalıştır: node frontend/tests/lib.test.js
const assert = require('assert'); const fs = require('fs'); const path = require('path'); const vm = require('vm');
const lib = require('../js/lib.js');
const ctx = { window: {} }; vm.createContext(ctx);
['flex', 'materials'].forEach(n => vm.runInContext(fs.readFileSync(path.join(__dirname, '../data', n + '.js'), 'utf8'), ctx));
const { flex, materials } = ctx.window.FF_DATA;

assert.strictEqual(flex.length, 274);
const e = lib.flexEvidence(flex, { fuel: 'Methanol', o2: 21, p: 1.0 });
assert(e.n >= 5 && e.top && e.top.share > 0 && e.top.share <= 1);
assert.strictEqual(e.outcomes.reduce((a, o) => a + o.n, 0), e.n);
const w = lib.wilson(5, 10); assert(w[0] < 0.5 && w[1] > 0.5);
assert.strictEqual(lib.wilson(0, 0), null);
// hiç eşleşme yoksa yakıt geneline düşer ve bunu bildirir
const far = lib.flexEvidence(flex, { fuel: 'Heptane', o2: 90, p: 5 }); assert.strictEqual(far.level, 'fuel-wide');

const m21 = lib.materialEvidence(materials, { o2: 21 });
assert(!m21.beyond && m21.groups[0].nNear > 0);
const m34 = lib.materialEvidence(materials, { o2: 34 });
assert(m34.beyond, '34% O2 test edilen aralığın dışında olmalı');   // keşif atmosferi boşluğu
assert(m34.groups.every(g => g.nNear === 0));
console.log('OK. En yüksek test edilen O2:', m34.maxTestedO2, '| FLEX 21% metanol:', e.n, 'test, en sık sonuç', e.top.name, (e.top.share * 100).toFixed(0) + '%');
console.log('21% O2 sıralama:', m21.groups.slice(0, 4).map(g => `${g.name} (n=${g.nNear}, ΔCO=${g.coMedian})`).join(' | '));

const fpCtx = { window: {} }; vm.createContext(fpCtx);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../js/flex-predictor-ui.js'), 'utf8'), fpCtx);
const { validateClientCondition } = fpCtx.window.FF.flexPredictorHelpers;
const okAir = validateClientCondition({ fuel: 'Methanol', o2Pct: 21, dilMode: 'Air', dilPct: 0, pressureVal: 1.0, pressureUnit: 'atm', d0Mm: 2.5 });
assert.strictEqual(okAir.valid, true);
assert(Math.abs(okAir.n2Frac - 0.79) < 1e-6);
const badSum = validateClientCondition({ fuel: 'Methanol', o2Pct: 80, dilMode: 'CO2', dilPct: 30, pressureVal: 1.0, pressureUnit: 'atm', d0Mm: 2.5 });
assert.strictEqual(badSum.valid, false);
const mixedDil = validateClientCondition({ fuel: 'Methanol', o2Pct: 21, dilMode: 'MIXED', mixCo2Pct: 15, mixHePct: 15, pressureVal: 1.0, pressureUnit: 'atm', d0Mm: 2.5 });
assert.strictEqual(mixedDil.valid, true);
assert.strictEqual(mixedDil.payload.co2_mol_frac, 0.15);
assert.strictEqual(mixedDil.payload.he_mol_frac, 0.15);
const badP = validateClientCondition({ fuel: 'Heptane', o2Pct: 21, dilMode: 'Air', dilPct: 0, pressureVal: 0, pressureUnit: 'atm', d0Mm: 2.5 });
assert.strictEqual(badP.valid, false);
const moonPreset = lib.PRESETS.find(p => p.id === 'expl-moon');
const marsPreset = lib.PRESETS.find(p => p.id === 'expl-mars');
assert(moonPreset && moonPreset.hypothetical === true && /NOT NASA/i.test(moonPreset.note));
assert(marsPreset && marsPreset.hypothetical === true && /NOT NASA/i.test(marsPreset.note));

// Verify FF.api.renderCoverageCard renders all 4 coverage states cleanly without JS syntax errors
const apiCtx = { window: { FF: {} } };
vm.createContext(apiCtx);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../js/api.js'), 'utf8'), apiCtx);
const renderCov = apiCtx.window.FF.api.renderCoverageCard;
for (const [st, expected] of [
  ['matching', 'MATCHING TESTS FOUND'],
  ['related', 'RELATED TESTS ONLY'],
  ['no_match', 'NO MATCH IN INDEXED SOURCES'],
  ['unavailable', 'SOURCE UNAVAILABLE / ERROR']
]) {
  const html = renderCov({ status: st, corpus_id: 'TEST', matching_count: 1, total_corpus_count: 10 });
  assert(html.includes(expected), `Expected ${expected} for status ${st}`);
  assert(html.includes('./docs/AI_USE.md'), 'Expected AI_USE.md link in coverage card');
}

// Verify chat.js helpers deduplicate abstention text and distinguish guardrail vs no-LLM modes
const chatCtx = { window: { FF: { api: apiCtx.window.FF.api } } };
vm.createContext(chatCtx);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../js/chat.js'), 'utf8'), chatCtx);
const ch = chatCtx.window.FF.chat.helpers;
for (const emptyItem of ['', ' ', '*', ' - ', '**', '•', '—']) {
  assert.strictEqual(ch.cleanAnswerText(emptyItem), '');
}
assert.strictEqual(ch.cleanAnswerText('  K = 0.5 mm²/s  '), 'K = 0.5 mm²/s');
assert.deepStrictEqual(Array.from(ch.dedupeMessages(['*', ' - ', 'Measured evidence'], [])), ['Measured evidence']);
assert.deepStrictEqual(
  Array.from(ch.dedupeMessages(['Same explanation', 'Same   explanation ', 'Distinct note'], ['Prefix Same explanation'])),
  ['Distinct note']
);
assert.strictEqual(ch.resolveModeBadge({ status: 'ABSTAINED', mode: 'deterministic', llmUsed: false }, true), 'Guardrail · Not sent to LLM');
assert.strictEqual(ch.resolveModeBadge({ status: 'ABSTAINED', mode: 'deterministic', llmUsed: false }, false), 'Deterministic · Guardrail');
assert.strictEqual(ch.resolveModeBadge({ status: 'OK', mode: 'llm', llmUsed: true }, true), 'OpenRouter LLM · Cited only');
assert.strictEqual(ch.resolveModeBadge({ status: 'OK', mode: 'deterministic_fallback', llmUsed: false }, true), 'Fallback -> Deterministic (No LLM)');
const banner = ch.failureReasonBanner('OUTPUT_VALIDATION_FAILED', 'deterministic_fallback');
assert(banner.includes('schema/citation') && banner.includes('no LLM synthesis') && !/verified/i.test(banner));
const tech = ch.buildTechnicalDetails({
  failureReason: 'OUTPUT_VALIDATION_FAILED',
  validationDiagnostics: {
    category: 'OUTPUT_VALIDATION_FAILED',
    diagnosis_code: 'DISALLOWED_CITATION',
    field_path: '$.findings[0].citation_ids[0]',
    expected: 'id in allowed_citation_ids',
    observed: 'DOC:FAKE'
  },
  numericalAudit: { status: 'not_applicable_deterministic', checked_facts_count: 5 },
  warnings: ['llm_fallback: validation error', 'Internal lexical note'],
  limitations: ['BM25 score is lexical matching only.', 'Regular scope limit.']
});
assert(tech.some(l => l.includes('DISALLOWED_CITATION') && l.includes('$.findings[0].citation_ids[0]')));
assert(tech.some(l => l.includes('Expected: id in allowed_citation_ids')));
assert(tech.some(l => l.includes('BM25 score is lexical matching only.')));
assert(!tech.some(l => l.includes('Regular scope limit.')));
assert(!tech.some(l => l.startsWith('llm_fallback:')));
const llmTech = ch.buildTechnicalDetails({
  llmUsed: true,
  investigationId: 'SAFFIRE-CASE',
  numericalAudit: { status: 'passed', checked_facts_count: 12 },
  warnings: ['', '   ']
});
assert(llmTech.some(l => l.includes('isolated SAFFIRE IV–VI / SAME case bundle only')));
assert(llmTech.some(l => l.includes('Numerical audit: passed (12 facts)')));
assert.strictEqual(ch.resolveActiveContext(null).scope, 'auto');

console.log('OK. FLEX predictor + hypothetical preset + coverage card + chat helper UI checks passed.');
