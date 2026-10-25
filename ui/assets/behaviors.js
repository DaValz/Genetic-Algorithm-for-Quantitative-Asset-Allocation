/* GoalGA: comportamenti dell'interfaccia. Lo script è idempotente (può essere eseguito a ogni cambio di lingua).
   Nel testo non compare mai il simbolo di minore: st.html passa il contenuto a DOMPurify, che scarta gli script che lo contengono. */
(function () {
  var VERSION = "__VERSION__";          /* impronta del testo: se cambia, il vecchio script si disattiva e questo lo sostituisce */
  var previous = window.__gx;
  if (previous && previous.v === VERSION) { return; }
  if (previous && previous.off) {
    try { previous.off(); } catch (err) { /* già smontato */ }
  }
  var offs = [];
  window.__gx = {v: VERSION, off: function () { while (offs.length) { offs.pop()(); } }};
  var doc = document, root = doc.documentElement;
  var NAV = __NAV__;      /* prefissi dei pulsanti che cambiano schermata (theme.NAV_KEYS) */

  function on(target, type, handler, capture) {
    target.addEventListener(type, handler, capture);
    offs.push(function () { target.removeEventListener(type, handler, capture); });
  }
  function watch(target, options, handler) {
    var obs = new MutationObserver(handler);
    obs.observe(target, options);
    offs.push(function () { obs.disconnect(); });
  }

  function reduced() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  /* 1. Cambio schermata, in due tempi. Al clic la pagina sfuma subito, senza aspettare il server (gx-leaving). Quando
        la nuova schermata è arrivata e la dissolvenza è finita, gli elementi nuovi compaiono con la propria animazione; i
        resti della schermata precedente (elementi «stale», rimossi da Streamlit solo a fine esecuzione) restano nascosti
        (gx-swapped) finché lo script non termina. Un limite di tempo toglie comunque le classi. */
  function keyOf(btn) {
    var holder = btn.closest('[class*="st-key-"]');
    if (!holder) { return ""; }
    for (var i = 0; holder.classList.length > i; i++) {
      if (holder.classList[i].indexOf("st-key-") === 0) { return holder.classList[i].slice(7); }
    }
    return "";
  }
  function isNav(key) {
    for (var i = 0; NAV.length > i; i++) {
      if (key.indexOf(NAV[i]) === 0) { return true; }
    }
    return false;
  }
  function screenId() {
    var marker = doc.querySelector("[data-scroll]");
    return marker ? marker.getAttribute("data-scroll") : "";
  }
  var stop = null, MIN_OUT = 130;       /* durata minima della dissolvenza in uscita (ms) */
  offs.push(function () { if (stop) { stop(); } });
  function leave() {
    if (reduced()) { return; }
    if (stop) { stop(); }
    var from = screenId(), app = doc.querySelector('[data-testid="stApp"]');
    var ran = false, changed = false, phase = 1, t0 = Date.now();
    var timer = window.setTimeout(finish, 4000);
    var obs = new MutationObserver(check);
    function state() { return app ? app.getAttribute("data-test-script-state") : ""; }
    function finish() {
      if (stop !== finish) { return; }
      stop = null;
      window.clearTimeout(timer);
      obs.disconnect();
      root.classList.remove("gx-leaving");
      root.classList.remove("gx-swapped");
    }
    function show() {
      if (phase !== 1) { return; }
      phase = 2;
      window.requestAnimationFrame(function () {
        window.requestAnimationFrame(function () {
          if (stop !== finish) { return; }
          if (changed && state() === "running") {
            window.clearTimeout(timer);
            timer = window.setTimeout(finish, 180000);
            root.classList.add("gx-swapped");
            root.classList.remove("gx-leaving");
          } else {
            finish();
          }
        });
      });
    }
    function check() {
      if (state() === "running") { ran = true; }
      if (screenId() !== from) { changed = true; }
      if (phase === 1 && (changed || (ran && state() === "notRunning"))) {
        window.setTimeout(show, Math.max(0, MIN_OUT - (Date.now() - t0)));
      } else if (phase === 2 && state() === "notRunning") {
        finish();
      }
    }
    stop = finish;
    root.classList.add("gx-leaving");
    obs.observe(doc.body, {subtree: true, childList: true, attributes: true, attributeFilter: ["data-test-script-state"]});
  }
  on(doc, "click", function (e) {
    var btn = e.target && e.target.closest ? e.target.closest("button") : null;
    if (btn && !btn.disabled && isNav(keyOf(btn))) { leave(); }
  }, true);

  /* 2. Importi: entrando nel campo il valore si seleziona tutto, così si digita subito il nuovo importo (il mouseup che
        segue il primo clic annullerebbe la selezione, quindi per un attimo se ne blocca l'effetto). Dopo un invio il campo
        resta attivo: appena Streamlit ha riscritto il valore formattato lo si riseleziona. Un clic dentro il campo già
        attivo sposta il cursore come sempre, per correggere una cifra. */
  var guard = false;
  function isAmount(el) {
    return !!el && el.tagName === "INPUT" && !!el.closest('[class*="st-key-amt-"], [class*="st-key-gamt-"]');
  }
  function whenIdle(fn) {
    var app = doc.querySelector('[data-testid="stApp"]');
    if (!app || app.getAttribute("data-test-script-state") !== "running") { fn(); return; }
    var obs = new MutationObserver(function () {
      if (app.getAttribute("data-test-script-state") !== "running") { obs.disconnect(); fn(); }
    });
    obs.observe(app, {attributes: true, attributeFilter: ["data-test-script-state"]});
    window.setTimeout(function () { obs.disconnect(); }, 5000);
  }
  on(doc, "focusin", function (e) {
    if (!isAmount(e.target)) { return; }
    try { e.target.select(); } catch (err) { return; }
    guard = true;
    window.setTimeout(function () { guard = false; }, 700);
  });
  on(doc, "mouseup", function (e) {
    if (guard) { guard = false; e.preventDefault(); }
  }, true);
  on(doc, "keydown", function (e) {
    if (e.key !== "Enter" || !isAmount(e.target)) { return; }
    var el = e.target;
    window.setTimeout(function () {
      whenIdle(function () {
        if (doc.activeElement === el) { try { el.select(); } catch (err) { return; } }
      });
    }, 150);
  }, true);

  /* 3. Obiettivi. Il cursore sceglie un anno di calendario e il fumetto sopra il cursore mostra proprio quello (è
        l'etichetta del cursore, che Streamlit aggiorna mentre si trascina); qui si aggiungono la didascalia «tra 36 anni»
        e, nell'intestazione della scheda, la stessa frase che il server scrive dopo il rilascio, così durante il
        trascinamento è già giusta. I testi (lingua e plurali compresi) arrivano dal server nel segnaposto
        data-gx-live (goals.live_texts). Vicino ai bordi il fumetto si sposta (data-edge): sui telefoni non esce dallo schermo. */
  var queued = false, liveRaw = null, live = null;
  function mark(el, name, value) {
    if (value) {
      if (el.getAttribute(name) !== value) { el.setAttribute(name, value); }
    } else if (el.hasAttribute(name)) {
      el.removeAttribute(name);
    }
  }
  function readLive() {
    var el = doc.querySelector("[data-gx-live]");
    var raw = el ? el.getAttribute("data-gx-live") : "";
    if (raw !== liveRaw) {
      liveRaw = raw;
      try { live = raw ? JSON.parse(raw) : null; } catch (err) { live = null; }
    }
    return live;
  }
  function headline(card, data, years) {
    var sub = card.querySelector(".gx-goal-sub");
    if (!sub) { return; }
    var n = [], text = "";
    for (var i = 0; years.length > i; i++) { n.push(years[i] - data.base); }
    if (n.length === 1 && n[0] > 0 && data.one[n[0] - 1]) {
      text = data.one[n[0] - 1];
    } else if (n.length === 2 && n[0] > 0 && n[1] >= n[0] && data.count[n[1] - n[0]]) {
      text = data.span.replace("{start}", n[0]).replace("{end}", n[1]).replace("{count}", data.count[n[1] - n[0]])
        .replace("{y0}", years[0]).replace("{y1}", years[1]) + " · " + data.every;
    }
    if (text && sub.textContent !== text) { sub.textContent = text; }
  }
  function stamp() {
    queued = false;
    var data = readLive();
    var base = data ? data.base : (parseInt(root.getAttribute("data-gx-year"), 10) || new Date().getFullYear());
    var cards = doc.querySelectorAll('[class*="st-key-goal-"]');
    for (var c = 0; cards.length > c; c++) {
      var labels = cards[c].querySelectorAll('[data-testid="stSliderThumbValue"]'), years = [];
      for (var i = 0; labels.length > i; i++) {
        var year = parseInt(labels[i].textContent, 10), n = year - base;
        years.push(year);
        mark(labels[i], "data-cap", data && n > 0 && data.cap[n - 1] ? data.cap[n - 1] : "");
        var at = labels[i].parentElement ? parseFloat(labels[i].parentElement.style.left) : NaN;
        mark(labels[i], "data-edge", at !== at ? "" : (16 > at ? "start" : (at > 84 ? "end" : "")));
      }
      if (data && labels.length) { headline(cards[c], data, years); }
    }
  }
  function queue() {
    if (!queued) { queued = true; window.requestAnimationFrame(stamp); }
  }
  watch(doc.body, {subtree: true, childList: true, characterData: true}, queue);
  queue();
})();
