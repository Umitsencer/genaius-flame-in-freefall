/* Shared navigation pill. Add to any page, last in <body>:
 *   <link rel="stylesheet" href="css/nav.css">
 *   <script src="js/nav.js" data-active="lab|fire|case|data"></script>
 * To add a page, add one entry to ITEMS (English label, Turkish short label and full name). */
(function () {
  'use strict';
  var script = document.currentScript, active = script ? script.getAttribute('data-active') : '';
  var I = window.FF && window.FF.i18n;
  var ITEMS = {
    left: [
      { id: 'lab', en: 'Material lab', tr: 'Laboratuvar', trFull: 'Malzeme laboratuvarı', enShort: 'Lab', trShort: 'Lab', href: 'material-lab.html' },
      { id: 'fire', en: 'Fire animation', tr: 'Animasyon', trFull: 'Yangın animasyonu', enShort: 'Fire', trShort: 'Yangın', href: 'fire.html' }
    ],
    right: [
      { id: 'case', en: 'Case study', tr: 'Vaka', trFull: 'SAFFIRE Vaka İncelemesi', enShort: 'Case', trShort: 'Vaka', href: 'case-saffire.html' },
      { id: 'data', en: 'Data', tr: 'Veri', trFull: 'Veri', href: 'data.html' }
    ]
  };
  var isTr = function () { return !!I && I.lang() === 'tr'; };

  function item(it) {
    var tr = isTr(), name = tr ? it.tr : it.en, full = tr ? it.trFull : it.en;
    if (it.soon) return '<span class="gn-it off" title="' + (tr ? 'Yakında' : 'Coming soon') + '">' + name + '</span>';
    var inner = it.enShort ? '<span class="gn-full">' + name + '</span><span class="gn-short">' + (tr ? it.trShort : it.enShort) + '</span>' : name;
    return '<a class="gn-it' + (it.id === active ? ' on' : '') + '" href="' + it.href + '"' + (it.id === active ? ' aria-current="page"' : '') + ' aria-label="' + full + '">' + inner + '</a>';
  }
  if (!document.querySelector('link[href*="family=Inter"]')) {
    var f = document.createElement('link'); f.rel = 'stylesheet'; f.href = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap'; document.head.appendChild(f);
  }
  var nav = document.createElement('nav'); nav.className = 'gn-nav'; nav.setAttribute('data-no-i18n', '');   // its labels are handled here
  function paintNav() {
    nav.setAttribute('aria-label', isTr() ? 'Ana menü' : 'Main');
    nav.innerHTML = '<div class="gn-grp">' + ITEMS.left.map(item).join('') + '</div>' +
      '<div class="gn-brand-wrap"><a class="gn-badge" href="data.html" aria-label="GenAIus, ' + (isTr() ? 'veri panosu' : 'research dashboard') + '"><img src="assets/logo.jpg" alt=""></a></div>' +
      '<div class="gn-grp">' + ITEMS.right.map(item).join('') + '</div>';
  }
  paintNav();
  document.body.insertBefore(nav, document.body.firstChild);

  // Language button (Turkish / English). It shows the language you would switch to.
  if (I) {
    var lb = document.createElement('button');
    lb.type = 'button'; lb.className = 'gn-lang'; lb.setAttribute('aria-label', 'Dil / Language'); lb.setAttribute('data-no-i18n', '');
    var paint = function () { lb.textContent = isTr() ? 'EN' : 'TR'; lb.title = isTr() ? 'Switch to English' : 'Türkçeye geç'; };
    lb.addEventListener('click', function () { I.set(isTr() ? 'en' : 'tr'); });
    window.addEventListener('ff-lang', function () { paint(); paintNav(); }); paint();
    document.body.insertBefore(lb, nav.nextSibling);
  }

  // Keep navigation available on upward scroll and while using the keyboard.
  var bars = [nav].concat(lb ? [lb] : []);
  var lastY = window.pageYOffset || 0, scrollPending = false;
  function showBars() { bars.forEach(function (bar) { bar.classList.remove('gn-hidden'); }); }
  function updateScrollVisibility() {
    scrollPending = false;
    var y = Math.max(0, window.pageYOffset || 0), delta = y - lastY;
    var focused = bars.some(function (bar) { return bar.contains(document.activeElement); });
    if (y < 80 || delta < -6 || focused) showBars();
    else if (delta > 6) bars.forEach(function (bar) { bar.classList.add('gn-hidden'); });
    if (Math.abs(delta) > 6 || y < 80) lastY = y;
  }
  window.addEventListener('scroll', function () {
    if (!scrollPending) { scrollPending = true; requestAnimationFrame(updateScrollVisibility); }
  }, { passive: true });
  bars.forEach(function (bar) { bar.addEventListener('focusin', showBars); });
})();
