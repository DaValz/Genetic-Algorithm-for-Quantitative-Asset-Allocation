<div align="center">

# GoalGA · allocazione dinamica per obiettivi

**Un robo-advisor guidato in cui un algoritmo genetico trova — e ti fa vedere — la strategia d'investimento più
probabile per i tuoi obiettivi.**

[![CI](https://github.com/DaValz/goalga/actions/workflows/ci.yml/badge.svg)](https://github.com/DaValz/goalga/actions/workflows/ci.yml)
[![Licenza: MIT](https://img.shields.io/badge/licenza-MIT-2EA44F.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/built%20with-Streamlit-FF4B4B?logo=streamlit&logoColor=white)
[![Paper](https://img.shields.io/badge/basato%20su-Pomante%2C%20Farina%20%26%20Cucurachi%20%282024%29-8C2D19)](https://doi.org/10.3905/jwm.2024.1.227)

[English](README.md) · [Come si usa](#come-si-usa) · [Il paper](#il-paper) · [Avvio rapido](#avvio-rapido) ·
[Deploy](#deploy) · [Limiti](#limiti-e-avvertenze)

<img src="docs/images/hero.png" alt="Schermata iniziale di GoalGA" width="880">

</div>

> Versione italiana, in sintesi. La documentazione completa (deploy, configurazione, struttura del progetto, aggiunta di una
> lingua) è in inglese: [`README.md`](README.md).

> [!IMPORTANT]
> GoalGA è uno strumento di supporto alle decisioni e a scopo didattico, **non consulenza finanziaria**. I risultati
> poggiano su dati storici e ipotesi di rendimento; costi, commissioni e tasse non sono modellati. Leggi
> [Limiti e avvertenze](#limiti-e-avvertenze) prima di usarlo con denaro o clienti reali.

Un percorso guidato, in stile *robo-advisor*, che trova la **strategia d'investimento giusta per i tuoi obiettivi** e ti fa
*vedere* come l'algoritmo genetico la trova: ogni linea è una strategia, si sfidano, si incrociano e mutano finché resta la
migliore.

Dato un piano (capitale, versamenti, obiettivi di spesa negli anni) e un universo di strumenti, calcola il **glide path**
ottimale: quale dei 9 portafogli efficienti (P1 difensivo … P9 aggressivo) detenere in ciascun anno, con rischio non
crescente nel tempo, per massimizzare la probabilità di raggiungere tutti gli obiettivi e, raggiunta la soglia, il
rendimento negli scenari peggiori.

Implementa il modello di Ugo Pomante, Vincenzo Farina e Paolo Antonio Cucurachi,
[*A "Plug-and-Play," Goal-Based, Dynamic Asset Allocation Model with Genetic Algorithms*](https://doi.org/10.3905/jwm.2024.1.227),
*The Journal of Wealth Management* 26(4), Spring 2024 (riferimento completo e come citarlo in [Il paper](#il-paper)).

## Come si usa

Nessuna barra laterale: **una domanda per schermata**, in sei lingue (inglese, italiano, spagnolo, francese, russo, cinese)
con selettore in alto a destra.

| Passo | Cosa succede |
|---|---|
| **Home** | L'algoritmo evolve in sottofondo; tre contatori («1.000+ futuri simulati», «100+ strategie che si incrociano a ogni generazione», «3.400+ asset analizzabili in ogni settore»). Si parte sempre da un piano nuovo. |
| **1 · Punto di partenza** | Capitale e versamento annuo, da scrivere liberamente: `20000`, `20.000`, `20k`, `1,5M`, `2 milioni`, `2 million`, `2 millones`, `2 млн`, `100万`… (una cifra aggiunta a un importo già formattato ne conserva il significato: `€ 250.000` + `0` fa 2,5 milioni). Un clic nel campo ne seleziona il valore, così il numero successivo lo sostituisce. |
| **2 · Obiettivi** | Linea del tempo: quanto serve e in quale anno. Un solo cursore per obiettivo, su una scala di anni di calendario: il fumetto sopra il cursore si ingrandisce mentre lo trascini e mostra in grande **l'anno** che stai scegliendo («2062») con «tra 36 anni» sotto, e il titolo della scheda si aggiorna man mano. **Si ripete ogni anno** aggiunge un secondo cursore per una spesa annuale (studi, pensione). |
| **3 · Rischio** | *«Quanto rischio sei disposto ad assumere?»* Prudente (P1–P3), Equilibrato (P1–P6), Dinamico (P1–P9), ciascuno con la probabilità di raggiungere i tuoi obiettivi. |
| **4 · Conferma** | *«Confermi il piano?»* Riepilogo, difficoltà del piano e, sotto, due pulsanti a tutta larghezza: **Trova la mia strategia** e **Usa impostazioni avanzate**. Se hai personalizzato qualcosa, la scheda dice cosa e compare «Torna alle scelte automatiche». |
| **5 · Evoluzione** | *«L'algoritmo sta ragionando»*: il replay della ricerca reale, con didascalie che cambiano; non si salta e non si rivede. |
| **6 · Il tuo piano** | Esito in «futuri su 100» verificato su 10.000 scenari nuovi, composizione nel tempo, confronto con le alternative, **collegamento alla composizione esatta degli asset**, Excel/JSON, salvataggio nel tuo account. |

La **configurazione avanzata** raccoglie ciò che l'app decide da sola, in cinque passi guidati: **1 · Universo** (quali classi di
fondi e quali settori può usare l'algoritmo, quante azioni, esclusioni o una lista scelta a mano; un imbuto mostra asset
*valutati → idonei → usati* e ogni asset si può sfogliare per categoria), **2 · Rendimenti** (ipotesi di lungo periodo o storico,
cursore di ottimismo, ritocchi per classe), **3 · Portafogli** (diversificazione, frontiera efficiente, opzioni per esperti),
**4 · Ricerca** (livello di impegno, seed fisso per risultati riproducibili, parametri dell'algoritmo) e **5 · Verifiche**
(analisi completa del piano).

## Come sceglie gli asset

Ad ogni avvio l'algoritmo **valuta tutti gli asset del catalogo** (40 ETF curati e ~3.400 azioni): solo azioni ordinarie
(niente privilegiate, fondi chiusi, warrant, unit, criptovalute), storico completo degli ultimi 10 anni, prezzi
aggiornati, nessun movimento mensile oltre +100% / −60%, volatilità annua ≤ 80% per le azioni. Poi **estrae un pool**:
*tutti* i fondi idonei più 33 azioni distribuite sugli 11 settori, con un **seed nuovo a ogni avvio** (stessi obiettivi e
stesso profilo di rischio → un altro campione dell'universo → un nuovo calcolo). Con lo stesso seed si riottiene lo stesso
risultato: nell'area avanzata si può fissare. I rendimenti attesi dei fondi sono ipotesi di lungo periodo; quelli delle
azioni derivano dal CAPM (beta misurato sull'S&P 500 in euro). Le azioni entrano nella frontiera come **un'unica cesta** a
pesi uguali (almeno il 30% dell'esposizione azionaria, al massimo il 60% del portafoglio) e ogni asset class pesa al
massimo il 40% in totale, così più ETF simili non aggirano il limite. **Niente posizioni troppo piccole per essere
acquistate**: nessun fondo sotto l'1% e nessun titolo della cesta sotto lo 0,5%, perciò la cesta compare solo nei
portafogli in cui vale almeno 33 × 0,5% = 16,5% (dal sesto in su). La finestra storica usata è la più recente, di 14 anni al
massimo (i primi mesi di alcuni ETF giovani hanno quotazioni errate).

Gli **obiettivi sono in euro di oggi e si rivalutano del 2% l'anno** (inflazione, modificabile nell'area avanzata anche a
0%); versamenti e obiettivi sono a fine anno, come nel paper. Il numero in evidenza e il confronto con le strategie
semplici sono calcolati su 10.000 scenari nuovi; il rendimento minimo necessario (composto) si confronta con il
rendimento **composto** atteso dei portafogli, non con la media aritmetica.

## Il paper

GoalGA è un'implementazione indipendente e open source del modello descritto in:

> Pomante, U., Farina, V., & Cucurachi, P. A. (2024). **A "Plug-and-Play," Goal-Based, Dynamic Asset Allocation Model
> with Genetic Algorithms.** *The Journal of Wealth Management*, 26(4), 33–48.
> [doi:10.3905/jwm.2024.1.227](https://doi.org/10.3905/jwm.2024.1.227)

**L'idea in quattro righe** (parafrasi: il paper contiene la trattazione completa):

1. Un investitore ha un capitale oggi, risparmia una somma fissa ogni anno e ha spese — gli *obiettivi* — a date note.
2. Chi costruisce il modello fornisce un menu di portafogli ordinati per rischio: al metodo non importa come siano stati
   costruiti (da qui «plug-and-play»).
3. Una *strategia* sceglie un portafoglio per anno, con un rischio che non aumenta mai: un glide path come quello di un
   fondo a data target, ma costruito sugli obiettivi dell'investitore.
4. Un algoritmo genetico fa evolvere le strategie su futuri di mercato simulati: prima sale verso una probabilità
   obiettivo *Pr\** di raggiungere tutti gli obiettivi e, raggiunta la soglia, massimizza l'IRR medio negli scenari
   peggiori (`IRR_ES`).

**Cosa riproduce questo repository.** Funzione obiettivo (Eq. 1) e codifica non crescente (Eq. 2); operatori genetici e
parametri (sezione IV, Exhibit 2–3); bootstrap con reinserimento; ricentratura sui rendimenti attesi di lungo periodo
(sezione I, Exhibit 6); il caso di studio (160.000 €, 10.000 € l'anno, 50 anni, obiettivi dell'Exhibit 4), con rendimento
minimo necessario **4,43%** nel paper e **4,427%** qui; l'esempio di mutazione di pag. 40; la robustezza su lanci ripetuti
(Exhibit 9–10) e il confronto con strategie alternative (Exhibit 11). Ogni verifica è in [`docs/AUDIT.md`](docs/AUDIT.md) e
in `tests/`; la tabella «Paper → codice» è nel [README inglese](README.md#paper--code).

**Cosa aggiunge GoalGA.** I nove portafogli costruiti da un universo reale e filtrato di fondi e azioni (il paper li lascia a
chi costruisce il modello); la verifica su 10.000 scenari nuovi, perché l'ottimizzatore sovrastima la probabilità che
trova; i profili di rischio; l'elitismo e un tetto di generazioni; i piani che ripartono a metà anno; e tutta la parte di
prodotto: interfaccia guidata, account, avvisi, esportazione, sei lingue.

> [!NOTE]
> Non è il codice degli autori e il paper non è incluso nel repository (diritti dell'editore). Eventuali errori nel codice
> o nella sua descrizione sono del manutentore, non degli autori.

**Come citare.** Cita il paper — il metodo è degli autori — e, se vuoi, anche questo repository: il pulsante *Cite this
repository* di GitHub legge [`CITATION.cff`](CITATION.cff); il BibTeX è nel [README inglese](README.md#citing).

## Account e avvisi

Puoi creare un account, salvare i piani come **portafogli**, **seguire** quelli in cui investi e modificarli nel tempo. Il
pulsante in alto a destra dice *Accedi o registrati* agli ospiti (solo l'icona sugli schermi stretti) e, dopo l'accesso, mostra
il tuo nome e gli avvisi non letti.
Ogni volta che i pesi target cambiano di almeno la soglia scelta (5 punti percentuali di default) ricevi un **avviso** nell'app
e, se configurato l'SMTP, per **email**: succede quando il glide path scende di livello, quando una revisione periodica
(ogni 90 giorni) rilancia l'algoritmo con prezzi aggiornati, o quando modifichi il piano. La revisione è eseguita da
`scripts/monitor_portfolios.py` (workflow GitHub Actions `monitor.yml`). Una revisione riparte **dal giorno in cui gira**
(il primo anno è parziale: il primo flusso resta al prossimo anniversario dell'investimento) e dal patrimonio mediano previsto
per quel giorno, corretto dello scarto dell'ultimo valore registrato; «Modifica» riparte dal piano rimasto (capitale di
oggi, anni degli obiettivi contati da oggi) e non dal piano iniziale.

## Avvio rapido

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
streamlit run app.py
```

L'app si apre su <http://localhost:8501> (Python 3.11 o 3.12, Streamlit 1.63–1.66: `requirements.txt` limita la versione a quelle
provate nel browser). Aggiungi `?lang=it` all'indirizzo per
forzare la lingua. Mentre l'app è in uso non scarica nulla: i prezzi mensili in euro di tutto l'universo sono nell'archivio
`data/prices_monthly.parquet`, che si rigenera con `python scripts/update_prices.py` (nel repository lo fa ogni mese il
workflow `update-prices.yml`; servono le dipendenze di `requirements-data.txt`).

## Deploy

- **Pubblicare il repository** (dalla cartella del progetto, con la [GitHub CLI](https://cli.github.com) autenticata come
  proprietario): `git init -b main`, `git add .`, `git commit -m "GoalGA"`, poi
  `gh repo create DaValz/goalga --public --source=. --remote=origin --push` (`--private` per tenerlo chiuso).
- **Streamlit Community Cloud**: [share.streamlit.io](https://share.streamlit.io) → *Create app* → repository
  `DaValz/goalga`, file principale `app.py`, Python 3.12. Dopo il deploy aggiungi l'indirizzo dell'app al README (link
  *Live demo*) e al segreto `GOALGA_APP_URL`.
  I segreti (facoltativi) sono descritti in [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example).
- **Account persistenti**: il file SQLite locale si azzera a ogni riavvio di Community Cloud; imposta
  `GOALGA_DATABASE_URL` con un database PostgreSQL gratuito (Neon, Supabase, Railway…).
- **Avvisi**: aggiungi gli stessi segreti (`GOALGA_DATABASE_URL`, ed eventualmente `GOALGA_SMTP_*` e `GOALGA_APP_URL`)
  in *Settings → Secrets and variables → Actions* del repository.
- **Prezzi**: il workflow `update-prices.yml` (ogni mese, o a mano da *Actions*) rigenera e committa l'archivio; il commit
  rilascia di nuovo l'app. Verifica la **licenza dei dati** prima di un uso commerciale (vedi il README inglese).
- **Docker**: `docker build -t goalga .` e `docker run -p 8501:8501 -v goalga-data:/data goalga`.

## Test

```bash
pip install -r requirements-dev.txt
pytest -q                          # ~3 minuti, 600+ test (archivio di prezzi sintetico, nessuna rete)
ruff check .
playwright install chromium        # una tantum
python scripts/e2e_smoke.py        # ~80 controlli nel browser (avvia da solo il server)
python scripts/e2e_smoke.py --mobile --lang fr
```

## Documenti

- [`docs/DESIGN.md`](docs/DESIGN.md): principi di design, flusso, internazionalizzazione, vincoli tecnici di Streamlit.
- [`docs/AUDIT.md`](docs/AUDIT.md): rapporto di verifica rispetto al paper e alle funzioni aggiunte.

## Limiti e avvertenze

- Il modello è uno strumento di supporto alle decisioni e **non costituisce consulenza finanziaria**; prima di usarlo con
  clienti reali servono la validazione e le verifiche regolamentari di ogni strumento di consulenza (i controlli numerici
  svolti sono in [`docs/AUDIT.md`](docs/AUDIT.md), sezione «Verifica per l'uso con denaro reale»).
- I risultati dipendono da dati storici e da ipotesi di rendimento: il passato non garantisce il futuro. La finestra storica
  comune è di circa **11–12 anni (senza il 2008)** e le code poggiano su pochi episodi (12/2018, 03–04/2020, 2022): togliendo il
  2022 la probabilità dello stesso piano passa dal 90,5% al 94,6%. Con seed diversi un piano di difficoltà media varia di
  1–2 punti percentuali.
- Prezzi in euro (le attività in dollari includono il cambio EUR/USD, non coperto); **nessun costo, commissione o tassa**,
  né vincolo di liquidità; l'universo azionario è soggetto a *survivorship bias* e lo storico è mensile (20 anni al massimo,
  14 usati).
- Il paniere di azioni è un **campione** (con seed) dell'universo, non una raccomandazione; la quota minima del 30%
  dell'esposizione azionaria è una scelta di progetto modificabile nell'area avanzata. ETF e azioni quotati negli USA possono non
  essere acquistabili da tutti i risparmiatori europei (regole PRIIPs/KID): i 18 ETF UCITS del catalogo lo sono.
- Gli account sono volutamente semplici: nessuna verifica email, recupero password o cookie «ricordami» (da aggiungere prima
  di un uso pubblico). Su Community Cloud il SQLite predefinito non è persistente.

## Licenza

Il codice è rilasciato con licenza [MIT](LICENSE). La licenza copre solo il codice: il font Inter mantiene la propria (SIL
Open Font License, [`static/fonts/OFL.txt`](static/fonts/OFL.txt)) e l'archivio dei prezzi in `data/` segue i termini del
suo fornitore di dati: i dati di Yahoo Finance sono pensati per uso personale o di ricerca e ridistribuirne un archivio
derivato in un repository pubblico è una zona grigia. Per un servizio **commerciale** sostituisci il downloader in
`goalga/snapshot.py` con un fornitore di dati con licenza e tieni l'archivio privato (vedi il README inglese, sezione
*Data*).
