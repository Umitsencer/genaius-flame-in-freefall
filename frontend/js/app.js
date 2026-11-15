/* Shell: shared environment state, tabs, module lifecycle. Add a module by registering it in FF.modules and ORDER. */
(function () {
  'use strict';
  var lib = FF.lib, ORDER = ['fire'];
  var env = { o2: 21, p: 1.0, g: 0, preset: 'iss' };
  var $ = function (id) { return document.getElementById(id); };
  var current = null;

  function paintRail() {
    $('o2').value = env.o2; $('o2-out').textContent = env.o2 + '%';
    $('p').value = env.p; $('p-out').textContent = env.p.toFixed(2) + ' atm';
    $('g').value = env.g; $('g-out').textContent = env.g === 0 ? '0 g' : env.g.toFixed(3).replace(/0+$/, '').replace(/\.$/, '') + ' g';
    $('preset').value = env.preset;
    var pr = lib.PRESETS.filter(function (x) { return x.id === env.preset; })[0];
    $('preset-note').textContent = pr ? pr.note : '';
    Array.prototype.forEach.call($('gravity-seg').children, function (b) {
      b.setAttribute('aria-pressed', String(Math.abs(parseFloat(b.dataset.g) - env.g) < 0.0005));
    });
    var uses = current ? FF.modules[current].uses : [];
    ['o2', 'p', 'g'].forEach(function (k) {
      document.querySelector('.slider[data-key="' + k + '"]').classList.toggle('idle', uses.indexOf(k) < 0);
    });
    var unused = ['o2', 'p', 'g'].filter(function (k) { return uses.indexOf(k) < 0; }).map(function (k) { return { o2: 'oxygen', p: 'pressure', g: 'gravity' }[k]; });
    $('uses-note').textContent = unused.length ? 'This view does not use ' + unused.join(' or ') + '. The test tables behind it do not record that value.' : '';
  }

  function changed(fromUser) {
    if (fromUser) env.preset = 'custom';
    paintRail();
    if (current) FF.modules[current].update(env);
  }

  function show(id) {
    if (current) FF.modules[current].unmount();
    current = id;
    if ($('tabs')) Array.prototype.forEach.call($('tabs').children, function (t) { t.setAttribute('aria-selected', String(t.dataset.id === id)); });
    FF.modules[id].mount($('view'), env);
    paintRail();
    try { history.replaceState(null, '', '#' + id); } catch (e) { /* file:// */ }
  }

  function init() {
    if ($('tabs')) ORDER.forEach(function (id) {
      var b = document.createElement('button');
      b.className = 'tab'; b.type = 'button'; b.setAttribute('role', 'tab'); b.dataset.id = id; b.textContent = FF.modules[id].title;
      b.addEventListener('click', function () { show(id); });
      $('tabs').appendChild(b);
    });
    $('preset').innerHTML = lib.PRESETS.map(function (p) { return '<option value="' + p.id + '">' + p.label + '</option>'; }).join('');
    lib.GRAVITY.forEach(function (g) {
      var b = document.createElement('button'); b.type = 'button'; b.dataset.g = g.g; b.textContent = g.label;
      b.addEventListener('click', function () { env.g = g.g; changed(true); });
      $('gravity-seg').appendChild(b);
    });
    $('preset').addEventListener('change', function (e) {
      var p = lib.PRESETS.filter(function (x) { return x.id === e.target.value; })[0];
      if (p.id !== 'custom') { env.o2 = p.o2; env.p = p.p; env.g = p.g; }
      env.preset = p.id; changed(false);
    });
    $('o2').addEventListener('input', function (e) { env.o2 = parseFloat(e.target.value); changed(true); });
    $('p').addEventListener('input', function (e) { env.p = parseFloat(e.target.value); changed(true); });
    $('g').addEventListener('input', function (e) { env.g = Math.round(parseFloat(e.target.value) * 1000) / 1000; changed(true); });
    var qs = new URLSearchParams(location.search), pre = lib.PRESETS.filter(function (x) { return x.id === qs.get('preset'); })[0];
    if (pre && pre.id !== 'custom') { env.o2 = pre.o2; env.p = pre.p; env.g = pre.g; env.preset = pre.id; }
    var start = location.hash.slice(1);
    show(ORDER[0]);
  }

  init();
})();
