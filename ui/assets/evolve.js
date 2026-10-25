/* GoalGA · scena dell'evoluzione (canvas 2D, nessuna dipendenza).
   Riceve la configurazione da window.GX (vedi ui/stage.py):
   - mode "replay": riproduce l'evoluzione reale registrata dall'algoritmo genetico;
   - mode "ambient": sfondo decorativo della home, con un mini algoritmo genetico simulato. */
(function () {
  "use strict";
  var GX = window.GX || {};
  var MODE = GX.mode || "replay";
  var AMBIENT = MODE === "ambient";
  var TXT = GX.text || {};
  var REDUCED = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var RISK = ["#2DD4BF", "#38BDF8", "#60A5FA", "#818CF8", "#A78BFA", "#C084FC", "#E879F9", "#F472B6", "#FB923C"];

  var cv = document.getElementById("cv");
  var ctx = cv.getContext("2d");
  var root = document.getElementById("root");
  var $ = function (id) { return document.getElementById(id); };
  var api = window.__gx = { mode: MODE, done: false, frame: 0, frames: 0, cycles: 0, restart: null };

  /* ---------------------------------------------------------------- utilità */
  function clamp(x, a, b) { return Math.max(a, Math.min(b, x)); }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function hex(h) { return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]; }
  var STOPS = RISK.map(hex);
  function riskRGB(p) {
    var x = clamp(p, 0, 1) * (STOPS.length - 1), i = Math.min(STOPS.length - 2, Math.floor(x)), a = x - i;
    var c0 = STOPS[i], c1 = STOPS[i + 1];
    return [lerp(c0[0], c1[0], a), lerp(c0[1], c1[1], a), lerp(c0[2], c1[2], a)];
  }
  function rgba(c, a) { return "rgba(" + Math.round(c[0]) + "," + Math.round(c[1]) + "," + Math.round(c[2]) + "," + a + ")"; }
  /* numeri nella lingua dell'interfaccia (GX.locale è un tag BCP 47, es. it-IT) */
  var LOC = GX.locale || "en-GB", PCT = GX.pctSuffix || "%", NFS = {}, COMPACT = null;
  function nf(d) {
    var k = d || 0;
    if (!NFS[k]) {
      try { NFS[k] = new Intl.NumberFormat(LOC, { minimumFractionDigits: k, maximumFractionDigits: k, useGrouping: "always" }); }
      catch (e) { NFS[k] = { format: function (n) { return Number(n).toFixed(k); } }; }
    }
    return NFS[k];
  }
  function num(n, d) { return nf(d).format(n); }
  function pct(x, d) { return num(x * 100, d === undefined ? 1 : d) + PCT; }
  function compact(n) {
    try {
      COMPACT = COMPACT || new Intl.NumberFormat(LOC, { notation: "compact", maximumFractionDigits: 1 });
      return COMPACT.format(n);
    } catch (e) { return num(n, 0); }
  }
  function b64(s) {
    var raw = atob(s), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  function mulberry(seed) {
    var a = seed >>> 0;
    return function () {
      a += 0x6D2B79F5; var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* ---------------------------------------------------------------- dati */
  var D = null;   // {T, K, F, N, pop, champ, gens, pr, irr, score, evals, total}

  function fromPayload(p) {
    return { T: p.T, K: p.K, F: p.F, N: p.N, pop: b64(p.pop), champ: b64(p.champ), gens: p.gens, pr: p.pr,
             irr: p.irr, score: p.score, evals: p.evals, total: p.generations };
  }

  /* mini algoritmo genetico decorativo: evolve profili a gradini non crescenti verso un profilo "bersaglio" */
  function makeAmbient(seed) {
    var r = mulberry(seed), T = 26, K = 9, N = 64, G = 260, F = 130;
    function desc(a) { return a.sort(function (x, y) { return y - x; }); }
    function randStair() {
      var hi = 3 + Math.floor(r() * 7), lo = 1 + Math.floor(r() * Math.min(hi, 4)), g = [];
      for (var t = 0; t < T; t++) g.push(lo + Math.floor(r() * (hi - lo + 1)));
      return desc(g);
    }
    var target = [], level = 7 + Math.floor(r() * 3), plateau = 0, run = 4 + Math.floor(r() * 5);
    for (var t = 0; t < T; t++) {
      target.push(level);
      if (++plateau >= run && level > 1) { level = Math.max(1, level - 1 - Math.floor(r() * 2)); plateau = 0; run = 4 + Math.floor(r() * 5); }
    }
    function fit(g) { var s = 0; for (var q = 0; q < T; q++) s -= Math.abs(g[q] - target[q]); return s; }
    var pop = [], i;
    for (i = 0; i < N; i++) pop.push(randStair());
    var picks = {}, j;
    for (j = 0; j < F; j++) picks[Math.round(Math.pow(G, j / (F - 1))) - 1] = true;
    var frames = [], champs = [], gens = [];
    for (var g = 0; g < G; g++) {
      var scored = pop.map(function (x) { return { g: x, f: fit(x) }; }).sort(function (a, b) { return b.f - a.f; });
      if (picks[g] || g === G - 1) {
        frames.push(scored.map(function (s) { return s.g.slice(); }));
        champs.push(scored[0].g.slice());
        gens.push(g + 1);
      }
      var next = [scored[0].g.slice(), scored[1].g.slice()];
      while (next.length < N) {
        var pa = scored[Math.min(Math.floor(r() * N), Math.floor(r() * N))].g;
        var pb = scored[Math.min(Math.floor(r() * N), Math.floor(r() * N))].g;
        var cut = 1 + Math.floor(r() * (T - 1)), kid = pa.slice(0, cut).concat(pb.slice(cut));
        if (r() < 0.45) {
          var pos = Math.floor(r() * T);
          kid[pos] = clamp(kid[pos] + (r() < 0.5 ? -1 : 1) * (1 + Math.floor(r() * 2)), 1, K);
        }
        next.push(desc(kid));
      }
      pop = next;
    }
    var Fn = frames.length, popArr = new Uint8Array(Fn * N * T), champArr = new Uint8Array(Fn * T);
    for (var f = 0; f < Fn; f++) {
      for (var k = 0; k < N; k++) for (var q = 0; q < T; q++) popArr[(f * N + k) * T + q] = frames[f][k][q];
      for (var u = 0; u < T; u++) champArr[f * T + u] = champs[f][u];
    }
    return { T: T, K: K, F: Fn, N: N, pop: popArr, champ: champArr, gens: gens, pr: [], irr: [], score: [], evals: [], total: G };
  }

  /* ---------------------------------------------------------------- geometria */
  var dpr = Math.min(2, window.devicePixelRatio || 1), W = 0, H = 0, P = null, vGrad = null;
  function X(t) { return P.x0 + (P.x1 - P.x0) * t / D.T; }
  function Y(level) { return P.y1 - (P.y1 - P.y0) * (level - 0.5) / D.K; }

  function layout() {
    var box = cv.parentNode.getBoundingClientRect();
    W = Math.max(260, box.width); H = Math.max(200, box.height);
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    cv.style.width = W + "px"; cv.style.height = H + "px";
    var small = W < 560;
    if (AMBIENT) P = { x0: -0.04 * W, x1: 1.04 * W, y0: 0.14 * H, y1: 0.9 * H };
    else P = { x0: small ? 38 : 66, x1: W - (small ? 14 : 30), y0: 16, y1: H - (small ? 70 : 82) };
    if (D) {
      vGrad = ctx.createLinearGradient(0, Y(1) * dpr, 0, Y(D.K) * dpr);
      for (var k = 0; k < D.K; k++) vGrad.addColorStop(k / Math.max(1, D.K - 1), rgba(riskRGB(k / Math.max(1, D.K - 1)), 1));
    }
  }

  /* ---------------------------------------------------------------- stato */
  var S = { start: null, fp: 0, u: 0, done: false, doneAt: 0, pulse: 0, lastScore: -1, flash: [], lastLv: [], prevTs: 0, amb: 1, lastDraw: 0, frozen: false };
  var DUR = GX.duration || 9500, HOLD = 1500, LEAD = 1200;

  /* ritmo della riproduzione: più tempo dove la popolazione cambia molto, scorrimento rapido dove non succede nulla */
  function buildPace() {
    var F = D.F, n = D.N * D.T, motion = new Float32Array(F), peak = 1e-9, f, k;
    for (f = 1; f < F; f++) {
      var s = 0, a = f * n, b = (f - 1) * n;
      for (k = 0; k < n; k++) s += Math.abs(D.pop[a + k] - D.pop[b + k]);
      motion[f] = s / n; if (motion[f] > peak) peak = motion[f];
    }
    var cum = new Float32Array(F);
    for (f = 1; f < F; f++) {
      var better = D.score && D.score[f] > D.score[f - 1] + 1e-9 ? 1 : 0;
      cum[f] = cum[f - 1] + 0.35 + 2.8 * Math.pow(motion[f] / peak, 0.7) + 0.9 * better;
    }
    var total = Math.max(1e-9, cum[F - 1]);
    return function (u) {
      var target = clamp(u, 0, 1) * total, lo = 0, hi = F - 1;
      while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (cum[mid] <= target) lo = mid; else hi = mid; }
      var span = cum[hi] - cum[lo];
      return lo + (span > 0 ? clamp((target - cum[lo]) / span, 0, 1) : 0);
    };
  }
  var pace = function (u) { return (D.F - 1) * u; };

  /* ---------------------------------------------------------------- disegno */
  function stairs(get, f0, f1, a, jitter) {
    ctx.beginPath();
    var dy = (jitter || 0) * dpr;
    for (var t = 0; t < D.T; t++) {
      var y = Y(lerp(get(f0, t), get(f1, t), a)) * dpr + dy, x0 = X(t) * dpr, x1 = X(t + 1) * dpr;
      if (t === 0) ctx.moveTo(x0, y); else ctx.lineTo(x0, y);
      ctx.lineTo(x1, y);
    }
  }
  function roundRect(x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }
  function text(str, x, y, size, color, align, weight) {
    ctx.font = (weight || 500) + " " + (size * dpr) + "px Inter, system-ui, sans-serif";
    ctx.fillStyle = color; ctx.textAlign = align || "left"; ctx.textBaseline = "alphabetic";
    ctx.fillText(str, x * dpr, y * dpr);
  }
  function axes() {
    var T = D.T, K = D.K, MUTED = "rgba(164,172,189,.9)";
    ctx.lineWidth = dpr; ctx.strokeStyle = "rgba(255,255,255,.05)";
    for (var k = 1; k <= K; k++) { ctx.beginPath(); ctx.moveTo(P.x0 * dpr, Y(k) * dpr); ctx.lineTo(P.x1 * dpr, Y(k) * dpr); ctx.stroke(); }
    text(TXT.riskHigh || "High", P.x0 - 10, Y(K) + 4, 10.5, MUTED, "right", 600);
    text(TXT.riskLow || "Low", P.x0 - 10, Y(1) + 4, 10.5, MUTED, "right", 600);
    ctx.save(); ctx.translate(14 * dpr, (P.y0 + P.y1) / 2 * dpr); ctx.rotate(-Math.PI / 2);
    text(TXT.risk || "RISK", 0, 0, 10, "rgba(108,117,137,.95)", "center", 700); ctx.restore();
    var step = T <= 6 ? 1 : T <= 12 ? 2 : T <= 40 ? 5 : 10, y = P.y1 + 26;
    text(TXT.today || "Today", X(0), y, 11, MUTED, "center", 600);
    for (var t = step; t <= T; t += step) {
      if (T - t < step / 2 && t !== T) continue;
      var last = t + step > T, labels = TXT.yearLabels || {};
      text(last ? (labels[String(t)] || (t + " " + (TXT.years || "years"))) : String(t), X(t), y, 11, MUTED, "center", 500);
    }
    /* limite di rischio del profilo scelto: sopra la linea l'algoritmo non può andare */
    var cap = GX.cap || K;
    if (cap < K) {
      var yc = Y(cap + 0.5);
      ctx.fillStyle = "rgba(255,255,255,.025)"; ctx.fillRect(P.x0 * dpr, P.y0 * dpr, (P.x1 - P.x0) * dpr, (yc - P.y0) * dpr);
      ctx.save(); ctx.setLineDash([6 * dpr, 5 * dpr]); ctx.strokeStyle = "rgba(251,191,36,.55)"; ctx.lineWidth = dpr;
      ctx.beginPath(); ctx.moveTo(P.x0 * dpr, yc * dpr); ctx.lineTo(P.x1 * dpr, yc * dpr); ctx.stroke(); ctx.restore();
      text(TXT.cap || "Your risk limit", P.x1 - 6, yc - 6, 10.5, "rgba(251,191,36,.9)", "right", 650);
    }
    var goals = GX.goals || [];
    for (var i = 0; i < goals.length; i++) {
      var gx = X(goals[i].y), label = goals[i].label;
      ctx.save(); ctx.setLineDash([3 * dpr, 5 * dpr]); ctx.strokeStyle = "rgba(255,255,255,.2)"; ctx.lineWidth = dpr;
      ctx.beginPath(); ctx.moveTo(gx * dpr, P.y1 * dpr); ctx.lineTo(gx * dpr, (P.y0 + (label ? 22 : 6)) * dpr); ctx.stroke(); ctx.restore();
      if (!label) continue;
      ctx.font = "600 " + (11 * dpr) + "px Inter, system-ui, sans-serif";
      var w = ctx.measureText(label).width / dpr + 16, lx = clamp(gx - w / 2, P.x0, P.x1 - w);
      roundRect(lx * dpr, (P.y0 + 2) * dpr, w * dpr, 20 * dpr, 10 * dpr);
      ctx.fillStyle = "rgba(20,24,38,.92)"; ctx.fill(); ctx.strokeStyle = "rgba(255,255,255,.22)"; ctx.stroke();
      text(label, lx + w / 2, P.y0 + 16, 11, "#F4F6FB", "center", 650);
    }
  }
  function dna(f0, f1, a) {
    var T = D.T, K = D.K, top = P.y1 + 40, h = W < 560 ? 12 : 16, cw = (P.x1 - P.x0) / T;
    for (var c = 0; c < T; c++) {
      var lv = lerp(D.champ[f0 * T + c], D.champ[f1 * T + c], a), rounded = Math.round(lv);
      if (S.lastLv[c] !== undefined && S.lastLv[c] !== rounded) S.flash[c] = 1;
      S.lastLv[c] = rounded;
      roundRect((P.x0 + c * cw + 1) * dpr, top * dpr, Math.max(2, cw - 2) * dpr, h * dpr, 3 * dpr);
      ctx.fillStyle = rgba(riskRGB((lv - 1) / Math.max(1, K - 1)), 0.92); ctx.fill();
      if (S.flash[c] > 0.02) { ctx.fillStyle = "rgba(255,255,255," + (0.85 * S.flash[c]) + ")"; ctx.fill(); }
    }
    text(TXT.dna || "DNA of the best strategy", P.x0, top + h + 16, 11, "rgba(164,172,189,.9)", "left", 500);
  }

  function drawFrame(fp, now) {
    var f0 = Math.floor(fp), f1 = Math.min(D.F - 1, f0 + 1), a = fp - f0;
    var popAt = function (i) { return function (f, t) { return D.pop[(f * D.N + i) * D.T + t]; }; };
    var champAt = function (f, t) { return D.champ[f * D.T + t]; };
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, cv.width, cv.height);
    var fade = S.done ? lerp(1, AMBIENT ? 0.5 : 0.16, clamp((now - S.doneAt) / 900, 0, 1)) : 1;
    if (AMBIENT) fade *= S.amb;
    if (!AMBIENT) axes();

    /* filamenti: una strategia per linea, luminosi dove si sovrappongono (mescolanza additiva);
       le "scie" mostrano dove si trovava lo sciame poco prima, così si vede la direzione dell'evoluzione */
    ctx.globalCompositeOperation = "lighter";
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    ctx.strokeStyle = vGrad;
    var N = D.N, base = (AMBIENT ? 5.5 : 7.5) / N, k = fade * (AMBIENT ? 0.7 : 1);
    var swarm = function (fx, gain, limit) {
      var g0 = Math.floor(fx), g1 = Math.min(D.F - 1, g0 + 1), ga = fx - g0;
      for (var i = Math.min(N, limit) - 1; i >= 0; i--) {
        var r = N > 1 ? i / (N - 1) : 0, best = Math.max(0, 1 - i / 8);
        ctx.globalAlpha = clamp((base + 0.2 * Math.pow(1 - r, 4) + 0.18 * best) * k * gain, 0, 1);
        ctx.lineWidth = (i < 6 ? 2 : 1.5) * dpr;
        stairs(popAt(i), g0, g1, ga, ((i * 37) % 9 - 4) * 0.45);
        ctx.stroke();
      }
    };
    if (!AMBIENT && !S.done) {
      if (fp > 0.05) swarm(Math.max(0, fp - 2.6), 0.14, 36);
      if (fp > 0.05) swarm(Math.max(0, fp - 1.3), 0.3, 48);
    }
    swarm(fp, 1, N);

    /* campione: la miglior strategia trovata finora */
    ctx.globalCompositeOperation = "source-over";
    var breathe = S.done ? 0.5 + 0.5 * Math.sin(now / 520) : 0;
    ctx.strokeStyle = vGrad;
    stairs(champAt, f0, f1, a);
    ctx.globalAlpha = AMBIENT ? 0.16 * fade : 0.16 + 0.22 * S.pulse + 0.1 * breathe; ctx.lineWidth = (10 + 8 * S.pulse) * dpr; ctx.stroke();
    ctx.globalAlpha = AMBIENT ? 0.5 * fade : 0.95; ctx.lineWidth = (AMBIENT ? 2.4 : 4.2) * dpr; ctx.stroke();
    if (!AMBIENT) {
      ctx.strokeStyle = "#ffffff"; ctx.globalAlpha = 0.55 + 0.25 * S.pulse; ctx.lineWidth = 1.5 * dpr;
      stairs(champAt, f0, f1, a); ctx.stroke();
    }
    ctx.globalAlpha = 1;
    if (!AMBIENT) { ripples(f0, f1, a); dna(f0, f1, a); }
  }
  function ripples(f0, f1, a) {
    /* un'onda parte da ogni gene del campione che cambia: è la mutazione che ha funzionato */
    var n = 0, c;
    for (c = 0; c < D.T; c++) if (S.flash[c] > 0.03) n++;
    if (n === 0 || n > 6) return;               // se cambiano molti geni insieme, bastano le celle del DNA
    for (c = 0; c < D.T; c++) {
      var fl = S.flash[c];
      if (!(fl > 0.03)) continue;
      var lv = lerp(D.champ[f0 * D.T + c], D.champ[f1 * D.T + c], a), x = (X(c) + X(c + 1)) / 2, y = Y(lv);
      ctx.beginPath(); ctx.arc(x * dpr, y * dpr, (5 + 20 * (1 - fl)) * dpr, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(255,255,255," + (0.65 * fl) + ")"; ctx.lineWidth = 1.5 * dpr; ctx.stroke();
    }
  }

  /* ---------------------------------------------------------------- interfaccia (statistiche e narrazione) */
  var el = {};
  ["v-gen", "s-gen", "v-sims", "v-pr", "bar-pr", "bar-target", "v-irr", "stat-pr", "narr"].forEach(function (id) { el[id] = $(id); });
  var lastNarr = -1, PHASES = TXT.phases || [];
  /* la frase cambia con le fasi della ricerca: simulazioni, generazione dei percorsi, selezione, scelta finale */
  function narrate(u) {
    var idx = S.done ? PHASES.length : u < 0.07 ? 0 : u < 0.2 ? 1 : u < 0.45 ? 2 : u < 0.7 ? 3 : 4;
    idx = Math.min(idx, PHASES.length);
    if (idx === lastNarr || !el.narr) return;
    var first = lastNarr < 0;
    lastNarr = idx;
    el.narr.style.opacity = 0;
    window.setTimeout(function () {
      el.narr.textContent = idx >= PHASES.length ? (TXT.done || "") : (PHASES[idx] || "");
      el.narr.style.opacity = 1;
    }, first ? 0 : 160);
  }
  function hud(fp, u) {
    if (AMBIENT || !el["v-gen"]) return;
    var f0 = Math.floor(fp), f1 = Math.min(D.F - 1, f0 + 1), a = fp - f0, fi = Math.round(fp);
    var pr = lerp(D.pr[f0], D.pr[f1], a), i0 = D.irr[f0], i1 = D.irr[f1];
    el["v-gen"].textContent = num(D.gens[fi]);
    el["v-sims"].textContent = compact(D.evals[fi] * (GX.nScenarios || 1));
    el["v-pr"].textContent = pct(pr, 1);
    el["bar-pr"].style.width = clamp(pr * 100, 0, 100) + "%";
    el["stat-pr"].classList.toggle("ok", pr >= (GX.target || 1) - 1e-9);
    if (i0 === null || i1 === null || i0 === undefined) el["v-irr"].textContent = "—";
    else { var irr = lerp(i0, i1, a); el["v-irr"].textContent = (irr >= 0 ? "+" : "−") + pct(Math.abs(irr), 2); }
    narrate(u);
  }

  /* ---------------------------------------------------------------- ciclo di animazione */
  function finish(now) {
    S.done = true; S.doneAt = now; api.done = true; api.frame = D.F - 1; root.classList.add("done");
    S.fp = D.F - 1; hud(S.fp, 1);
    cv.setAttribute("aria-label", (TXT.aria || "Strategy evolution") + ": " + pct(D.pr[D.F - 1], 1));
  }
  function restart() {
    S.start = null; S.done = false; S.fp = 0; S.u = 0; S.lastScore = -1; S.pulse = 0; S.flash = []; S.lastLv = [];
    api.done = false; lastNarr = -1;
    root.classList.remove("done");
  }
  api.restart = restart;   /* uso interno (test): nell'interfaccia l'evoluzione si vede una volta sola */
  /* uso interno (test e anteprime): ferma la riproduzione su un fotogramma preciso */
  api.seek = function (fp) { S.frozen = true; S.fp = clamp(fp, 0, D.F - 1); S.u = S.fp / Math.max(1, D.F - 1); };

  function frame(ts) {
    var dt = Math.min(64, ts - (S.prevTs || ts)); S.prevTs = ts;
    for (var c = 0; c < S.flash.length; c++) if (S.flash[c]) S.flash[c] = Math.max(0, S.flash[c] - dt / 520);
    S.pulse = Math.max(0, S.pulse - dt / 700);

    if (AMBIENT) {
      if (S.start === null) S.start = ts;
      var run = ts - S.start, total = DUR + HOLD + 1200;
      if (run >= total) {
        D = makeAmbient(Math.floor(Math.random() * 1e9)); layout(); api.cycles++;
        S.start = ts; S.done = false; S.flash = []; S.lastLv = []; run = 0;
      }
      S.u = clamp(run / DUR, 0, 1);
      if (S.u >= 1 && !S.done) { S.done = true; S.doneAt = ts; }
      S.amb = clamp(run / 800, 0, 1) * clamp((total - run) / 1000, 0, 1);
      S.fp = (D.F - 1) * S.u;
    } else if (!S.done && !S.frozen) {
      if (S.start === null) S.start = ts + LEAD;
      S.u = clamp((ts - S.start) / DUR, 0, 1);
      S.fp = pace(S.u);
      var score = D.score[Math.floor(S.fp)];
      if (S.lastScore >= 0 && score > S.lastScore + 1e-9) S.pulse = 1;
      S.lastScore = score;
      api.frame = S.fp;
      if (S.u >= 1) finish(ts);
    }
    if (!(S.done && !AMBIENT && ts - S.lastDraw < 33)) {   // a riproduzione finita basta una cadenza ridotta
      hud(S.fp, S.u);
      drawFrame(S.fp, ts);
      S.lastDraw = ts;
    }
    window.requestAnimationFrame(frame);
  }

  /* ---------------------------------------------------------------- avvio */
  function relayout() {          // il ridimensionamento svuota il canvas: si ridisegna subito, senza sfarfallio
    layout();
    if (D && S.fp !== undefined) drawFrame(S.fp, performance.now());
  }
  function init() {
    D = AMBIENT ? makeAmbient(GX.seed || 7) : fromPayload(GX.data);
    if (!AMBIENT) pace = buildPace();
    api.frames = D.F;
    if (el["bar-target"]) el["bar-target"].style.left = clamp((GX.target || 1) * 100, 0, 100) + "%";
    if (el["s-gen"]) el["s-gen"].textContent = (TXT.of || "of") + " " + num(D.total);
    layout();
    if (typeof ResizeObserver !== "undefined") new ResizeObserver(relayout).observe(cv.parentNode);
    else window.addEventListener("resize", relayout);
    if (document.fonts && document.fonts.load) document.fonts.load("600 12px Inter").catch(function () {});
    if (REDUCED && !AMBIENT) { S.fp = D.F - 1; finish(performance.now() - 2000); drawFrame(S.fp, performance.now()); return; }
    window.requestAnimationFrame(frame);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
