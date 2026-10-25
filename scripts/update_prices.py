"""Aggiorna l'archivio dei prezzi mensili dell'universo (``data/prices_monthly.parquet``).

Scarica i prezzi aggiustati di tutti gli asset investibili del catalogo (ETF curati e azioni ordinarie), li converte
in euro e riscrive archivio e metadati. Va eseguito a intervalli regolari (di norma una volta al mese: i dati sono
mensili); vedi ``.github/workflows/update-prices.yml``.

    python scripts/update_prices.py                 # universo completo, ultimi 20 anni (qualche minuto)
    python scripts/update_prices.py --limit 200     # prova rapida su un sottoinsieme
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from goalga import snapshot  # noqa: E402
from goalga.universe import catalog  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, default=snapshot.DEFAULT_YEARS, help="anni di storico da conservare (20)")
    ap.add_argument("--batch", type=int, default=100, help="ticker per richiesta (100)")
    ap.add_argument("--limit", type=int, default=0, help="solo i primi N ticker (prove)")
    ap.add_argument("--out", type=Path, default=None, help="file di destinazione (predefinito: data/prices_monthly.parquet)")
    ap.add_argument("--min-assets", type=int, default=0,
                    help="se meno asset del previsto hanno prezzi l'archivio esistente non viene sostituito")
    args = ap.parse_args()

    table = catalog()
    table = table[table["Skip"] == ""]
    currencies = table["Valuta"].to_dict()
    if args.limit:
        currencies = dict(list(currencies.items())[: args.limit])
    print(f"Scarico {len(currencies)} asset ({args.years} anni, blocchi da {args.batch})...", flush=True)
    t0 = time.time()

    def progress(done: int, total: int) -> None:
        print(f"  {done}/{total} ticker richiesti ({time.time() - t0:.0f}s)", flush=True)

    prices, meta = snapshot.build_snapshot(currencies, years=args.years, batch=args.batch, progress=progress)
    ratio = prices.shape[1] / max(1, len(currencies))
    print(f"Ottenuti {prices.shape[1]} asset su {len(currencies)} ({ratio:.0%}), {prices.shape[0]} mesi "
          f"({meta['first']} - {meta['last']}); senza dati: {len(meta['failed'])}", flush=True)
    if args.min_assets and prices.shape[1] < args.min_assets:
        print(f"Errore: meno di {args.min_assets} asset, l'archivio esistente non viene sostituito.", file=sys.stderr)
        return 1
    path = snapshot.save_snapshot(prices, meta, args.out)
    print(f"Salvato {path} ({path.stat().st_size / 1e6:.1f} MB) in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
