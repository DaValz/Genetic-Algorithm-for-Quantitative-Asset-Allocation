"""Smoke test end-to-end dell'interfaccia (Playwright + Chromium).

Avvia l'app in locale (oppure usa --url) e percorre il flusso come un utente: home con contatori animati, punto di
partenza, obiettivi, scelta del rischio, riepilogo con il pulsante delle impostazioni avanzate, area avanzata guidata in cinque
passi (con «torna alle scelte automatiche»), evoluzione dell'algoritmo senza salto né replay, piano, composizione nel
tempo, nuovo avvio con seed diverso, registrazione e salvataggio di un portafoglio, cambio lingua.
Richiede:

    pip install -r requirements-dev.txt
    playwright install chromium
    python scripts/e2e_smoke.py [--url http://localhost:8501] [--lang it] [--screenshots cartella] [--mobile] [--headed]

I prezzi vengono dall'archivio mensile ``data/prices_monthly.parquet`` (vedi scripts/update_prices.py): nessun accesso
alla rete durante il test.
Codice di uscita: 0 = tutti i controlli superati, 1 = almeno un controllo fallito, 2 = Playwright non installato.
"""
from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = {"en": "en-US", "it": "it-IT", "es": "es-ES", "fr": "fr-FR", "ru": "ru-RU", "zh": "zh-CN"}
LANG_NAMES = {"en": "English", "it": "Italiano", "es": "Español", "fr": "Français", "ru": "Русский", "zh": "中文"}
LOGIN_LABELS = {"en": "Sign in or sign up", "it": "Accedi o registrati", "es": "Accede o regístrate",
                "fr": "Connexion ou inscription", "ru": "Вход или регистрация", "zh": "登录或注册"}

# fumetto dello slider: un cursore degli obiettivi (primo), il suo fumetto e l'intestazione della scheda
_BUBBLE = """() => {
    const thumb = document.querySelector("[class*='st-key-goal-'] [data-testid='stSlider'] div[data-rac][style*='absolute']");
    const v = thumb.querySelector('[data-testid=stSliderThumbValue]');
    const r = v.getBoundingClientRect(), cs = getComputedStyle(v), sub = document.querySelector('.gx-goal-sub');
    return {opacity: Number(cs.opacity), height: r.height, width: r.width, text: v.textContent.trim(), cap: v.getAttribute('data-cap') || '',
            header: sub ? sub.textContent.trim() : '', dragging: thumb.getAttribute('data-dragging') === 'true',
            state: document.querySelector('[data-testid=stApp]').getAttribute('data-test-script-state'),
            inside: r.left >= -1 && r.right <= window.innerWidth + 1};
}"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int, db_path: str) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true",
           "--server.port", str(port), "--server.address", "127.0.0.1", "--browser.gatherUsageStats", "false"]
    env = {**os.environ, "GOALGA_DB_PATH": db_path, "PYTHONIOENCODING": "utf-8"}
    env.pop("GOALGA_DATABASE_URL", None)
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 90
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("Streamlit terminato durante l'avvio")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as r:
                if r.status == 200:
                    return proc
        except OSError:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("Streamlit non risponde")


class Report:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool]] = []

    def check(self, name: str, cond: object, extra: object = "") -> None:
        self.results.append((name, bool(cond)))
        detail = str(extra).encode("ascii", "replace").decode()
        print("PASS" if cond else "FAIL", "-", name, detail, flush=True)


_OVERLAP = """() => {
    const boxes = (r, sel) => { const e = r.querySelector(sel); const b = e.getBoundingClientRect();
        return {l: b.left, r: b.right, t: b.top, b: b.bottom}; };
    const hit = (a, b) => a.l < b.r - 0.5 && a.r > b.l + 0.5 && a.t < b.b - 0.5 && a.b > b.t + 0.5;
    return [...document.querySelectorAll('.gx-cmp .row')].map(row => {
        const lbl = boxes(row, '.lbl'), bar = boxes(row, '.bar'), val = boxes(row, '.val');
        return hit(lbl, bar) || hit(lbl, val) || hit(bar, val);
    });
}"""


def scenario(browser, url: str, shots: Path | None, mobile: bool, lang: str, report: Report) -> None:
    check = report.check
    size = {"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900}
    ctx = browser.new_context(viewport=size, locale=LOCALES[lang], has_touch=mobile, is_mobile=mobile)
    pg = ctx.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
    pg.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
    tag = f"{'mobile' if mobile else 'desktop'}_{lang}"
    counter = [0]

    def snap(name: str, full: bool = False) -> None:
        if shots is None:
            return
        shots.mkdir(parents=True, exist_ok=True)
        counter[0] += 1
        path = shots / f"{tag}_{counter[0]:02d}_{name}.png"
        if full:      # Streamlit scorre un contenitore interno: si ingrandisce la finestra fino all'altezza del contenuto
            height = pg.evaluate("() => document.querySelector('[data-testid=\"stMain\"]').scrollHeight")
            pg.set_viewport_size({"width": size["width"], "height": int(min(max(height + 40, size["height"]), 7000))})
            pg.wait_for_timeout(500)
            pg.screenshot(path=str(path))
            pg.set_viewport_size(size)
            pg.wait_for_timeout(300)
        else:
            pg.screenshot(path=str(path))

    def settle(ms: int = 600) -> None:
        """Attende che Streamlit abbia terminato l'esecuzione dello script (e un breve tempo per le animazioni)."""
        pg.wait_for_timeout(300)
        pg.wait_for_function("document.querySelector('[data-testid=\"stApp\"]').getAttribute('data-test-script-state') === 'notRunning'",
                             timeout=240_000)
        pg.wait_for_timeout(ms)

    def key(name: str, tail: str = "button"):
        return pg.locator(f".st-key-{name} {tail}".strip())

    def no_overflow() -> bool:
        return pg.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1 && "
                           "document.querySelector('[data-testid=\"stMain\"]').scrollWidth <= window.innerWidth + 1")

    def digits(text: str) -> str:
        return re.sub(r"\D", "", text)

    # 1. home ---------------------------------------------------------------------------------------------
    pg.goto(f"{url}/?lang={lang}")
    pg.wait_for_selector(".gx-head", timeout=90_000)
    pg.wait_for_timeout(150)
    start_values = pg.eval_on_selector_all(".gx-count", "els => els.map(e => e.textContent)")
    settle(2600)
    final_values = pg.eval_on_selector_all(".gx-count", "els => els.map(e => e.textContent)")
    check("home: tre contatori che salgono fino ai valori finali (+)",
          [digits(v) for v in final_values] == ["1000", "100", "3400"] and start_values != final_values,
          f"{start_values} -> {final_values}")
    check("home: ogni numero è seguito da «+»", pg.locator(".gx-feat b").evaluate_all(
        "els => els.every(e => e.textContent.trim().endsWith('+'))"))
    check("home: nessuna sezione di esempi", pg.locator(".st-key-example_pick").count() == 0 and
          "example" not in pg.inner_text("body").lower() and "esempio" not in pg.inner_text("body").lower())
    check("home: nessuna barra laterale", pg.locator('[data-testid="stSidebar"]').count() == 0
          or not pg.locator('[data-testid="stSidebar"]').first.is_visible())
    check("home: sfondo animato dell'algoritmo", pg.locator(".st-key-bg iframe").count() == 1)
    check("home: lingua e account in alto a destra", pg.locator(".st-key-lang_pick").count() == 1
          and pg.locator(".st-key-acct-btn").count() == 1)
    check("home: il pulsante di accesso invita anche a registrarsi",
          LOGIN_LABELS[lang] in (pg.locator(".st-key-acct-btn button").first.text_content() or ""),
          pg.locator(".st-key-acct-btn button").first.text_content())
    check("home: nessun overflow orizzontale", no_overflow())
    snap("1_home")

    # cambio lingua dal selettore -------------------------------------------------------------------------
    other = "en" if lang != "en" else "it"
    before = key("cta-home-btn").inner_text()
    pg.locator(".st-key-lang_pick").get_by_role("combobox").click()
    options = pg.get_by_role("option")
    check("lingua: sei lingue disponibili", options.count() == 6, options.all_inner_texts())
    options.filter(has_text=LANG_NAMES[other]).first.click()
    settle(800)
    check("lingua: il cambio traduce la pagina", key("cta-home-btn").inner_text() != before
          and pg.evaluate("document.documentElement.lang") == other, pg.evaluate("document.documentElement.lang"))
    pg.locator(".st-key-lang_pick").get_by_role("combobox").click()
    pg.get_by_role("option").filter(has_text=LANG_NAMES[lang]).first.click()
    settle(800)

    # 2. punto di partenza --------------------------------------------------------------------------------------
    key("cta-home-btn").click()
    pg.wait_for_selector(".st-key-amt-w0", timeout=30_000)
    settle()
    check("importo: si parte da un piano vuoto e non si può continuare", key("cta-btn").is_disabled())
    cap = pg.locator(".st-key-amt-w0 input")
    cap.fill("20k")
    cap.press("Enter")
    settle(1200)
    check("importo: «20k» diventa 20.000 nel formato della lingua", digits(cap.input_value()) == "20000", cap.input_value())
    cap.fill("2M")
    cap.press("Enter")
    settle(1200)
    check("importo: «2M» diventa 2.000.000", digits(cap.input_value()) == "2000000", cap.input_value())
    cap.press("End")                                                    # uno zero aggiunto in coda al testo già formattato
    cap.press_sequentially("0")
    cap.press("Enter")
    settle(1200)
    check("importo: uno zero in coda a 2.000.000 dà 20.000.000 (non più 2.000)", digits(cap.input_value()) == "20000000",
          cap.input_value())
    pg.wait_for_timeout(300)
    check("importo: dopo l'invio il valore è selezionato, il numero successivo lo sostituisce",
          cap.evaluate("e => e.selectionStart === 0 && e.selectionEnd === e.value.length && document.activeElement === e"))
    cap.fill("20k")
    cap.press("Enter")
    settle(1200)
    check("importo: si torna a 20.000", digits(cap.input_value()) == "20000", cap.input_value())
    pg.locator(".st-key-chip-contribution button").nth(4).click()       # 12 k€ (0 · 1,2 k · 3 k · 6 k · 12 k · 24 k)
    settle(1200)
    check("importo: scorciatoia versamento 12 k€", digits(pg.locator(".st-key-amt-contribution input").input_value()) == "12000")
    snap("2_start")

    # 3. obiettivi ---------------------------------------------------------------------------------------------------
    key("cta-btn").click()
    pg.wait_for_selector(".st-key-add_goal", timeout=30_000)
    settle(900)
    check("obiettivi: si parte senza obiettivi e non si può continuare", pg.locator("[class*='st-key-goal-']").count() == 0
          and key("cta-btn").is_disabled())
    pg.locator(".st-key-add_goal button").nth(0).click()
    settle(1200)
    pg.locator(".st-key-add_goal button").nth(2).click()
    settle(1200)
    check("obiettivi: aggiunta di due obiettivi", pg.locator("[class*='st-key-goal-']").count() == 2)
    check("obiettivi: la linea del tempo mostra un indicatore per obiettivo", pg.locator(".gx-tl-pin").count() == 2)
    check("obiettivi: un cursore solo per ogni obiettivo di un anno",
          pg.locator("[class*='st-key-goal-'] [data-testid='stSlider'] div[data-rac][style*='absolute']").count() == 2)
    check("obiettivi: a riposo i fumetti sono nascosti", pg.evaluate(_BUBBLE)["opacity"] == 0)
    year = date.today().year
    ticks = pg.locator("[class*='st-key-goal-'] [data-testid='stSliderTickBar']").first.inner_text()
    check("obiettivi: gli estremi dello slider sono anni di calendario", str(year + 1) in ticks and str(year + 60) in ticks, ticks)
    thumb = pg.locator("[class*='st-key-goal-'] [data-testid='stSlider'] div[data-rac][style*='absolute']").first
    pg.locator("[class*='st-key-goal-']").first.scroll_into_view_if_needed()
    box = thumb.bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    before_text = pg.evaluate(_BUBBLE)["text"]
    pg.mouse.move(cx, cy)
    pg.mouse.down()
    for i in range(1, 31):                                                  # come una mano vera: tanti piccoli spostamenti
        pg.mouse.move(cx + i * 2, cy)
        pg.wait_for_timeout(12)
    pg.wait_for_timeout(300)
    bubble = pg.evaluate(_BUBBLE)
    check("obiettivi: trascinando il fumetto grande mostra l'anno scelto e «tra N anni»",
          bubble["dragging"] and bubble["opacity"] == 1 and bubble["height"] >= 70 and re.fullmatch(r"20\d\d", bubble["text"])
          and year < int(bubble["text"]) <= year + 60 and bubble["text"] != before_text and bubble["cap"]
          and str(int(bubble["text"]) - year) in bubble["cap"] and bubble["inside"], bubble)
    check("obiettivi: durante il trascinamento (senza ricalcoli) anche l'intestazione dice già quell'anno",
          bubble["state"] == "notRunning" and bubble["text"] in bubble["header"]
          and re.search(r"\d+", bubble["cap"]).group() in bubble["header"], bubble)
    snap("3b_goal_bubble")
    pg.mouse.up()
    settle(900)
    pg.mouse.move(2, 2)
    pg.wait_for_timeout(500)
    after = pg.evaluate(_BUBBLE)
    check("obiettivi: a cursore rilasciato il fumetto sparisce", after["opacity"] == 0)
    check("obiettivi: dopo il rilascio il server scrive la stessa intestazione già vista durante il trascinamento",
          after["header"] == bubble["header"], f"{bubble['header']!r} / {after['header']!r}")
    pg.locator("[class*='st-key-gm_'] label").first.click()                 # «Si ripete ogni anno»
    settle(1200)
    check("obiettivi: «ogni anno» mostra le due estremità e l'obiettivo si estende su più anni",
          pg.locator("[class*='st-key-goal-'] [data-testid='stSlider'] div[data-rac][style*='absolute']").count() == 3
          and pg.locator(".gx-tl-span").count() == 1)
    pg.locator("[class*='st-key-gm_'] label").first.click()
    settle(1200)
    check("obiettivi: spegnendolo si torna a un cursore solo",
          pg.locator("[class*='st-key-goal-'] [data-testid='stSlider'] div[data-rac][style*='absolute']").count() == 2
          and pg.locator(".gx-tl-span").count() == 0)
    goal_amount = pg.locator("[class*='st-key-gamt-'] input").first
    goal_amount.fill("1M")
    goal_amount.press("Enter")
    settle(1200)
    check("obiettivi: il milione si scrive anche nell'importo di un obiettivo", digits(goal_amount.input_value()) == "1000000",
          goal_amount.input_value())
    goal_amount.press("End")
    goal_amount.press_sequentially("0")
    goal_amount.press("Enter")
    settle(1200)
    check("obiettivi: uno zero in coda dà 10 milioni", digits(goal_amount.input_value()) == "10000000", goal_amount.input_value())
    goal_amount.fill("quasi mezzo")
    goal_amount.press("Enter")
    settle(1200)
    check("obiettivi: un testo illeggibile non cambia l'importo e avvisa", digits(goal_amount.input_value()) == "10000000"
          and pg.locator(".gx-note[style*='warn']").count() == 1)
    goal_amount.fill("40k")
    goal_amount.press("Enter")
    settle(1200)
    check("obiettivi: l'importo torna valido e l'avviso sparisce", digits(goal_amount.input_value()) == "40000"
          and pg.locator(".gx-note[style*='warn']").count() == 0)
    snap("3_goals", full=True)
    pg.locator("[class*='st-key-rm-']").last.click()
    settle(1500)
    check("obiettivi: rimozione", pg.locator("[class*='st-key-goal-']").count() == 1)
    pg.locator(".st-key-add_goal button").nth(2).click()
    settle(1200)

    # 4. rischio --------------------------------------------------------------------------------------------------------
    key("cta-btn").click()
    pg.wait_for_selector(".st-key-rk-btn-balanced", timeout=240_000)
    settle(1500)
    check("rischio: tre profili con probabilità di riuscita", pg.locator(".gx-risk").count() == 3
          and pg.locator(".gx-risk .n").count() == 3)
    check("rischio: è evidenziato un solo profilo", pg.locator(".gx-risk.sel").count() == 1)
    check("rischio: il profilo scelto resta leggibile (non disabilitato)", not key("rk-btn-balanced").is_disabled())
    check("rischio: nessun overflow orizzontale", no_overflow())
    snap("4_risk", full=True)
    key("rk-btn-cautious").click()
    settle(1200)
    check("rischio: la scelta si sposta sul profilo prudente",
          pg.locator(".gx-risk.sel").first.get_attribute("data-profile") == "cautious")

    # 5. riepilogo --------------------------------------------------------------------------------------------------------
    key("cta-btn").click()
    pg.wait_for_selector(".st-key-card-auto", timeout=60_000)
    settle(1200)
    check("riepilogo: nessun interruttore né link piccolo, solo il pulsante delle impostazioni avanzate",
          pg.locator('[data-testid="stToggle"]').count() == 0 and pg.locator(".st-key-to-lab-link").count() == 0
          and pg.locator(".st-key-to-lab").count() == 1 and pg.locator(".st-key-review-reset").count() == 0)
    primary, advanced = pg.locator(".st-key-cta-btn button").bounding_box(), pg.locator(".st-key-to-lab button").bounding_box()
    check("riepilogo: il pulsante delle impostazioni avanzate è grande quanto quello principale",
          abs(primary["width"] - advanced["width"]) < 2 and abs(primary["height"] - advanced["height"]) < 2
          and advanced["height"] >= 48 and advanced["y"] > primary["y"], f"{primary} / {advanced}")
    check("riepilogo: difficoltà del piano", pg.locator(".gx-gauge").count() == 1)
    snap("5_review", full=True)

    # 5c. area avanzata guidata -----------------------------------------------------------------------------------------
    key("to-lab").click()
    pg.wait_for_selector(".gx-guide", timeout=60_000)
    settle(2500)
    stepper = pg.locator(".st-key-lab_section button")
    body = pg.inner_text("body").lower()
    check("lab: sei sezioni (cinque passi guidati più il metodo)", stepper.count() == 6, stepper.all_inner_texts())
    check("lab: il primo passo si apre con la sua spiegazione", pg.locator(".gx-guide .no").first.inner_text().strip() == "1")
    check("lab: l'imbuto mostra asset valutati, idonei e usati", pg.locator(".gx-funnel > div").count() == 3,
          pg.locator(".gx-funnel").all_inner_texts())
    check("lab: categorie selezionabili (9 di fondi, 11 di settori)",
          pg.locator(".st-key-cats_funds button").count() == 9 and pg.locator(".st-key-cats_sectors button").count() == 11)
    check("lab: nessun caricamento di file né dati sintetici né fornitore dei dati",
          pg.locator("input[type=file]").count() == 0 and not any(w in body for w in ("yahoo", "csv", "excel", "synthetic", "sintetic")))
    check("lab: l'esplorazione per categoria elenca gli asset", pg.locator(".st-key-browse_cat").count() == 1)
    snap("5c_lab_universe", full=True)
    for step in range(2, 6):
        key("lab-next").click()
        settle(2500)
        check(f"lab: passo {step} con la sua spiegazione", pg.locator(".gx-guide .no").first.inner_text().strip() == str(step))
        if step == 3:
            check("lab: frontiera e composizione per categoria", pg.locator(".js-plotly-plot").count() == 2)
        if step == 4:
            check("lab: impegno della ricerca con tre livelli", pg.locator(".st-key-effort button").count() == 3)
        snap(f"5d_lab_step{step}")
    stepper.nth(0).click()
    settle(1800)
    pg.locator(".st-key-cats_sectors-none button").click()
    settle(1500)
    check("lab: una modifica compare nel riepilogo dei cambiamenti", pg.locator(".gx-changes .gx-badge").count() == 1)
    check("lab: nessun overflow orizzontale", no_overflow())
    key("back-lab").click()                                              # «Indietro» tiene le modifiche
    pg.wait_for_selector(".st-key-card-auto", timeout=60_000)
    settle(1200)
    check("riepilogo: con modifiche la scheda dice quali e compare «torna alle scelte automatiche»",
          pg.locator(".st-key-card-auto .gx-badge").count() == 1 and pg.locator(".st-key-review-reset").count() == 1)
    snap("5b_review_custom")
    key("to-lab").click()                                                # di nuovo nell'area avanzata
    pg.wait_for_selector(".gx-guide", timeout=60_000)
    settle(1500)
    pg.evaluate("""() => { window.__gx_seen = []; const root = document.documentElement;
        new MutationObserver(() => { const s = (root.classList.contains('gx-leaving') ? 'L' : '') + (root.classList.contains('gx-swapped') ? 'S' : '');
            if (s && window.__gx_seen[window.__gx_seen.length - 1] !== s) window.__gx_seen.push(s); })
            .observe(root, {attributes: true, attributeFilter: ['class']}); }""")
    t_reset = time.time()
    key("lab-reset").click()                                             # azzera e riporta alla conferma
    pg.wait_for_selector(".st-key-card-auto", timeout=60_000)
    took = time.time() - t_reset
    settle(1500)
    check("lab: «torna alle scelte automatiche» azzera le modifiche e riporta alla conferma del piano",
          pg.locator(".gx-guide").count() == 0 and pg.locator(".st-key-card-auto .gx-badge").count() == 0
          and pg.locator(".st-key-review-reset").count() == 0 and pg.locator(".st-key-to-lab").count() == 1)
    seen = pg.evaluate("window.__gx_seen")
    check("lab: il ritorno passa da una dissolvenza e le classi di transizione si chiudono da sole",
          seen[:1] == ["L"] and pg.evaluate("() => !document.documentElement.classList.contains('gx-leaving') && "
                                            "!document.documentElement.classList.contains('gx-swapped')"), seen)
    check("lab: il ritorno è rapido (il mercato automatico è già in memoria)", took < 2.5, f"{took:.2f} s")
    check("riepilogo: nessun overflow orizzontale", no_overflow())

    # 6. evoluzione --------------------------------------------------------------------------------------------------------
    key("cta-btn").click()
    pg.wait_for_selector(".st-key-stage", timeout=240_000)
    pg.wait_for_timeout(2500)
    snap("6_evolve")
    pg.wait_for_selector(".st-key-cta-late-btn button", timeout=120_000)
    buttons = pg.locator(".stButton").evaluate_all(
        "els => els.map(e => (e.parentElement.className.match(/st-key-[^ ]+/) || [''])[0])")
    check("evoluzione: nessun pulsante per saltare o rivedere", set(buttons) <= {"st-key-acct-btn", "st-key-cta-late-btn"}
          and "st-key-cta-late-btn" in buttons, buttons)
    pg.wait_for_timeout(9000)
    snap("6b_evolve_done")
    check("evoluzione: nessun overflow orizzontale", no_overflow())

    # 7. piano --------------------------------------------------------------------------------------------------------------
    key("cta-late-btn").click()
    pg.wait_for_selector(".st-key-to-holdings", timeout=60_000)
    settle(2500)
    check("piano: esito in «su 100» con anello", pg.locator(".gx-ring").count() == 1)
    check("piano: profilo e soglia nei badge", pg.locator(".gx-hero .gx-badge").count() >= 2)
    check("piano: nessun pulsante «rivedi l'evoluzione»", pg.locator(".st-key-plan-replay").count() == 0)
    rows = pg.locator(".gx-cmp .row").count()
    check("piano: confronto con le alternative", rows >= 4, rows)
    overlaps = pg.evaluate(_OVERLAP)
    check("piano: nel confronto etichette, barre e valori non si sovrappongono", rows > 0 and not any(overlaps), overlaps)
    check("piano: collegamento ben visibile alla composizione nel tempo", pg.locator(".st-key-card-holdings").count() == 1
          and key("to-holdings").is_visible())
    check("piano: stime degli altri profili", pg.locator("[class*='st-key-wi-btn-']").count() == 3)
    check("piano: nessun overflow orizzontale", no_overflow())
    snap("7_plan", full=True)

    # 8. composizione nel tempo ---------------------------------------------------------------------------------------------
    key("to-holdings").click()
    pg.wait_for_selector(".gx-hold", timeout=60_000)
    settle(2500)
    n_first = pg.locator(".gx-hrow").count()
    check("composizione: ciambella, elenco degli asset e tabella anno per anno",
          pg.locator(".gx-donut").count() == 1 and n_first >= 1 and pg.locator(".gx-heat tbody tr").count() >= 2, n_first)
    check("composizione: ogni asset ha nome e ticker", pg.locator(".gx-hrow .nm span").first.inner_text().strip() != "")
    heading = pg.locator(".gx-sec h3").first.inner_text()
    thumb = pg.locator("[class*='st-key-hold_year_'] input[type='range'], [class*='st-key-hold_year_'] [role='slider']").first
    thumb.focus()
    pg.keyboard.press("End")
    settle(1500)
    check("composizione: scegliendo l'ultimo anno cambia il portafoglio mostrato",
          pg.locator(".gx-sec h3").first.inner_text() != heading and pg.locator(".gx-hrow").count() >= 1,
          f"{heading!r} -> {pg.locator('.gx-sec h3').first.inner_text()!r}")
    check("composizione: nessun overflow orizzontale", no_overflow())
    snap("8_holdings", full=True)
    key("back-holdings").click()
    pg.wait_for_selector(".st-key-save-guest", timeout=60_000)
    settle(1200)

    # 8b. ogni avvio usa un seed nuovo ------------------------------------------------------------------------------------
    def last_seed() -> str:
        """Seed dell'ultima ricerca, letto nell'area avanzata (poi si torna al piano senza lasciare modifiche)."""
        key("plan-lab").click()
        pg.wait_for_selector(".gx-guide", timeout=60_000)
        settle(1200)
        pg.locator(".st-key-lab_section button").nth(3).click()
        settle(1800)
        numbers = [n for text in pg.locator(".gx-note").all_inner_texts() for n in re.findall(r"\d{6,}", text)]
        key("lab-reset").click()                                       # azzera ed esce: si torna al piano
        pg.wait_for_selector(".st-key-to-holdings", timeout=60_000)
        settle(1200)
        return max(numbers, key=len, default="")

    seed_a = last_seed()
    key("plan-edit").click()
    pg.wait_for_selector(".st-key-amt-w0", timeout=60_000)
    settle(900)
    for _ in range(2):                                                    # punto di partenza -> obiettivi -> rischio
        key("cta-btn").click()
        settle(1500)
    pg.wait_for_selector(".st-key-rk-btn-balanced", timeout=240_000)
    settle(1500)
    key("cta-btn").click()                                                # rischio -> riepilogo
    pg.wait_for_selector(".st-key-card-auto", timeout=60_000)
    settle(1200)
    key("cta-btn").click()                                                # stessi obiettivi, stesso profilo: nuovo avvio
    pg.wait_for_selector(".st-key-cta-late-btn button", timeout=240_000)
    pg.wait_for_timeout(9000)
    key("cta-late-btn").click()
    pg.wait_for_selector(".st-key-to-holdings", timeout=60_000)
    settle(2000)
    seed_b = last_seed()
    check("nuovo avvio: stessi obiettivi e stesso profilo ma seed diverso, quindi si ricalcola",
          bool(seed_a) and bool(seed_b) and seed_a != seed_b, f"{seed_a} -> {seed_b}")
    check("nuovo avvio: l'esito è di nuovo un piano completo", pg.locator(".gx-ring").count() == 1)

    # 9. account ---------------------------------------------------------------------------------------------------------------
    key("save-guest").click()
    pg.wait_for_selector(".st-key-card-signin", timeout=60_000)
    settle(1000)
    check("account: accesso e registrazione, nessun overflow", pg.locator('[role="tab"]').count() == 2 and no_overflow())
    snap("9_account_guest")
    pg.locator('[role="tab"]').nth(1).click()
    pg.wait_for_selector(".st-key-su_name input", timeout=30_000)
    settle(600)
    email = f"e2e.{tag}.{int(time.time())}@example.com"
    pg.locator(".st-key-su_name input").fill("Mario Rossi")
    pg.locator(".st-key-su_email input").fill(email)
    pg.locator(".st-key-su_password input").fill("Sup3rSecret!")
    pg.locator(".st-key-su_password2 input").fill("Sup3rSecret!")
    pg.locator(".st-key-su_password2 input").press("Tab")
    settle(600)
    key("su_submit").click()
    pg.wait_for_selector(".st-key-save-new", timeout=60_000)
    settle(1500)
    check("account: dopo la registrazione si torna al piano con il nome in alto",
          "Mario" in (pg.locator(".st-key-acct-btn").first.text_content() or ""))
    key("save-new").click()
    pg.wait_for_selector(".st-key-save-version", timeout=60_000)
    settle(1500)
    check("account: il portafoglio è salvato (si può salvare una nuova versione)", key("save-version").is_visible())
    pg.locator(".st-key-acct-btn button:visible").first.click()
    pg.wait_for_selector(".st-key-signout", timeout=60_000)
    settle(2500)
    check("account: spazio personale con il portafoglio seguito", pg.locator("[class*='st-key-pfcard-']").count() == 1
          and pg.locator("[class*='st-key-pf-comp-']").count() == 1)
    check("account: nessun overflow orizzontale", no_overflow())
    snap("10_space", full=True)
    pg.locator("[class*='st-key-pf-comp-'] button").first.click()
    pg.wait_for_selector(".gx-hold", timeout=60_000)
    settle(1500)
    check("account: la composizione del portafoglio salvato si apre", pg.locator(".gx-hrow").count() >= 1)
    key("back-holdings").click()
    pg.wait_for_selector(".st-key-signout", timeout=60_000)
    key("signout").click()
    pg.wait_for_selector(".st-key-cta-home-btn", timeout=60_000)
    settle(800)
    check("account: l'uscita riporta alla home", pg.locator(".st-key-cta-home-btn").count() == 1)

    check("nessun errore JavaScript o di rete", not [e for e in errors if "favicon" not in e], errors[:3])
    ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke test end-to-end dell'interfaccia (Playwright).")
    ap.add_argument("--url", help="URL di un'app già in esecuzione (altrimenti ne avvia una locale)")
    ap.add_argument("--lang", default="it", choices=sorted(LOCALES), help="lingua dell'interfaccia (predefinita: it)")
    ap.add_argument("--screenshots", type=Path, help="cartella in cui salvare gli screenshot")
    ap.add_argument("--mobile", action="store_true", help="simula uno smartphone (390x844)")
    ap.add_argument("--headed", action="store_true", help="mostra il browser")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright non installato: pip install -r requirements-dev.txt && playwright install chromium")
        return 2

    server = None
    url = args.url
    tmp = tempfile.TemporaryDirectory()
    if url is None:
        port = free_port()
        server = start_server(port, str(Path(tmp.name) / "e2e.db"))
        url = f"http://127.0.0.1:{port}"

    report = Report()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not args.headed)
            try:
                scenario(browser, url, args.screenshots, args.mobile, args.lang, report)
            except Exception as exc:        # un passo che non si completa è un controllo fallito, non un crash muto
                report.check("il percorso arriva fino in fondo", False, f"{type(exc).__name__}: {str(exc)[:300]}")
            finally:
                browser.close()
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        try:
            tmp.cleanup()
        except OSError:
            pass

    passed = sum(ok for _, ok in report.results)
    print(f"\n{passed}/{len(report.results)} controlli superati")
    return 0 if report.results and passed == len(report.results) else 1


if __name__ == "__main__":
    sys.exit(main())
