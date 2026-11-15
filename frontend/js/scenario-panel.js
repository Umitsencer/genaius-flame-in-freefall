/* Scenario Evidence Check panel under the fire animation.
 * - Reads the shared Environment rail (oxygen, pressure, gravity) and asks POST /api/scenario/check.
 * - Habitat report: PMMA, Nomex, SIBAL and methanol checked under one Moon / Mars / ISS condition (POST /api/scenario/report).
 * - Coverage map: every oxygen x pressure cell at the chosen fuel and gravity (POST /api/scenario/grid).
 * - Fuel list stays in step with the animation's own Fuel list (the animation shows only methanol and heptane droplets).
 * Deterministic coverage check: TESTED / PARTIAL / GAP. It is not a safety rating. English and Turkish. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var root = $('sc-panel');
  if (!root) return;
  var ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function esc(s) { return String(s == null ? '–' : s).replace(/[&<>"']/g, function (c) { return ESC[c]; }); }
  var FUELS = ['Methanol', 'Heptane', 'PMMA', 'Nomex', 'SIBAL', 'Wax candle'];
  var DROPLET = { Methanol: 1, Heptane: 1 };
  var LETTER = { TESTED: 'T', PARTIAL: 'P', GAP: 'G' };

  var TXT = {
    title: ['Scenario Evidence Check', 'Senaryo Kanıt Kontrolü'],
    lead: ['Does NASA\'s recorded test data cover the environment you set on the left? This is a coverage check, not a safety rating.',
      'NASA\'nın kayıtlı test verileri soldaki ortamı kapsıyor mu? Bu bir kapsam kontrolüdür, güvenlik değerlendirmesi değildir.'],
    fuel: ['Fuel / material', 'Yakıt / malzeme'],
    purpose: ['Research purpose (optional)', 'Araştırma amacı (isteğe bağlı)'],
    purposePh: ['e.g. lunar habitat planning', 'örn. Ay habitatı planlaması'],
    repTitle: ['Habitat report', 'Habitat raporu'],
    repLead: ['One click: PMMA, Nomex, SIBAL and methanol checked under the same habitat condition.',
      'Tek tık: PMMA, Nomex, SIBAL ve metanol aynı habitat koşulunda kontrol edilir.'],
    moon: ['Moon habitat', 'Ay habitatı'], mars: ['Mars habitat', 'Mars habitatı'], iss: ['ISS cabin (reference)', 'ISS kabini (referans)'],
    colMat: ['Material', 'Malzeme'], colStatus: ['Status', 'Durum'], colWhy: ['Why', 'Neden'],
    colRange: ['Oxygen recorded', 'Kayıtlı oksijen'], colNear: ['Nearest test', 'En yakın test'],
    checking: ['Checking: ', 'Kontrol ediliyor: '], micro: ['0 g (microgravity)', '0 g (mikro yerçekimi)'],
    differ: ['Conditions that differ or are not recorded', 'Farklı olan veya kayıtlı olmayan koşullar'],
    nearest: ['Nearest recorded tests', 'En yakın kayıtlı testler'],
    test: ['Test', 'Test'], mf: ['Material / fuel', 'Malzeme / yakıt'], pressure: ['Pressure atm', 'Basınç atm'], source: ['Source', 'Kaynak'],
    notRec: ['not recorded', 'kayıtlı değil'], sources: ['Source tables', 'Kaynak tablolar'],
    tol: ['Match tolerance: ±{o} points O₂, ±{p} atm; below {g} g counts as microgravity.',
      'Eşleşme toleransı: ±{o} puan O₂, ±{p} atm; {g} g altı mikro yerçekimi sayılır.'],
    purposeNote: [' Purpose noted: {x} (not used for matching).', ' Not alınan amaç: {x} (eşleştirmede kullanılmaz).'],
    mapTitle: ['Coverage map', 'Kapsam haritası'], micro2: ['0 g (microgravity)', '0 g (mikro yerçekimi)'],
    mapHelp: ['Rows are pressure (atm), columns are oxygen (%). <strong>T</strong> tested, <strong>P</strong> partial, <strong>G</strong> gap. {t} tested, {p} partial, {g} gap of {n} cells. Click a cell to set the environment.',
      'Satırlar basınç (atm), sütunlar oksijen (%). <strong>T</strong> test edilmiş, <strong>P</strong> kısmi, <strong>G</strong> boşluk. {n} hücrenin {t} tanesi T, {p} tanesi P, {g} tanesi G. Ortamı ayarlamak için bir hücreye tıklayın.'],
    dropNote: ['The animation shows droplets only (methanol, heptane); this check is for {f}.',
      'Animasyon yalnızca damlaları (metanol, heptan) gösterir; bu kontrol {f} içindir.'],
    down: ['The backend is not reachable.', 'Sunucuya ulaşılamıyor.'], badInput: ['Check the input values.', 'Girdi değerlerini kontrol edin.']
  };
  function lang() { return window.FF && FF.i18n && FF.i18n.lang() === 'tr' ? 'tr' : 'en'; }
  function t(k, vars) {
    var s = TXT[k][lang() === 'tr' ? 1 : 0];
    if (vars) Object.keys(vars).forEach(function (v) { s = s.replace('{' + v + '}', vars[v]); });
    return s;
  }
  function val(id) { return parseFloat($(id).value); }

  var seq = 0, timer = 0, mapKey = '', mapData = null, mapSeq = 0, lastRep = null, syncing = false;

  function post(path, body) {
    body.lang = lang();
    return FF.api.requestJson('POST', path, body);
  }

  function build() {
    root.innerHTML =
      '<h2>' + t('title') + '</h2><p class="sc-lead">' + t('lead') + '</p>' +
      '<div class="sc-report"><h3>' + t('repTitle') + '</h3><p class="sc-lead">' + t('repLead') + '</p>' +
      '<div class="sc-row"><button type="button" class="btn sc-rb" data-h="moon">' + t('moon') + '</button>' +
      '<button type="button" class="btn sc-rb" data-h="mars">' + t('mars') + '</button>' +
      '<button type="button" class="btn quiet sc-rb" data-h="iss">' + t('iss') + '</button></div><div id="sc-rep" aria-live="polite"></div>' +
      '<p class="small">Habitat coverage in indexed tables.</p></div>' +
      '<div class="sc-row"><label>' + t('fuel') + '<select id="sc-fuel">' +
      FUELS.map(function (f) { return '<option' + (f === curFuel ? ' selected' : '') + '>' + f + '</option>'; }).join('') + '</select></label>' +
      '<label>' + t('purpose') + '<input id="sc-purpose" maxlength="200" placeholder="' + esc(t('purposePh')) + '" value="' + esc(curPurpose) + '"></label></div>' +
      '<p class="sc-hint" id="sc-fuelnote"></p><p class="sc-cond" id="sc-cond"></p><div id="sc-out" aria-live="polite"></div>' +
      '<p class="small">Nearest tests and condition differences.</p><div id="sc-map"></div>' +
      '<p class="small">Coverage, not safety.</p>';
    $('sc-fuel').addEventListener('change', onPanelFuel);
    $('sc-purpose').addEventListener('change', function () { curPurpose = $('sc-purpose').value; run(); });
    Array.prototype.forEach.call(root.querySelectorAll('.sc-rb'), function (b) {
      b.addEventListener('click', function () { loadReport(b.getAttribute('data-h')); });
    });
  }
  var curFuel = ($('f-fuel') && $('f-fuel').value) || 'Methanol', curPurpose = '';

  // ---- single check ----------------------------------------------------------------------------------
  function render(d) {
    var rows = d.nearest.map(function (n) {
      return '<tr><td><a href="' + esc(n.link) + '">' + esc(n.id) + '</a></td><td>' + esc(n.name) + '</td><td>' + esc(n.o2_percent) +
        '</td><td>' + esc(n.pressure_atm == null ? t('notRec') : n.pressure_atm) + '</td><td>' + esc(n.source) + '</td></tr>';
    }).join('');
    var tl = d.tolerances, r = d.requested;
    $('sc-out').innerHTML =
      '<p><span class="sc-badge ' + esc(d.status) + '">' + esc(d.status) + '</span>' + esc(d.status_text.replace(/^[A-Z]+: /, '')) + '</p>' +
      (d.differences.length ? '<h3>' + t('differ') + '</h3><ul>' + d.differences.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '') +
      (rows ? '<h3>' + t('nearest') + '</h3><div class="sc-tablewrap"><table><thead><tr><th>' + t('test') + '</th><th>' + t('mf') + '</th><th>O₂ %</th><th>' +
        t('pressure') + '</th><th>' + t('source') + '</th></tr></thead><tbody>' + rows + '</tbody></table></div>' : '') +
      (d.sources.length ? '<h3>' + t('sources') + '</h3><ul>' + d.sources.map(function (s) {
        return '<li><a href="' + esc(s.href) + '">' + esc(s.label) + '</a></li>'; }).join('') + '</ul>' : '') +
      '<p class="sc-note">' + d.limitations.map(esc).join(' ') + ' ' + esc(t('tol', { o: tl.o2_percentage_points, p: tl.pressure_atm, g: tl.gravity_microgravity_below_g })) +
      (r.purpose ? esc(t('purposeNote', { x: r.purpose })) : '') + '</p>';
  }

  function run() {
    var o2 = val('o2'), p = val('p'), g = val('g'), fuel = $('sc-fuel').value, my = ++seq;
    $('sc-cond').textContent = t('checking') + fuel + ', ' + o2 + '% O₂, ' + p.toFixed(2) + ' atm, ' + (g === 0 ? t('micro') : g + ' g');
    post('/api/scenario/check', { fuel: fuel, o2_percent: o2, pressure_atm: p, gravity_g: g, purpose: $('sc-purpose').value.trim() || null })
      .then(function (j) {
        if (my !== seq) return;
        if (j.status !== 'OK') { $('sc-out').innerHTML = '<p>' + esc(j.message || t('badInput')) + '</p>'; return; }
        render(j.data);
      })
      .catch(function (err) { if (my === seq) $('sc-out').innerHTML = '<p>' + (err && (err.httpStatus === 400 || err.status === 'INVALID_INPUT') ? t('badInput') : t('down')) + '</p>'; });
  }

  // ---- habitat report --------------------------------------------------------------------------------
  function renderReport(d) {
    var c = d.condition;
    var body = d.rows.map(function (r) {
      var rng = r.fuel_o2_range ? (lang() === 'tr' ? '%' + r.fuel_o2_range[0] + '–' + r.fuel_o2_range[1] + ' O₂' : r.fuel_o2_range[0] + '–' + r.fuel_o2_range[1] + '% O₂') : '–';
      var n = r.nearest[0];
      return '<tr><td><strong>' + esc(r.fuel) + '</strong></td><td><span class="sc-badge ' + esc(r.status) + '">' + esc(r.status) + '</span></td><td>' +
        (r.differences.length ? '<ul>' + r.differences.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '–') +
        '</td><td>' + esc(rng) + '</td><td>' + (n ? '<a href="' + esc(n.link) + '">' + esc(n.id) + '</a>' : '–') + '</td></tr>';
    }).join('');
    $('sc-rep').innerHTML = '<p><strong>' + esc(d.summary) + '</strong></p><div class="sc-tablewrap"><table class="sc-reptable"><thead><tr><th>' + t('colMat') +
      '</th><th>' + t('colStatus') + '</th><th>' + t('colWhy') + '</th><th>' + t('colRange') + '</th><th>' + t('colNear') + '</th></tr></thead><tbody>' +
      body + '</tbody></table></div><p class="sc-note">' + d.limitations.map(esc).join(' ') + '</p>';
    Array.prototype.forEach.call(root.querySelectorAll('.sc-rb'), function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-h') === d.habitat)); });
  }
  function loadReport(h) {
    lastRep = h;
    post('/api/scenario/report', { habitat: h })
      .then(function (j) { if (lastRep === h) { if (j.status === 'OK') renderReport(j.data); else $('sc-rep').innerHTML = '<p>' + esc(j.message || t('badInput')) + '</p>'; } })
      .catch(function () { $('sc-rep').innerHTML = '<p>' + t('down') + '</p>'; });
  }

  // ---- coverage map ----------------------------------------------------------------------------------
  function paintMarker() {
    if (!mapData) return;
    var o2 = val('o2'), p = val('p'), best = null;
    mapData.o2_values.forEach(function (x, i) {
      mapData.pressure_values.forEach(function (y, j) {
        var d = Math.abs(x - o2) / 2.5 + Math.abs(y - p) / 0.1;
        if (!best || d < best.d) best = { d: d, i: i, j: j };
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll('#sc-map .sc-cell'), function (c) {
      var on = best && +c.dataset.i === best.i && +c.dataset.j === best.j;
      c.classList.toggle('now', on);
      if (on) c.setAttribute('aria-current', 'true'); else c.removeAttribute('aria-current');
    });
  }
  function renderMap(m) {
    var head = '<div class="sc-mh"></div>' + m.o2_values.map(function (x, i) { return '<div class="sc-mh">' + (i % 2 === 0 ? x : '') + '</div>'; }).join('');
    var body = m.pressure_values.map(function (y, j) {
      return '<div class="sc-mh">' + y.toFixed(1) + '</div>' + m.o2_values.map(function (x, i) {
        var s = m.cells[j][i];
        return '<button type="button" class="sc-cell ' + s + '" data-i="' + i + '" data-j="' + j + '" data-o2="' + x + '" data-p="' + y +
          '" aria-label="' + x + '% O₂, ' + y.toFixed(1) + ' atm: ' + s + '" title="' + x + '% O₂, ' + y.toFixed(1) + ' atm: ' + s + '">' + LETTER[s] + '</button>';
      }).join('');
    }).join('');
    var c = m.counts, g = m.gravity_g;
    $('sc-map').innerHTML = '<h3>' + t('mapTitle') + ': ' + esc(m.fuel) + ' · ' + (g ? esc(g) + ' g' : t('micro2')) + '</h3>' +
      (m.warnings || []).map(function (w) { return '<p class="sc-warn" role="note">' + esc(w) + '</p>'; }).join('') +
      '<p class="sc-lead">' + t('mapHelp', { t: c.TESTED, p: c.PARTIAL, g: c.GAP, n: c.TESTED + c.PARTIAL + c.GAP }) + '</p>' +
      '<div class="sc-grid" style="grid-template-columns:44px repeat(' + m.o2_values.length + ',1fr)">' + head + body + '</div>' +
      '<p class="sc-note">' + m.limitations.map(esc).join(' ') + '</p>';
    paintMarker();
  }
  function loadMap(force) {
    var fuel = $('sc-fuel').value, g = val('g'), key = fuel + '|' + g + '|' + lang(), my = ++mapSeq;
    if (!force && key === mapKey && mapData) { paintMarker(); return; }
    post('/api/scenario/grid', { fuel: fuel, gravity_g: g })
      .then(function (j) { if (my === mapSeq && j.status === 'OK') { mapKey = key; mapData = j.data; renderMap(j.data); } })
      .catch(function () { /* the check above already reports an unreachable backend */ });
  }
  $('sc-panel').addEventListener('click', function (ev) {
    var c = ev.target.closest ? ev.target.closest('.sc-cell') : null;
    if (!c) return;
    [['o2', c.dataset.o2], ['p', c.dataset.p]].forEach(function (kv) {
      $(kv[0]).value = kv[1];
      $(kv[0]).dispatchEvent(new Event('input', { bubbles: true }));
    });
  });

  // ---- fuel lists kept in step -----------------------------------------------------------------------
  function note(f) { $('sc-fuelnote').textContent = (f && !DROPLET[f]) ? t('dropNote', { f: f }) : ''; }
  function refreshAll() { run(); loadMap(); }
  function onPanelFuel() {
    var f = $('sc-fuel').value; curFuel = f; note(f);
    var anim = $('f-fuel');
    if (anim && DROPLET[f] && anim.value !== f && !syncing) {
      syncing = true; anim.value = f; anim.dispatchEvent(new Event('change', { bubbles: true })); syncing = false;
    }
    refreshAll();
  }
  function onAnimFuel() {
    if (syncing) return;
    var f = $('f-fuel').value;
    if (f && $('sc-fuel').value !== f) { $('sc-fuel').value = f; curFuel = f; note(f); refreshAll(); }
  }
  function later() { clearTimeout(timer); timer = setTimeout(refreshAll, 250); }

  build();
  var anim = $('f-fuel');
  if (anim) anim.addEventListener('change', onAnimFuel);
  // the rail controls are updated by app.js listeners that were registered first, so values are current here
  var rail = document.querySelector('.rail');
  if (rail) { rail.addEventListener('input', later); rail.addEventListener('change', later); rail.addEventListener('click', later); }
  window.addEventListener('ff-lang', function () { build(); note(curFuel); mapData = null; refreshAll(); if (lastRep) loadReport(lastRep); });
  note(curFuel);
  refreshAll();
})();
