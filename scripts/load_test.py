"""Prova di carico: N utenti simultanei percorrono il flusso fino al piano su un solo processo Streamlit.

    pip install -r requirements-dev.txt
    playwright install chromium
    python scripts/load_test.py 1 4 8 16                     # avvia un server locale per ogni livello di concorrenza
    python scripts/load_test.py 8 --url https://mia-app.example.com

Per ogni livello misura, per utente, il tempo per vedere le tre anteprime del rischio e quello per ottenere il piano; con
un server locale (e ``psutil`` installato) riporta anche la memoria del processo. I browser girano sulla stessa macchina
del test: i numeri sono prudenti rispetto a utenti reali (che hanno il proprio browser). Un utente «di riscaldamento»
precede ogni livello.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_smoke import free_port, start_server  # noqa: E402


def rss_mb(proc) -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    main = psutil.Process(proc.pid)
    return sum(p.memory_info().rss for p in [main, *main.children(recursive=True)]) / 1e6


async def user(browser, url: str, index: int, results: list) -> None:
    """Un utente: punto di partenza, due obiettivi, rischio (anteprime), conferma, evoluzione e piano."""
    ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
    page = await ctx.new_page()
    marks: dict[str, float] = {}
    try:
        start = time.time()
        await page.goto(f"{url}/?lang=it")
        await page.wait_for_selector(".st-key-cta-home-btn button", timeout=300_000)
        await page.locator(".st-key-cta-home-btn button").click()
        await page.wait_for_selector(".st-key-amt-w0 input", timeout=60_000)
        box = page.locator(".st-key-amt-w0 input")
        await box.fill("20k")
        await box.press("Enter")
        await page.wait_for_timeout(1500)
        await page.locator(".st-key-chip-contribution button").nth(4).click()
        await page.wait_for_timeout(1500)
        await page.locator(".st-key-cta-btn button").click()
        await page.wait_for_selector(".st-key-add_goal", timeout=60_000)
        await page.wait_for_timeout(1000)
        for nth in (0, 2):
            await page.locator(".st-key-add_goal button").nth(nth).click()
            await page.wait_for_timeout(1500)
        t = time.time()
        await page.locator(".st-key-cta-btn button").click()
        await page.wait_for_selector(".st-key-rk-btn-balanced", timeout=900_000)
        marks["previews"] = time.time() - t
        await page.wait_for_timeout(800)
        await page.locator(".st-key-cta-btn button").click()
        await page.wait_for_selector(".st-key-card-auto", timeout=60_000)
        await page.wait_for_timeout(800)
        t = time.time()
        await page.locator(".st-key-cta-btn button").click()
        await page.wait_for_selector(".st-key-cta-late-btn button", timeout=900_000)
        marks["search"] = time.time() - t
        await page.locator(".st-key-cta-late-btn button").click()
        await page.wait_for_selector(".gx-ring", timeout=300_000)
        marks["total"] = time.time() - start
        results.append((index, marks, None))
    except Exception as exc:  # noqa: BLE001 - un utente che non arriva in fondo è un risultato, non un crash
        results.append((index, marks, f"{type(exc).__name__}: {str(exc)[:120]}"))
    finally:
        await ctx.close()


async def level(n: int, url: str | None) -> None:
    from playwright.async_api import async_playwright

    tmp = tempfile.TemporaryDirectory()
    server, target = None, url
    if target is None:
        port = free_port()
        server = start_server(port, str(Path(tmp.name) / "load.db"))
        target = f"http://127.0.0.1:{port}"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            warm: list = []
            await user(browser, target, -1, warm)
            base = rss_mb(server) if server else None
            results: list = []
            began = time.time()
            await asyncio.gather(*[user(browser, target, i, results) for i in range(n)])
            wall = time.time() - began
            peak = rss_mb(server) if server else None
            await browser.close()
        ok = [r for r in results if r[2] is None]

        def stat(key: str) -> str:
            xs = [r[1][key] for r in ok if key in r[1]]
            return f"mediana {statistics.median(xs):5.1f} s  max {max(xs):5.1f} s" if xs else "n/d"

        print(f"\n== {n} utenti simultanei ==  completati {len(ok)}/{n} in {wall:.0f} s", flush=True)
        print(f"   anteprime del rischio : {stat('previews')}")
        print(f"   ricerca -> piano      : {stat('search')}")
        print(f"   percorso completo     : {stat('total')} (include ~25 s di pause dello script)")
        if base is not None and peak is not None:
            print(f"   memoria del server    : {base:.0f} MB dopo il riscaldamento -> {peak:.0f} MB "
                  f"({(peak - base) / max(n, 1):.0f} MB per sessione)")
        for index, marks, error in results:
            if error:
                print(f"   FALLITO utente {index}: {error} {marks}")
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=15)
            except Exception:  # noqa: BLE001
                server.kill()
        try:
            tmp.cleanup()
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("users", nargs="*", type=int, default=[1, 4], help="livelli di concorrenza (predefinito: 1 4)")
    ap.add_argument("--url", help="app già in esecuzione (altrimenti si avvia un server locale per ogni livello)")
    args = ap.parse_args()
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("Playwright non installato: pip install -r requirements-dev.txt && playwright install chromium")
        return 2
    for n in args.users:
        asyncio.run(level(n, args.url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
