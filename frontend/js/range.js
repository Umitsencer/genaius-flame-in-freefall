/* Two-handle range slider built from two native range inputs, so keyboard and screen readers work.
 * FF.range(host, { label, unit, min, max, step, value: [lo, hi], digits, onChange(lo, hi) }) -> { get, set, reset, isFull } */
(function (root) {
  'use strict';
  root.FF = root.FF || {};
  var uid = 0;
  root.FF.range = function (host, o) {
    var id = 'rs' + (++uid), min = o.min, max = o.max, step = o.step || 1, d = o.digits == null ? 0 : o.digits;
    var lo = o.value ? o.value[0] : min, hi = o.value ? o.value[1] : max, start = [lo, hi];
    host.classList.add('rs');
    host.innerHTML = '<div class="rs-head"><span class="rs-label" id="' + id + 'l">' + o.label + '</span><output class="rs-out" for="' + id + 'a ' + id + 'b"></output></div>' +
      '<div class="rs-track"><div class="rs-rail"></div><div class="rs-fill"></div>' +
      '<input type="range" id="' + id + 'a" min="' + min + '" max="' + max + '" step="' + step + '" aria-label="' + o.label + ', lowest">' +
      '<input type="range" id="' + id + 'b" min="' + min + '" max="' + max + '" step="' + step + '" aria-label="' + o.label + ', highest"></div>';
    var a = host.querySelector('#' + id + 'a'), b = host.querySelector('#' + id + 'b'), fill = host.querySelector('.rs-fill'), out = host.querySelector('.rs-out');
    function f(v) { return (Math.round(v * Math.pow(10, d)) / Math.pow(10, d)).toString(); }
    function isFull() { return lo <= min && hi >= max; }
    function paint() {
      a.value = lo; b.value = hi;
      var span = max - min || 1, l = (lo - min) / span, r = (hi - min) / span;
      fill.style.left = 'calc(9px + (100% - 18px) * ' + l + ')'; fill.style.width = 'calc((100% - 18px) * ' + (r - l) + ')';
      a.style.zIndex = lo > min + span / 2 ? 3 : 2; b.style.zIndex = 2;
      var u = o.unit ? ' ' + o.unit : '';
      out.textContent = isFull() ? 'Any' : lo <= min ? 'Up to ' + f(hi) + u : hi >= max ? f(lo) + u + ' and above' : f(lo) + ' to ' + f(hi) + u;
      out.classList.toggle('on', !isFull());
      a.setAttribute('aria-valuetext', f(lo) + u); b.setAttribute('aria-valuetext', f(hi) + u);
    }
    function change() { if (o.onChange) o.onChange(lo, hi); }
    a.addEventListener('input', function () { lo = Math.min(parseFloat(a.value), hi); paint(); change(); });
    b.addEventListener('input', function () { hi = Math.max(parseFloat(b.value), lo); paint(); change(); });
    paint();
    return {
      get: function () { return [lo, hi]; }, isFull: isFull,
      set: function (x, y) { lo = x; hi = y; paint(); change(); },
      reset: function () { lo = start[0]; hi = start[1]; paint(); }
    };
  };
})(window);
