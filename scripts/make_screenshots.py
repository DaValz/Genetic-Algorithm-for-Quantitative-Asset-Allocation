"""Rigenera le immagini del README (docs/images): schermate in inglese, GIF dell'evoluzione e composizione mobile.

    pip install -r requirements-dev.txt
    playwright install chromium
    python scripts/make_screenshots.py [--url http://localhost:8501] [--out docs/images]

Avvia un'app locale con un database temporaneo (oppure usa --url, ma serve allora un'app con archivio SQLite
accessibile: senza ``--db`` l'avviso di esempio non viene creato). Percorre il flusso come un utente, salva un
portafoglio e ne modifica il piano per ottenere un vero avviso sui pesi da mostrare nello spazio personale.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_smoke import free_port, start_server  # noqa: E402

BG = (5, 6, 11)
PASSWORD = "Sup3rSecret!"


def main() -> int:
    ap = argparse.ArgumentParser(description="Rigenera le immagini del README.")
    ap.add_argument("--url", help="URL di un'app già in esecuzione (altrimenti ne avvia una locale)")
    ap.add_argument("--db", help="file SQLite usato dall'app indicata con --url (per creare l'avviso di esempio)")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "images")
    args = ap.parse_args()
    try:
        from PIL import Image
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Servono Pillow e Playwright: pip install -r requirements-dev.txt && playwright install chromium")
        return 2

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.TemporaryDirectory()
    db_path = args.db or str(Path(tmp.name) / "shots.db")
    server, url = None, args.url
    if url is None:
        port = free_port()
        server = start_server(port, db_path)
        url = f"http://127.0.0.1:{port}"
    os.environ["GOALGA_DB_PATH"] = db_path

    def settle(pg, ms: int = 700) -> None:
        pg.wait_for_timeout(300)
        pg.wait_for_function("document.querySelector('[data-testid=\"stApp\"]').getAttribute('data-test-script-state') === 'notRunning'",
                             timeout=240_000)
        pg.wait_for_timeout(ms)

    def shot(pg, name: str, height: int | None = None, full: bool = False) -> Path:
        path = out / name
        if full:
            h = pg.evaluate("() => document.querySelector('[data-testid=\"stMain\"]').scrollHeight")
            size = pg.viewport_size
            pg.set_viewport_size({"width": size["width"], "height": int(min(max(h + 30, height or 0), 6000))})
            pg.wait_for_timeout(500)
            pg.screenshot(path=str(path))
            pg.set_viewport_size(size)
        else:
            pg.screenshot(path=str(path))
        return path

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1000, "height": 760}, locale="en-GB", device_scale_factor=1)
            pg = ctx.new_page()

            # hero (finestra larga) -----------------------------------------------------------------------------
            pg.set_viewport_size({"width": 1440, "height": 820})
            pg.goto(f"{url}/?lang=en")
            pg.wait_for_selector(".gx-feat", timeout=90_000)
            settle(pg, 3200)
            shot(pg, "hero.png")
            pg.set_viewport_size({"width": 1000, "height": 760})

            # percorso -------------------------------------------------------------------------------------------
            pg.locator(".st-key-cta-home-btn button").click()
            pg.wait_for_selector(".st-key-amt-w0", timeout=30_000)
            settle(pg)
            for field, value in (("w0", "50000"), ("contribution", "6000")):
                box = pg.locator(f".st-key-amt-{field} input")
                box.fill(value)
                box.press("Enter")
                settle(pg, 900)
            pg.locator(".st-key-cta-btn button").click()
            pg.wait_for_selector(".st-key-add_goal", timeout=30_000)
            settle(pg)
            pg.locator(".st-key-add_goal button").nth(0).click()
            settle(pg, 1200)
            pg.locator(".st-key-add_goal button").nth(2).click()
            settle(pg, 1500)
            # il fumetto compare mentre si trascina il cursore del primo obiettivo: è ciò che mostra l'immagine
            thumb = pg.locator("[class*='st-key-goal-'] [data-testid='stSlider'] div[data-rac][style*='absolute']").first
            thumb.scroll_into_view_if_needed()
            tb = thumb.bounding_box()
            cx, cy = tb["x"] + tb["width"] / 2, tb["y"] + tb["height"] / 2
            pg.mouse.move(cx, cy)
            pg.mouse.down()
            pg.mouse.move(cx + 70, cy, steps=8)
            pg.wait_for_timeout(600)
            shot(pg, "goals.png", full=True, height=760)
            pg.mouse.up()
            settle(pg, 900)
            pg.mouse.move(2, 2)

            pg.locator(".st-key-cta-btn button").click()
            pg.wait_for_selector(".st-key-rk-btn-balanced", timeout=240_000)
            settle(pg, 1800)
            pg.set_viewport_size({"width": 1100, "height": 900})
            shot(pg, "risk.png", full=True, height=760)
            pg.set_viewport_size({"width": 1000, "height": 760})

            pg.locator(".st-key-cta-btn button").click()
            pg.wait_for_selector(".st-key-card-auto", timeout=60_000)
            settle(pg, 1200)
            shot(pg, "review.png", full=True, height=760)

            # configurazione avanzata guidata (passo 1: universo) --------------------------------------------------
            pg.locator(".st-key-to-lab button").click()
            pg.wait_for_selector(".gx-funnel", timeout=60_000)
            settle(pg, 2500)
            pg.set_viewport_size({"width": 1100, "height": 900})
            shot(pg, "lab.png", full=True, height=760)
            pg.set_viewport_size({"width": 1000, "height": 760})
            pg.locator(".st-key-lab-reset button").click()          # «torna alle scelte automatiche»: si torna alla conferma
            pg.wait_for_selector(".st-key-card-auto", timeout=60_000)
            settle(pg, 1200)

            # evoluzione: fotogrammi per la GIF -------------------------------------------------------------------
            pg.locator(".st-key-cta-btn button").click()
            pg.wait_for_selector(".st-key-stage iframe", timeout=240_000)
            stage = pg.locator(".st-key-stage")
            frames: list[Image.Image] = []
            t0 = time.time()
            while time.time() - t0 < 11.5 and len(frames) < 70:
                frames.append(Image.open(io.BytesIO(stage.screenshot())).convert("RGB"))
                pg.wait_for_timeout(110)
            width = 720
            small = [f.resize((width, int(f.height * width / f.width)), Image.LANCZOS) for f in frames]
            pal = [f.quantize(colors=112, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in small]
            pal[0].save(out / "evolution.gif", save_all=True, append_images=pal[1:], duration=150, loop=0, optimize=True)
            pg.wait_for_selector(".st-key-cta-late-btn button", timeout=120_000)
            pg.wait_for_timeout(1500)

            # piano -------------------------------------------------------------------------------------------------
            pg.locator(".st-key-cta-late-btn button").click()
            pg.wait_for_selector(".st-key-to-holdings", timeout=60_000)
            settle(pg, 2500)
            pg.set_viewport_size({"width": 1000, "height": 1250})
            pg.wait_for_timeout(600)
            shot(pg, "plan.png")
            pg.set_viewport_size({"width": 1000, "height": 760})

            # composizione -------------------------------------------------------------------------------------------
            pg.locator(".st-key-to-holdings button").click()
            pg.wait_for_selector(".gx-hold", timeout=60_000)
            settle(pg, 2500)
            pg.set_viewport_size({"width": 1000, "height": 1180})
            pg.wait_for_timeout(600)
            shot(pg, "holdings.png")
            pg.set_viewport_size({"width": 1000, "height": 760})
            pg.locator(".st-key-back-holdings button").click()
            pg.wait_for_selector(".st-key-save-guest", timeout=60_000)

            # account, salvataggio e avviso di esempio -----------------------------------------------------------------
            pg.locator(".st-key-save-guest button").click()
            pg.wait_for_selector(".st-key-card-signin", timeout=60_000)
            settle(pg)
            pg.locator('[role="tab"]').nth(1).click()
            pg.wait_for_selector(".st-key-su_name input", timeout=30_000)
            email = f"maria.{int(time.time())}@example.com"
            pg.locator(".st-key-su_name input").fill("Maria")
            pg.locator(".st-key-su_email input").fill(email)
            pg.locator(".st-key-su_password input").fill(PASSWORD)
            pg.locator(".st-key-su_password2 input").fill(PASSWORD)
            pg.locator(".st-key-su_password2 input").press("Tab")
            settle(pg, 600)
            pg.locator(".st-key-su_submit button").click()
            pg.wait_for_selector(".st-key-save-new", timeout=60_000)
            settle(pg, 1200)
            pg.locator(".st-key-save-new button").click()
            pg.wait_for_selector(".st-key-save-version", timeout=60_000)
            settle(pg, 1200)

            if args.url is None or args.db:           # un vero avviso: il piano viene modificato e i pesi cambiano
                from goalga.accounts import Accounts, Database
                db = Database(f"sqlite:///{Path(db_path).as_posix()}")
                service = Accounts(db)
                me = service.authenticate(email, PASSWORD)
                pf = service.list_portfolios(me.id)[0]
                version = service.current_version(pf.id)
                result = {**version.result, "path": [max(1, int(level) - 1) for level in version.result["path"]]}
                _, alert = service.save_version(me.id, pf.id, version.spec, result)
                db.dispose()
                print("avviso di esempio creato:", bool(alert))
            pg.locator(".st-key-acct-btn button:visible").first.click()
            pg.wait_for_selector(".st-key-signout", timeout=60_000)
            settle(pg, 2500)
            pg.mouse.move(5, 400)                    # niente tooltip residuo del pulsante appena premuto
            pg.wait_for_timeout(400)
            pg.set_viewport_size({"width": 1100, "height": 900})
            shot(pg, "account.png", full=True, height=760)
            ctx.close()

            # mobile: tre schermate affiancate ---------------------------------------------------------------------
            phone = browser.new_context(viewport={"width": 390, "height": 844}, locale="en-GB", has_touch=True,
                                        is_mobile=True, device_scale_factor=2)
            mp = phone.new_page()
            mp.goto(f"{url}/?lang=en")
            mp.wait_for_selector(".gx-feat", timeout=90_000)
            settle(mp, 3200)
            first = mp.screenshot()
            mp.locator(".st-key-cta-home-btn button").click()
            mp.wait_for_selector(".st-key-amt-w0", timeout=30_000)
            settle(mp)
            for field, value in (("w0", "50000"), ("contribution", "6000")):
                box = mp.locator(f".st-key-amt-{field} input")
                box.fill(value)
                box.press("Enter")
                settle(mp, 900)
            mp.locator(".st-key-cta-btn button").click()
            mp.wait_for_selector(".st-key-add_goal", timeout=30_000)
            settle(mp)
            mp.locator(".st-key-add_goal button").nth(0).click()
            settle(mp, 1200)
            mp.locator(".st-key-add_goal button").nth(2).click()
            settle(mp, 1500)
            second = mp.screenshot()
            mp.locator(".st-key-cta-btn button").click()
            mp.wait_for_selector(".st-key-rk-btn-balanced", timeout=240_000)
            settle(mp, 1800)
            third = mp.screenshot()
            phone.close()
            browser.close()
        shots = [Image.open(io.BytesIO(b)).convert("RGB") for b in (first, second, third)]
        gap, h = 36, shots[0].height
        canvas = Image.new("RGB", (sum(s.width for s in shots) + gap * (len(shots) - 1), h), BG)
        x = 0
        for s in shots:
            canvas.paste(s, (x, 0))
            x += s.width + gap
        canvas = canvas.resize((canvas.width // 2, canvas.height // 2), Image.LANCZOS)
        canvas.save(out / "mobile.png", optimize=True)
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except Exception:
                server.kill()
        try:
            tmp.cleanup()
        except OSError:
            pass

    for path in sorted(out.glob("*")):
        print(f"{path.name:18s} {path.stat().st_size / 1024:8.0f} kB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
