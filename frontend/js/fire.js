/* Fire animation: a burning fuel droplet whose size history and ending come from live /api/analytics/flex data.
 * Flame brightness and shape are an editorial conceptual illustration (buoyancy scaling), never a CFD or time-series replay. */
(function () {
  'use strict';
  var DURATION = 12;           // seconds of screen time for one burn at 1x
  var N = 170;                 // flame blobs
  var S = { fuel: 'Methanol', u: 0, playing: true, speed: 1, env: null, ev: null, par: null, raf: 0, last: 0, hold: 0, seq: 0, ctrl: null, error: null };
  var el = {};

  function rnd(i, k) { var s = Math.sin(i * 127.1 + k * 311.7) * 43758.5453; return s - Math.floor(s); }
  function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }
  function smooth(a, b, v) { var t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); }
  function pct(v) { return Math.round(v * 100) + '%'; }

  function params() {
    var ev = S.ev || {};
    var top = ev.top ? ev.top.name : 'Extinction';
    var d0 = ev.d0 || 3, dExt = ev.dExt;
    var dEnd = top === 'Extinction' ? (dExt || 0.35 * d0) : top === 'Completion' ? 0.08 * d0 : top === 'Disruption' ? 0.7 * d0 : 0.5 * d0;
    return { top: top, d0: d0, dEnd: Math.min(dEnd, d0 * 0.95), T: ev.tBurn || 5 };
  }

  function sizeAt(u) { var p = S.par; return Math.sqrt(Math.max(0, p.d0 * p.d0 - (p.d0 * p.d0 - p.dEnd * p.dEnd) * u)); }
  function intensityAt(u) {
    var p = S.par, i = smooth(0, 0.08, u);
    if (p.top === 'Extinction') i *= 1 - smooth(0.9, 1, u);
    else if (p.top === 'Completion') i *= 1 - smooth(0.85, 1, u);
    else if (p.top === 'Disruption') i *= u > 0.92 ? 1 - smooth(0.92, 1, u) * 0.6 : 1;
    return i;
  }
  function phaseAt(u) {
    var p = S.par;
    if (u < 0.08) return 'Ignition';
    if (u < 0.9) return 'Burning';
    return p.top === 'Extinction' ? 'Flame out' : p.top === 'Completion' ? 'Droplet consumed' : p.top === 'Disruption' ? 'Droplet breakup' : 'End of test';
  }

  function draw(wall) {
    if (!S.par || !S.env) return;
    var c = el.canvas, dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
    var x = c.getContext('2d'); x.setTransform(dpr, 0, 0, dpr, 0, 0);
    x.globalCompositeOperation = 'source-over'; x.fillStyle = '#0b0b0c'; x.fillRect(0, 0, w, h);
    var env = S.env, p = S.par, u = S.u, d = sizeAt(u), I = intensityAt(u);
    var pxmm = Math.min(0.06 * h, 0.19 * h / p.d0), cx = w / 2, cy = h * 0.68;
    var gs = Math.pow(env.g, 0.6), rd = d / 2 * pxmm;
    var F = clamp(2.4 * (0.85 + (env.o2 - 21) / 50), 1.6, 3.4);
    var R = Math.max(F * rd * (0.4 + 0.6 * smooth(0, 0.08, u)), 0), H = R * 2.6;
    var meth = S.fuel === 'Methanol', lift = clamp((env.o2 - 21) / 25, 0, 0.5);
    var inner = meth ? [150, 190, 255] : [255, 214, 120], outer = meth ? [50, 100, 255] : [255, 110, 30];
    inner = inner.map(function (v) { return Math.round(v + (255 - v) * lift); });

    x.globalCompositeOperation = 'lighter';
    if (I > 0.01) for (var i = 0; i < N; i++) {
      var th = rnd(i, 1) * Math.PI * 2, zz = rnd(i, 2) * 2 - 1, rs = R * Math.sqrt(1 - zz * zz) * 0.98;  // points on a sphere, seen from the side
      var age = (wall * (0.7 + 0.5 * rnd(i, 5)) + rnd(i, 3)) % 1;
      var px = cx + Math.cos(th) * rs * (1 - 0.5 * gs * age) + (rnd(i, 6) - 0.5) * 6 * gs * age * 4;
      var py = cy + Math.sin(th) * rs - H * gs * (0.55 * age + 0.45 * age * age);
      var sz = R * (0.30 + 0.22 * rnd(i, 4)) * (1 - 0.45 * age) * (1 + 0.06 * Math.sin(wall * 9 + i));
      var a = I * Math.pow(1 - age, 1.3) * (0.11 + 0.09 * lift) * (Math.sin(th) > 0 ? 1 - 0.35 * gs : 1);
      if (sz < 1) continue;
      var g = x.createRadialGradient(px, py, 0, px, py, sz);
      g.addColorStop(0, 'rgba(' + inner.join(',') + ',' + a + ')');
      g.addColorStop(0.45, 'rgba(' + outer.join(',') + ',' + a * 0.6 + ')');
      g.addColorStop(1, 'rgba(' + outer.join(',') + ',0)');
      x.fillStyle = g; x.beginPath(); x.arc(px, py, sz, 0, Math.PI * 2); x.fill();
    }
    x.globalCompositeOperation = 'source-over';
    // droplet
    if (rd > 0.5) {
      var dg = x.createRadialGradient(cx - rd * 0.3, cy - rd * 0.3, rd * 0.1, cx, cy, rd);
      dg.addColorStop(0, 'rgba(235,244,255,0.95)'); dg.addColorStop(1, 'rgba(120,150,185,0.85)');
      x.fillStyle = dg; x.beginPath(); x.arc(cx, cy, rd, 0, Math.PI * 2); x.fill();
    }
    // breakup fragments
    if (p.top === 'Disruption' && u > 0.92) {
      x.fillStyle = 'rgba(200,220,255,0.8)';
      for (var j = 0; j < 14; j++) { var q = (u - 0.92) / 0.08, an = rnd(j, 9) * 6.283; x.beginPath(); x.arc(cx + Math.cos(an) * q * R * 1.6 * (0.5 + rnd(j, 8)), cy + Math.sin(an) * q * R * 1.6 * (0.5 + rnd(j, 7)), 1.6, 0, 6.283); x.fill(); }
    }
    // scale bar: 1 mm
    x.strokeStyle = '#7f8da0'; x.lineWidth = 1.5; x.beginPath(); x.moveTo(w - 16 - pxmm, h - 16); x.lineTo(w - 16, h - 16); x.stroke();
    x.fillStyle = '#98a6b5'; x.font = '12px "Inter", system-ui, sans-serif'; x.textAlign = 'right'; x.fillText('1 mm', w - 16, h - 22);

    el.phase.textContent = phaseAt(u);
    el.cap.textContent = (u * p.T).toFixed(1) + ' s of about ' + p.T.toFixed(1) + ' s, droplet ' + d.toFixed(2) + ' mm wide';
  }

  function loop(ts) {
    var dt = S.last ? Math.min(0.1, (ts - S.last) / 1000) : 0; S.last = ts;
    if (S.playing) {
      if (S.u >= 1) { S.hold += dt; if (S.hold > 1.6) { S.playing = false; el.play.textContent = 'Replay'; } }
      else { S.u = Math.min(1, S.u + dt * S.speed / DURATION); el.scrub.value = S.u; }
    }
    draw(ts / 1000);
    S.raf = requestAnimationFrame(loop);
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function mapConditionMatch(cm) {
    var outcomes = (cm && Array.isArray(cm.outcomes) ? cm.outcomes : []).map(function (o) {
      return { name: o.label, n: o.count, share: o.share };
    });
    var med = (cm && cm.medians) || {};
    return {
      level: cm && cm.match_level === 'matched' ? 'matched' : 'broad',
      n: cm && typeof cm.count === 'number' ? cm.count : 0,
      o2Win: cm && cm.o2_window_pct != null ? cm.o2_window_pct : 2,
      pWin: cm && cm.p_window_atm != null ? cm.p_window_atm : 0.1,
      o2Range: (cm && Array.isArray(cm.o2_range_pct) && cm.o2_range_pct.length === 2) ? cm.o2_range_pct : [0, 0],
      outcomes: outcomes,
      top: outcomes.length ? outcomes[0] : null,
      d0: med.d0_mm,
      dExt: med.d_ext_positive_mm,
      tBurn: med.burn_time_s,
      samplePks: (cm && Array.isArray(cm.sample_record_pks)) ? cm.sample_record_pks : []
    };
  }

  function evidenceHtml() {
    if (S.error) {
      return '<div class="callout gap"><strong>Unable to load live FLEX evidence.</strong> ' + esc(S.error) + ' <button type="button" class="ghost sm" id="f-retry">Retry</button></div>';
    }
    var ev = S.ev, env = S.env, fuel = S.fuel.toLowerCase();
    if (!ev) {
      return '<h3>What FLEX measured under these conditions</h3><p class="cond">Loading NASA PSI-69 condition matches from backend...</p>';
    }
    var cond = ev.level === 'matched'
      ? 'Matched on ' + fuel + ' droplets within ' + ev.o2Win + ' points of ' + env.o2 + '% oxygen and ' + ev.pWin.toFixed(2) + ' atm of ' + env.p.toFixed(2) + ' atm.'
      : 'No close match for ' + env.o2 + '% oxygen at ' + env.p.toFixed(2) + ' atm, so this shows all ' + ev.n + ' ' + fuel + ' tests, ' + ev.o2Range[0] + ' to ' + ev.o2Range[1] + '% oxygen.';
    var bar = ev.outcomes.map(function (o) {
      var cls = /^(Extinction|Disruption|Completion)$/.test(o.name) ? o.name : 'other';
      return '<span class="o-' + cls + '" style="flex:' + o.n + ' 1 0" title="' + esc(o.name + ': ' + o.n + ' of ' + ev.n + ' tests') + '">' + esc(o.name) + ' ' + pct(o.share) + '</span>';
    }).join('');
    var t = ev.top, f = '';
    if (t) f += '<span><b>' + esc(t.name) + '</b>' + t.n + ' of ' + ev.n + ' tests (' + pct(t.share) + ')</span>';
    if (ev.tBurn != null) f += '<span><b>' + ev.tBurn.toFixed(1) + ' s</b>median burn time</span>';
    if (ev.dExt != null) f += '<span><b>' + ev.dExt.toFixed(2) + ' mm</b>median droplet width when the flame went out (d_ext &gt; 0)</span>';
    var sampleLinks = ev.samplePks.slice(0, 4).map(function (pk) {
      return '<a class="lnk" href="data.html?exp=PSI-69&pick=' + encodeURIComponent(pk) + '#s-explorer">' + esc(pk) + '</a>';
    }).join(' · ');
    var note = env.g > 0
      ? '<div class="callout gap" style="margin-top:14px"><strong>FLEX ran in microgravity.</strong> No table here was measured at ' + Number(env.g.toFixed(3)) + ' g. The droplet history and ending come from the data. The flame shape at this gravity is scaled from buoyancy and is not measured.</div>' : '';
    return '<h3>What FLEX measured under these conditions</h3><p class="cond">' + esc(cond) + '</p><div class="bar">' + bar + '</div><div class="facts">' + f + '</div>' +
      (sampleLinks ? '<p class="cond" style="margin-top:10px">Sample PSI-69 records: ' + sampleLinks + '</p>' : '') + note;
  }

  function paintEvidence() {
    el.evidence.innerHTML = evidenceHtml();
    var retry = el.evidence.querySelector('#f-retry');
    if (retry) retry.addEventListener('click', refresh);
  }

  function refresh() {
    if (!el.tag || !el.evidence) return;
    el.tag.textContent = S.env.g > 0
      ? 'Conceptual illustration (buoyancy scaled) — not a measured time-series replay or CFD'
      : 'Conceptual illustration — not a measured time-series replay or CFD';
    if (!FF.api || typeof FF.api.analyticsFlex !== 'function') {
      S.error = 'Backend API client not available.';
      paintEvidence();
      return;
    }
    var seq = ++S.seq;
    if (S.ctrl && typeof S.ctrl.abort === 'function') S.ctrl.abort();
    S.ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    S.error = null;
    paintEvidence();
    FF.api.analyticsFlex({
      fuel: S.fuel,
      target_o2_pct: S.env.o2,
      target_p_atm: S.env.p
    }, S.ctrl ? { signal: S.ctrl.signal } : undefined).then(function (envResp) {
      if (seq !== S.seq) return;
      var d = (envResp && envResp.data) || {};
      S.ev = mapConditionMatch(d.condition_match);
      S.par = params();
      S.error = null;
      paintEvidence();
    }).catch(function (err) {
      if (err && err.name === 'AbortError') return;
      if (seq !== S.seq) return;
      S.error = (err && err.message) ? err.message : 'Unable to reach /api/analytics/flex.';
      paintEvidence();
    });
  }

  FF.modules = FF.modules || {};
  FF.modules.fire = {
    id: 'fire', title: 'Fire animation', uses: ['o2', 'p', 'g'],
    mount: function (root, env) {
      S.env = env; S.u = clamp(parseFloat(new URLSearchParams(location.search).get('u')) || 0, 0, 1); S.last = 0; S.hold = 0;
      S.playing = !(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) && S.u === 0;
      root.innerHTML = '<div class="view-head"><h2>How a droplet fire unfolds</h2><p>A single fuel droplet burns from ignition to its recorded ending. Its size and the ending come from the FLEX tests closest to your oxygen and pressure. Gravity changes the flame shape: a sphere with none, a rising plume as it grows.</p></div>' +
        '<div class="fire-grid"><div class="canvas-wrap"><canvas id="flame" aria-label="Animated burning fuel droplet"></canvas>' +
        '<div class="stage-phase" id="f-phase"></div><div class="stage-tag" id="f-tag"></div><div class="stage-cap" id="f-cap"></div></div>' +
        '<div class="controls"><button class="btn" id="f-play" type="button"></button>' +
        '<div class="grow"><input type="range" id="f-scrub" min="0" max="1" step="0.001" value="0" aria-label="Burn progress"></div>' +
        '<label>Fuel <select id="f-fuel"><option>Methanol</option><option>Heptane</option></select></label>' +
        '<label>Speed <select id="f-speed"><option value="0.5">Half</option><option value="1" selected>Normal</option><option value="2">Double</option></select></label></div>' +
        '<div class="evidence" id="f-evidence"></div></div>';
      var q = function (id) { return root.querySelector(id); };
      el = { canvas: q('#flame'), phase: q('#f-phase'), tag: q('#f-tag'), cap: q('#f-cap'), play: q('#f-play'), scrub: q('#f-scrub'), evidence: q('#f-evidence') };
      el.play.textContent = S.playing ? 'Pause' : 'Play'; el.scrub.value = S.u;
      el.play.addEventListener('click', function () {
        if (S.u >= 1) { S.u = 0; S.hold = 0; S.playing = true; }
        else S.playing = !S.playing;
        el.play.textContent = S.playing ? 'Pause' : 'Play';
      });
      el.scrub.addEventListener('input', function (e) { S.u = parseFloat(e.target.value); S.hold = 0; S.playing = false; el.play.textContent = 'Play'; });
      q('#f-fuel').addEventListener('change', function (e) { S.fuel = e.target.value; S.u = 0; refresh(); });
      q('#f-speed').addEventListener('change', function (e) { S.speed = parseFloat(e.target.value); });
      S.par = params();
      refresh();
      cancelAnimationFrame(S.raf); S.raf = requestAnimationFrame(loop);
    },
    update: function (env) { S.env = env; refresh(); },
    unmount: function () { cancelAnimationFrame(S.raf); }
  };
})();
