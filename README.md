<div align="center">

# GoalGA

**Goal-based investing, evolved.**

A guided, minimal "robo-advisor" in which a **genetic algorithm** finds — and lets you *watch* — the investment
strategy most likely to reach your financial goals.

[![CI](https://github.com/DaValz/goalga/actions/workflows/ci.yml/badge.svg)](https://github.com/DaValz/goalga/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-2EA44F.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/built%20with-Streamlit-FF4B4B?logo=streamlit&logoColor=white)
![Languages](https://img.shields.io/badge/languages-EN%20%C2%B7%20IT%20%C2%B7%20ES%20%C2%B7%20FR%20%C2%B7%20RU%20%C2%B7%20ZH-8B9CFF)
[![Paper](https://img.shields.io/badge/based%20on-Pomante%2C%20Farina%20%26%20Cucurachi%20%282024%29-8C2D19)](https://doi.org/10.3905/jwm.2024.1.227)

[How it works](#how-it-works) · [The paper](#the-paper) · [Run it](#quick-start) ·
[Deploy it](#deploy-from-your-github-profile) · [Accounts & alerts](#accounts-and-weight-change-alerts) ·
[Italiano](README.it.md)

<img src="docs/images/hero.png" alt="GoalGA welcome screen: 'Your plan, evolved.'" width="880">

</div>

## Overview

Give GoalGA a plan — how much you have, how much you can add each year, and the expenses you want to cover (a home, a
degree, retirement) — and it computes the **glide path**: which of nine efficient portfolios, from defensive **P1** to
aggressive **P9**, to hold in each year of the plan. Risk can only go *down* over time, like a target-date fund, but the
path is tailored to *your* goals instead of your birth year.

The search is done by a genetic algorithm on thousands of simulated market futures. First it looks for strategies that
reach every goal in at least *Pr\** of the futures (90% by default); among those it keeps the one with the best return
in the worst scenarios. You see the answer as "**N futures out of 100**", checked again on 10,000 scenarios the algorithm
has never seen.

GoalGA implements the model of Ugo Pomante, Vincenzo Farina and Paolo Antonio Cucurachi —
[*A "Plug-and-Play," Goal-Based, Dynamic Asset Allocation Model with Genetic Algorithms*](https://doi.org/10.3905/jwm.2024.1.227),
*The Journal of Wealth Management* 26(4), Spring 2024 (see [The paper](#the-paper) for the reference, what is taken from
it and what is added) — and wraps it in a calm, step-by-step product experience, with accounts, alerts and six
languages.

> [!IMPORTANT]
> GoalGA is a decision-support and educational tool, **not financial advice**. Results rest on historical data and
> return assumptions, and costs, fees and taxes are not modelled. Read [Limitations](#limitations) before using it with
> real money or real clients.

## Highlights

| | |
|---|---|
| **Guided, one question per screen** | No sidebar, almost no inputs: amounts you can type naturally (`20000`, `20k`, `1.5M`, *"2 million"*, *"2 milioni"*, `100万`…), a visual timeline of goals whose slider names the **year** you are choosing while you drag it, three risk profiles. Moving between screens is a soft fade, never a hard cut. |
| **Autopilot with an open door** | Markets, expected returns and algorithm parameters are chosen for you. A large **Use advanced settings** button under the confirmation summary opens the advanced configuration — a five-step guide, not a wall of controls — and *Back to automatic choices* resets everything and takes you back. |
| **The whole universe, every launch** | Each run evaluates ~3,500 funds and stocks, keeps every eligible fund and draws a diversified basket of stocks from all eleven sectors with a fresh seed — so, over time, every eligible stock gets its chance. |
| **Watch the algorithm think** | The evolution screen replays the *real* recorded search: every line is a candidate strategy; they compete, cross over and mutate until the best one survives. No skip, no replay — once it's done, it's done. |
| **Risk you choose, odds you see** | "How much risk are you willing to take?" Cautious, balanced or dynamic — each card shows the probability of reaching your goals with that level, as 100 dots. |
| **Honest numbers** | The headline probability is verified out-of-sample; it is never "100 out of 100" if a single scenario fails; impossible plans are explained, not hidden; every run can be reproduced with a fixed seed. |
| **See exactly what you own** | A dedicated page lists the exact funds, tickers and weights for every year of the plan, grouped by category, with a donut, a year-by-year heatmap and a CSV export. |
| **Accounts and alerts** | Save portfolios, follow the ones you invest in, edit them over time. Whenever the algorithm changes your target weights you get an alert in the app and, optionally, by e-mail. |
| **Six languages** | English, Italian, Spanish, French, Russian and Chinese, detected from the browser and switchable from the top-right corner. Numbers, currencies and plurals follow each locale. |
| **Production-minded** | 600+ automated tests (core, UI, accounts, i18n, real-browser), a scheduled price archive and monitoring job, Docker image, PostgreSQL support, no external CDN, no network access while users are on the site. |

## The experience

<p align="center"><img src="docs/images/evolution.gif" alt="The algorithm at work: strategies compete, cross over and mutate" width="720"><br>
<sub><b>The algorithm at work</b> — the real recorded search: every line is a candidate strategy.</sub></p>

<table>
  <tr>
    <td width="50%"><img src="docs/images/goals.png" alt="Goals timeline with the year bubble on the slider"><br><sub><b>Goals</b> — a visual timeline; while you drag a handle, a bubble above it names the year you are choosing ("2062 · in 36 years") and the card's title follows. Turn on <i>Repeats every year</i> for recurring goals (studies, retirement).</sub></td>
    <td width="50%"><img src="docs/images/risk.png" alt="Risk profiles"><br><sub><b>Risk</b> — three profiles, each with the probability of success it allows.</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/images/review.png" alt="Confirm your plan"><br><sub><b>Confirm</b> — a receipt, the difficulty gauge and two full-width buttons: find my strategy, or use advanced settings.</sub></td>
    <td width="50%"><img src="docs/images/plan.png" alt="Your plan"><br><sub><b>Your plan</b> — outcome, allocation over time, possible futures and comparison with simple alternatives.</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/images/holdings.png" alt="Portfolio composition"><br><sub><b>Composition</b> — the exact assets, year by year, grouped by category.</sub></td>
    <td width="50%"><img src="docs/images/account.png" alt="Personal space with an alert"><br><sub><b>Personal space</b> — saved portfolios and a weight-change alert.</sub></td>
  </tr>
  <tr>
    <td colspan="2"><img src="docs/images/lab.png" alt="Advanced configuration, step 1: the universe"><br><sub><b>Advanced configuration</b> — five guided steps; step 1 lets you pick fund classes and sectors, with a funnel from <i>evaluated</i> to <i>eligible</i> to <i>used</i> assets.</sub></td>
  </tr>
</table>

<p align="center"><img src="docs/images/mobile.png" alt="The same flow on a phone" width="760"><br>
<sub><b>Mobile</b> — the same flow on a phone.</sub></p>

### The screens

| Step | What happens |
|---|---|
| **Welcome** | The algorithm evolves in the background. Three counters climb to *1,000+ simulated futures*, *100+ strategies crossing over each generation* and *3,400+ assets analysed across every sector*. Every visit starts a fresh plan. |
| **1 · Starting point** | Savings today and per year, typed freely: `20000`, `20.000`, `20k`, `1.5M`, `2 million`, `2 milioni`, `2 millones`, `2 млн`, `100万`… (a digit appended to a formatted amount keeps its meaning: `€250,000` + `0` is 2.5 million). Clicking a field selects its value so the next number replaces it. |
| **2 · Goals** | A timeline: how much you need and in which year. One handle per goal, on a scale of calendar years: the bubble above it grows while you drag and shows the **year** you are choosing in large type ("2062") with "in 36 years" below, and the card's title updates as you go. **Repeats every year** adds a second handle for a yearly expense (studies, retirement). |
| **3 · Risk** | *How much risk are you willing to take?* Three cards — **Cautious** (mostly bonds, portfolios P1–P3), **Balanced** (a mix, P1–P6) and **Dynamic** (mostly equities, P1–P9) — with the success probability, the maximum equity share and a "bad year" figure (1 year in 20). |
| **4 · Confirm** | *Confirm your plan?* A receipt, the **difficulty gauge** (required return vs. what the portfolios can deliver) and, below, two full-width buttons: **Find my strategy** and **Use advanced settings**. If you customised something, the card lists what and a *Back to automatic choices* link appears. |
| **5 · Evolution** | *The algorithm is thinking…* The recorded search, with captions that change as it goes: *Simulations launched → Generating the paths → Strategies compete and cross over → Discarding the weakest paths → Choosing the optimal path.* |
| **6 · Your plan** | The outcome in "futures out of 100", verification on new scenarios, allocation over time, a clear link to the **exact composition**, possible futures (fan chart), *Why this strategy* (comparison bars), *What if I take more or less risk?*, Excel / JSON export and "save to my account". |
| **Composition** | Exact funds, tickers and weights for any year, a heatmap of all years, CSV download. |
| **Account** | Sign up / sign in, your saved portfolios, alerts, real-value check-ins, settings. |
| **Advanced configuration** | Optional, in five guided steps. **1 · Universe** — which fund classes and sectors the algorithm may use, how many stocks, exclusions or a hand-picked list; a funnel shows *evaluated → eligible → used* and every asset can be browsed by category. **2 · Returns** — long-term assumptions or history, an optimism slider, per-class tweaks. **3 · Portfolios** — diversification, the efficient frontier, expert options. **4 · Search** — effort presets, a fixed seed for reproducible runs, every algorithm parameter. **5 · Checks** — the full analysis (KPIs, projections, risk, benchmarks, convergence, robustness over repeated runs). |

## How it works

```mermaid
flowchart LR
    A["Plan<br/>capital · savings · goals"] --> C
    U["Universe<br/>~3,500 funds and stocks<br/>monthly prices in EUR"] --> P["Screen + seeded pool<br/>every eligible fund<br/>diversified stocks"]
    P --> D["9 efficient portfolios<br/>P1 … P9"]
    D --> C["Scenarios<br/>block bootstrap<br/>1,000 futures"]
    C --> E["Genetic algorithm<br/>glide-path candidates"]
    R["Risk profile<br/>caps the portfolio level"] --> E
    E --> F["Best strategy"]
    F --> G["Validation<br/>10,000 unseen scenarios"]
    G --> H["Plan · composition · export"]
    H --> I["Saved portfolio<br/>alerts when weights change"]
```

**The universe.** Prices live in one monthly archive (`data/prices_monthly.parquet`: ~2,800 assets, 20 years, adjusted
for dividends and splits, converted to euro with the month-end EUR/USD rate) that a scheduled job refreshes. The app
never downloads anything while you use it. At every launch the algorithm:

1. **evaluates every asset** of the catalogue (40 curated ETFs + ~3,400 stocks): ordinary shares only (no preferred
   shares, closed-end funds and investment trusts — which the screeners file under "asset management" —, warrants, units
   or crypto), a complete history over the last 10 years, no stale data, no monthly move beyond +100% / −60%, annual
   volatility ≤ 80% for stocks. Each exclusion has a reason, listed in the advanced area;
2. **draws a pool**: *every* eligible fund (cash, government / corporate / high-yield / emerging bonds, developed and
   emerging equity, commodities, real estate) plus 33 stocks spread over the 11 sectors (quota ∝ √sector size; inside a
   sector, a better risk-adjusted CAPM score means a higher probability). The draw is driven by the launch's **seed**, so
   every new launch looks at a different slice of the universe and the same seed reproduces the same pool;
3. **builds the market**: funds use long-term capital-market assumptions; stocks use the CAPM
   (`rf + β·ERP`, with Blume-adjusted betas measured against the S&P 500 in euro). The stocks enter the frontier as **one
   equal-weight basket** that must be at least 30% of the equity exposure (and at most 60% of the portfolio). Left alone,
   a mean-variance optimiser would pile the stock exposure on three to five names — on the bundled archive, up to 100%
   in three stocks in the most aggressive portfolio — exploiting noise in individual betas; the basket keeps the stock
   sleeve diversified and makes sure the whole pool contributes. Every asset class is also capped at 40% *in total*, so
   duplicate ETFs cannot sidestep the per-asset cap. **Nothing too small to buy:** no fund is held below 1% and no stock
   of the basket below 0.5% — a portfolio is rebuilt at the same risk without any position under the minimum — so the
   basket appears only in the portfolios where it is worth at least 33 × 0.5% = 16.5% (from the sixth upwards).

Comparing risk profiles from the results page reuses the seed (same assets, same scenarios: only the risk changes);
every other launch draws a new one. Advanced users can fix the seed to reproduce a result.

**The market.** From monthly returns over a *common* historical window (no invented data, current month excluded; the
most recent 14 years at most, because the first months of some young ETFs carry bad quotes) the
app builds **nine long-only, mean-variance efficient portfolios** (Ledoit–Wolf shrinkage), equally spaced in
volatility. Expected returns are long-term assumptions by default (the historical distribution is *re-centred* on them,
keeping correlations and fat tails) and can be shifted in the advanced area.

**The scenarios.** One-year windows of historical monthly returns are resampled with replacement (a block bootstrap), so
real-world correlations and tails are inherited without assuming normality.

**The strategy.** A strategy is one portfolio level per year, never increasing. Its fitness is
`Pr` while the probability of reaching all goals is below the threshold `Pr*`, and `2 + IRR_ES` once it is reached
(`IRR_ES` is the average IRR in the worst α% of scenarios). The genetic algorithm — population 100, binary tournament,
one-point crossover (p = 0.55), ±2 mutation with minimal repair (p = 0.30), one elite, stop after 200 generations
without improvement — evolves candidate glide paths from a deliberately diverse initial population. Goals are expressed
in **today's euros and indexed by 2% a year** by default (set it to 0% in the advanced area for nominal amounts);
contributions stay flat unless you say otherwise, and goals and contributions are settled at year end, as in the paper.

**The risk profile is a cap, not a different objective.** *Cautious* may use portfolios P1–P3, *Balanced* P1–P6,
*Dynamic* P1–P9. The same search runs inside the allowed range, so comparing the three cards shows how much risk your
goals really require. Cards use a shorter search with the same seed (a prefix of the full one), so they are labelled as
estimates; the final result is then verified on unseen scenarios.

**The verification.** The optimiser tends to over-state the probability it found, so the headline number comes from
**10,000 fresh scenarios** (Wilson confidence interval shown), and the plan is compared — on those same fresh scenarios —
with a constant mix, linear de-risking and all-aggressive / all-cautious alternatives. The minimum return the goals need
is a *compound* rate, so it is compared with the *compound* expected return of the portfolios (the arithmetic mean
over-states what a long-run investor earns by about half the variance).

## The paper

GoalGA is an independent, open-source implementation of the model in:

> Pomante, U., Farina, V., & Cucurachi, P. A. (2024). **A "Plug-and-Play," Goal-Based, Dynamic Asset Allocation Model
> with Genetic Algorithms.** *The Journal of Wealth Management*, 26(4), 33–48.
> [doi:10.3905/jwm.2024.1.227](https://doi.org/10.3905/jwm.2024.1.227)

**The idea, in four lines** (a paraphrase — the paper has the full treatment):

1. An investor has capital today, saves a fixed amount every year and has expenses — *goals* — at known dates.
2. The modeller supplies a menu of risk-ranked portfolios. The method does not care how they were built, hence
   "plug-and-play".
3. A *strategy* picks one portfolio per year, with risk that never increases: a glide path, like a target-date fund,
   but fitted to the investor's own goals.
4. A genetic algorithm evolves strategies on simulated market futures. Its objective has two regimes: climb towards a
   target probability *Pr\** of meeting every goal and, once it is reached, maximise the average IRR in the worst
   scenarios (`IRR_ES`).

The authors present the method for **wealth management** (investors whose wealth must offset future liabilities) and for
**pension funds** (personalised investment paths for retirement needs), and report good convergence in a short
computation time.

**What this repository reproduces.** The objective function (Eq. 1) and the non-increasing encoding (Eq. 2); the genetic
operators and their parameters (Section IV, Exhibits 2–3); the bootstrap with replacement; the re-centring on long-term
expected returns (Section I, Exhibit 6); the case study (160,000 €, 10,000 € a year, 50 years, goals of Exhibit 4), whose
minimum required return is **4.43%** in the paper and **4.427%** here; the mutation example on page 40; the repeated-run
robustness check (Exhibits 9–10) and the comparison with alternative strategies (Exhibit 11). Every check is in
[`docs/AUDIT.md`](docs/AUDIT.md) (Italian) and in `tests/`: for instance, the genetic algorithm reaches the optimum of
exhaustive searches — every path of a small problem, and all 218,790 three-step strategies of a 50-year plan in 20 out of
20 seeds.

**What GoalGA adds** — each item is marked *(extension)* in the table below or described under [How it
works](#how-it-works): the nine portfolios built from a real, screened universe of funds and stocks (the paper leaves them
to the modeller); verification on 10,000 unseen scenarios, because the optimiser over-states the probability it found;
risk profiles; elitism and a generation cap; plans that restart mid-year; and the whole product layer — guided interface,
accounts, alerts, export, six languages.

> [!NOTE]
> This is an independent implementation, **not the authors' code**, and the paper itself is not included in this
> repository (publisher copyright). Any error in the code or in its description is the maintainer's, not the authors'.

### Paper → code

| Paper | Implementation |
|---|---|
| Objective `S = Pr` if `Pr < Pr*`, else `2 + IRR_ES` (Eq. 1) | `goalga/problem.py` → `GoalProblem._evaluate_block` |
| Non-increasing risk `I₁ ≥ I₂ ≥ … ≥ I_T` (Eq. 2) | `goalga/genetic.py` → `is_valid`, repair in `apply_gene_mutation` |
| Bootstrap with replacement, inherited correlations | `goalga/scenarios.py` |
| Re-centring on long-term expected returns (Section I, Exhibit 6) | `recenter_annual`, `recenter_monthly`, *Expected returns* table |
| Deliberately diverse initial population (note 8) | `goalga/genetic.py` → `random_population` (every individual has its own range of variation; half are step-wise) |
| Binary tournament, one-point crossover, ±v mutation with minimal repair (examples on pp. 39–40) | `tournament`, `crossover`, `mutate` |
| `p_c = 0.55`, `p_m = 0.30`, ±2, population 100, stop after 200 generations without improvement (Exhibits 2–3) | `GAConfig` defaults |
| Minimum required return — 4.43% in the case study | `goalga/problem.py` → `required_return` (4.427%) |
| Comparison with alternative strategies (Exhibit 11) | `goalga/analytics.py` → `benchmark_table` (repeated on the unseen scenarios in `out_of_sample`) |
| Repeated runs (Exhibits 9–10) | `goalga/analytics.py` → `run_robustness` |
| The nine asset-only ("A-O") portfolios, left to the modeller: "plug-and-play" | `goalga/portfolios.py` (efficient frontier), `goalga/market.py` (basket, class caps), `goalga/selection.py` (universe screen, seeded pool, CAPM) |
| *(extension)* elitism (one individual) and a generation cap | `GAConfig.elitism`, `GAConfig.max_generations` |
| *(extension)* no position too small to buy | `goalga/portfolios.py` → `prune_positions` |
| *(extension)* plans that restart mid-year (reviews, edits) | `goalga/problem.py` → `Flows.first_period`, `goalga/plan.py` → `Plan.advance` |

### Citing

If GoalGA helps your work, please cite the paper — the method is theirs — and, if you wish, this repository
(GitHub's **Cite this repository** button reads [`CITATION.cff`](CITATION.cff)):

```bibtex
@article{pomante2024plugandplay,
  author  = {Pomante, Ugo and Farina, Vincenzo and Cucurachi, Paolo Antonio},
  title   = {A ``Plug-and-Play,'' Goal-Based, Dynamic Asset Allocation Model with Genetic Algorithms},
  journal = {The Journal of Wealth Management},
  year    = {2024},
  volume  = {26},
  number  = {4},
  pages   = {33--48},
  doi     = {10.3905/jwm.2024.1.227}
}

@software{goalga,
  author  = {{DaValz}},
  title   = {{GoalGA}: goal-based dynamic asset allocation with genetic algorithms},
  year    = {2026},
  url     = {https://github.com/DaValz/goalga},
  version = {2.0.0},
  license = {MIT}
}
```

## Quick start

```bash
git clone https://github.com/DaValz/goalga.git
cd goalga
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
streamlit run app.py
```

Open <http://localhost:8501>. Python 3.11 or 3.12 and Streamlit 1.63–1.66 are required (the UI customises Streamlit
internals, so `requirements.txt` caps the version at the range the browser tests were run on; raise the cap only after
`python scripts/e2e_smoke.py` passes on the new release). Nothing is downloaded while you use the app: prices come from the bundled
archive `data/prices_monthly.parquet` (see [Price archive](#price-archive-monthly-refresh) to refresh it).

Add `?lang=it` (or `en`, `es`, `fr`, `ru`, `zh`) to the URL to force a language; otherwise it follows the browser.

## Deploy from your GitHub profile

### 1 · Publish the repository

From the project folder (with the [GitHub CLI](https://cli.github.com) signed in as the owner):

```bash
git init -b main
git add .
git commit -m "GoalGA"
gh repo create DaValz/goalga --public --source=. --remote=origin --push      # --private to keep it closed
```

Optional, for discoverability: `gh repo edit --add-topic streamlit --add-topic genetic-algorithm --add-topic robo-advisor
--add-topic asset-allocation --add-topic goal-based-investing --add-topic portfolio-optimization`. Check the licence of the
bundled price archive first (see [Data](#data)).

### 2 · Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, choose **Create app → Deploy from
   GitHub**, then pick `DaValz/goalga`, the branch and the main file **`app.py`**.
2. Open **Advanced settings**: select **Python 3.12** and paste your secrets (see
   [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example)). Everything is optional, but read the next
   section before you let real users create accounts.
3. **Deploy.** Dependencies come from [`requirements.txt`](requirements.txt); the theme, font and server options come
   from [`.streamlit/config.toml`](.streamlit/config.toml). Once the app is up, add its address to this README
   (a **Live demo** link next to the badges) and to the `GOALGA_APP_URL` secret.

### Persistent accounts

Accounts, portfolios and alerts live in a SQL database. Locally the app uses a SQLite file (`data/goalga.db`), which
**is wiped on every restart of Streamlit Community Cloud**. For anything real, provision a free PostgreSQL database
(Neon, Supabase, Railway…) and set one secret:

```toml
GOALGA_DATABASE_URL = "postgresql://user:password@host:5432/dbname?sslmode=require"
```

Tables are created automatically on first start. `psycopg2-binary` is already in `requirements.txt`.

### Weight-change alerts (scheduled monitor)

Alerts are produced by `scripts/monitor_portfolios.py`, which the workflow
[`.github/workflows/monitor.yml`](.github/workflows/monitor.yml) runs every day on GitHub Actions. In your repository go
to **Settings → Secrets and variables → Actions** and add `GOALGA_DATABASE_URL` (the *same* URL the app uses). For
e-mail delivery also add `GOALGA_SMTP_HOST`, `GOALGA_SMTP_PORT`, `GOALGA_SMTP_USER`, `GOALGA_SMTP_PASSWORD`,
`GOALGA_SMTP_FROM`, `GOALGA_SMTP_SECURITY` and `GOALGA_APP_URL`. Without SMTP, alerts still appear inside the app.
You can trigger it by hand from the **Actions** tab (*Run workflow*, with optional **force** and **dry run**).

### Docker

```bash
docker build -t goalga .
docker run -p 8501:8501 -v goalga-data:/data goalga          # SQLite on a volume
# or, with PostgreSQL:
docker run -p 8501:8501 -e GOALGA_DATABASE_URL="postgresql://…" goalga
```

The image runs as a non-root user and has a health check. On Azure Web App / Container Apps expose port **8501** and
enable **WebSockets** (required by Streamlit). To run the monitor: `docker run --rm -e GOALGA_DATABASE_URL=… goalga python scripts/monitor_portfolios.py`.

### Price archive (monthly refresh)

The app reads `data/prices_monthly.parquet`; nothing is downloaded while users are on the site. The workflow
[`.github/workflows/update-prices.yml`](.github/workflows/update-prices.yml) rebuilds it on the 3rd of every month (or on
demand from the **Actions** tab), refuses to replace it when fewer than 2,500 assets come back, runs a sanity check and
commits the new files — the commit redeploys the Streamlit app, and the daily monitor reads the same file. To refresh it
by hand:

```bash
pip install -r requirements-data.txt
python scripts/update_prices.py --min-assets 2500          # ≈3 minutes
```

Each refresh adds ≈4 MB to the Git history (≈50 MB a year). If that matters, squash the data commits from time to time
or publish the archive as a release asset / in object storage and download it at start-up.

### Concurrency and scaling

Every visitor gets an **isolated session** (own state, plan and results), so everyone can use the app at the same time.
What sessions share is read-only (the price archive and the universe screen, computed once per process) plus the accounts
database — and the **CPU**: one Streamlit process runs all its sessions, and a launch costs ≈ 6 CPU-seconds (three risk
previews ≈ 5 s, the search ≈ 1 s). Measured with real browsers against one process on a shared 12-core Windows machine
(the browsers ran on the same machine, so these figures are pessimistic):

| Simultaneous launches | Risk previews (median) | Search → plan (median) | Server memory |
|---|---|---|---|
| 1 | 5 s | 1 s | 210 MB |
| 4 | 10 s | 5 s | 226 MB |
| 8 | 54 s · 22 s with single-threaded BLAS | 7 s · 8 s | 252 MB |
| 16 | 74 s | 61 s | 266 MB |

Memory is not the constraint (≈ 4 MB per session); CPU is, and only bursts hurt: users who start a plan at different
moments each wait a few seconds. You can reproduce and size this for your own host with `python scripts/load_test.py 1 4 8`
(or `--url https://your-app…`). Practical advice: set `OMP_NUM_THREADS=1` (the Dockerfile does) so that concurrent
sessions do not oversubscribe the cores; the free Community Cloud tier is fine for a demo or a portfolio project; for a
real audience use a container host with ≥ 2 vCPUs and several replicas behind a load balancer with sticky sessions
(Streamlit sessions live in one process). Beyond that, move the search to a worker pool or a queue.

### Security and privacy

- **Passwords are never stored.** Only a salted **scrypt** hash (n = 2¹⁴, r = 8, p = 1, 16-byte random salt) is kept:
  hashing — not encryption — is the right tool, because nobody, including you, can get a password back. Checks are
  constant-time, unknown e-mails take as long as known ones, and five wrong attempts lock the account for 15 minutes.
- **What is stored in clear** in the database: e-mail, display name, language and the saved portfolios (plans, amounts,
  goals, weights). Protect them with a managed PostgreSQL (encryption at rest and TLS: `sslmode=require`), a dedicated
  least-privilege database user and backups. Community Cloud serves the app over HTTPS.
- **Secrets** (`GOALGA_DATABASE_URL`, SMTP) belong in the Streamlit / GitHub secret stores, never in the repository
  (`.streamlit/secrets.toml` is git-ignored). Users can delete their account and all its data from their personal space.
- **Not included**: e-mail verification, password reset, "remember me", per-IP rate limiting and application-level field
  encryption — see [Limitations](#limitations).

### Configuration reference

| Variable | Purpose |
|---|---|
| `GOALGA_DATABASE_URL` | SQLAlchemy URL of the accounts database (PostgreSQL recommended). |
| `GOALGA_DB_PATH` | SQLite file used when no URL is set (default `data/goalga.db`). |
| `GOALGA_DEFAULT_LANG` | Language when the browser does not ask for a supported one (`en` by default). |
| `GOALGA_PRICES_FILE` | Alternative price archive (tests, custom data); default `data/prices_monthly.parquet`. |
| `GOALGA_BRAND` | Name shown in the top bar (default `GoalGA`). Colours are CSS variables in `ui/assets/theme.css`. |
| `GOALGA_APP_URL` | Public URL of the app, used for the link inside alert e-mails. |
| `GOALGA_SMTP_HOST` `_PORT` `_USER` `_PASSWORD` `_FROM` `_SECURITY` | Outgoing e-mail (`starttls` · `ssl` · `none`). |
| `HTTPS_PROXY` / `HTTP_PROXY` | Only for `scripts/update_prices.py` behind a corporate proxy: the running app makes no outgoing market-data calls. |

On Streamlit Community Cloud, top-level secrets are exposed to the app as environment variables.

## Accounts and weight-change alerts

- **Create an account** (e-mail + password; passwords are stored only as salted *scrypt* hashes, with login lockout
  after repeated failures) and **save** any plan as a portfolio. The top-right button reads *Sign in or sign up* for
  guests (an icon on narrow screens) and shows your name and unread alerts once you are in.
- **Follow** a portfolio when you actually invest in it. From that day the app tracks your plan: *year 1, year 2…*
- Every portfolio keeps its **versions**. Edit a plan, re-run the search and save a new version; GoalGA tells you if the
  target weights moved.
- An **alert** is created whenever the target weight of any asset changes by at least the portfolio's tolerance
  (5 percentage points by default), for one of three reasons: the **glide path steps down** (e.g. P7 → P5 at the
  start of year 9), a **periodic review** re-ran the algorithm on fresh prices and your latest check-in
  (every 90 days by default), or you **edited the plan**.
- Alerts appear in the app (badge next to your name) and, if enabled, by **e-mail** in your language, with the old and
  new weights of every asset.
- **Check-ins** let you record the real value of your investments. A review restarts **from the day it runs**: the
  first cash flow stays at the next anniversary of your investment, so the first year is a partial one, and the starting
  wealth is the plan's expected median for that day corrected by how far your last check-in was from it (a check-in
  taken before an anniversary is not mistaken for the wealth after it; older than 400 days or from before the current
  version, it is ignored).
- **Edit** restarts from the plan that is left, not from the original one: today's estimated capital (editable), goal
  years counted from today.
- Only plans with efficient portfolios built from the price archive are re-optimised automatically (hand-edited
  weights are not); others still get the scheduled glide-path alerts. A review reuses the **pool of assets saved with the
  portfolio**, so a periodic review never reshuffles your holdings — only the weights can move.

Not included yet: e-mail verification, password reset and "remember me" cookies — see [Limitations](#limitations).

## Languages

English · Italiano · Español · Français · Русский · 中文. The language is detected from the browser (or `?lang=`),
saved with your account, and can be changed at any time from the top-right selector. All text lives in
`goalga/i18n/catalogs/<lang>.py`, so the core library, the UI, the Excel export and the e-mails share the same strings.

**Adding a language**

1. Copy `goalga/i18n/catalogs/en.py` to `<code>.py` and translate the values (keep `{placeholders}`, `[[gradient]]`
   markers, `**bold**` and `\n`).
2. Register it in `LANGS` and `LOCALE_TAGS` (`goalga/i18n/__init__.py`), add its number/currency format to `SPECS`
   (`goalga/i18n/fmt.py`) and, if it needs more than *one / other*, its plural rule in `plural_category`.
3. Run `python -m goalga.i18n.check <code>` — it verifies keys, placeholders and markup against the reference catalog,
   and the test-suite then covers the new language automatically.
4. If the script is not Latin, Cyrillic or CJK, add a font to `.streamlit/config.toml` (`[[theme.fontFaces]]` with a
   `unicodeRange`).

## Project structure

```
app.py                      Streamlit entry point
ga_model.py                 deprecated shim for the old `GoalBasedGA` API (delegates to goalga)
LICENSE · CITATION.cff      MIT licence · citation metadata (this repository and the paper)
goalga/                     calculation library — no Streamlit dependency
  problem.py  genetic.py    objective function, vectorised simulation, genetic algorithm
  scenarios.py portfolios.py market.py data.py   bootstrap, efficient frontier (caps, rules), market construction, price cleaning
  universe.py snapshot.py selection.py           catalogue of funds and stocks, monthly price archive, universe screen and seeded pool
  analytics.py plan.py demo.py                   benchmarks and out-of-sample validation, plan parameters, synthetic series for tests
  risk.py  pipeline.py      risk profiles (portfolio caps); headless optimisation, previews, serialisable specs
  trace.py                  records the real evolution for the visualisation
  accounts/                 users, portfolios, versions, alerts, check-ins (SQLAlchemy) · monitor · e-mail
  i18n/                     translation engine, locale formats, catalogs (en it es fr ru zh), catalog checker
ui/                         interface: flow, goals, inputs, risk, engine, stage, result, holdings, account, lab (+ lab_markets), charts, theme, …
  assets/                   theme.css (design system) · behaviors.js (screen fades, amount fields, year bubble) · stage.css, evolve.js (canvas animation)
static/fonts/               Inter (latin + cyrillic subsets, SIL OFL)
data/                       etf_universe.csv (40 curated ETFs) · asset_universe.parquet (≈3,500 US-listed stocks) ·
                            prices_monthly.parquet + .json (monthly EUR price archive, refreshed by a workflow)
scripts/
  update_prices.py          rebuilds the monthly price archive (run monthly by update-prices.yml)
  monitor_portfolios.py     weight-change monitor (run by the scheduled workflow)
  e2e_smoke.py              end-to-end browser test (Playwright), desktop or mobile, any language
  load_test.py              N simultaneous users through the whole flow: response times and memory per session
  make_screenshots.py       regenerates the images in docs/images
  update_ticker.py          refreshes the stock catalogue from Yahoo Finance screeners
tests/                      pytest: core, GA, data, universe, UI (AppTest), accounts, i18n, real-browser stage
docs/                       DESIGN.md (UI principles, Italian) · AUDIT.md (verification report, Italian)
.github/workflows/          ci.yml (lint + tests) · monitor.yml (scheduled alerts) · update-prices.yml (monthly archive)
```

## Testing

```bash
pip install -r requirements-dev.txt
pytest -q                        # ~3 minutes: 600+ tests (synthetic price archive, no network)
ruff check .

playwright install chromium      # once
python scripts/e2e_smoke.py                     # ~80 browser checks (starts its own server)
python scripts/e2e_smoke.py --mobile --lang fr  # same flow on a phone, in French
python scripts/make_screenshots.py              # regenerate docs/images
```

The suite checks, among other things: the paper's 4.43% minimum return, that the vectorised evaluation matches a
loop-based reference and `numpy_financial`, that the GA reaches the optimum on exhaustively solvable problems, the
paper's mutation example, absence of invented data, the universe screen (each exclusion reason, seeded and diverse
pools, CAPM returns, basket and asset-class caps), that every launch draws a new seed while a fixed seed reproduces the
result, that user inputs (including millions typed in words, in six languages) survive the whole flow, that the recorded
evolution is faithful, that every translation catalog matches the reference, account security and alert logic (including
how a check-in is rolled to a review date, plans restarting mid-year and editing from the plan that is left), that no
position is smaller than the minimum, that the compound return matches a lognormal Monte Carlo, that the animated scene
runs in a real browser — and that this README's links, images, anchors and paper reference still resolve
(`tests/test_docs.py`).

## Data

Prices come from **Yahoo Finance** through [`yfinance`](https://github.com/ranaroussi/yfinance), but only at build time:
`scripts/update_prices.py` downloads monthly adjusted prices for every investable asset of the catalogue (the 40 curated
ETFs and ~2,800 ordinary stocks), converts the dollar ones to euro with the month-end EUR/USD rate and writes
`data/prices_monthly.parquet` (≈4 MB). The running app only reads that file, so it needs no network, has no rate limits
and is reproducible. The catalogue itself (`data/etf_universe.csv`, `data/asset_universe.parquet`) lists 40 ETFs with
long-term return assumptions and ~3,400 US-listed stocks with sector and industry (`scripts/update_ticker.py` refreshes
the stock list).

> [!WARNING]
> **Licence of the data.** The MIT licence covers the code, not the price archive. Yahoo Finance data, as accessed by
> `yfinance`, is intended for personal / research use, and redistributing a derived archive in a public repository is a
> grey area. For a **commercial** service replace the downloader in `goalga/snapshot.py` (`download_monthly` takes any
> `(tickers, start) -> prices` function) with a licensed market-data provider and keep the archive private. Nothing else in
> the project depends on the provider.

## Limitations

- GoalGA is a decision-support tool and **not financial advice**. Results depend on historical data and return
  assumptions — past performance does not guarantee future results. Before it is used with real clients it needs the
  validation and regulatory review any advisory tool needs; the numerical checks done so far are in
  [`docs/AUDIT.md`](docs/AUDIT.md) (*Verification for real-money use*).
- All prices are in euro; dollar-listed assets include the EUR/USD move *unhedged*. **Costs, fees, taxes** and liquidity
  constraints are not modelled. Goals are in today's euros and indexed by 2% a year by default.
- The historical window is the common history of the pool's assets, about **11–12 years** (no 2008), and the tails rest
  on a handful of episodes (12/2018, 03–04/2020, 2022): removing 2022 moves the success probability of the same plan
  from 90.5% to 94.6%. The confidence interval measures sampling noise, not model uncertainty. Two runs with different
  seeds differ by 1–2 percentage points on a medium-difficulty plan.
- The stock universe comes from current Yahoo Finance screeners and is therefore subject to *survivorship bias*, and the
  history is monthly (20 years at most, 14 used).
- The stock basket is a seeded **sample** of the universe, not a recommendation to buy those stocks; its minimum share
  of the equity exposure (30%) is a design choice you can change in the advanced area. US-listed ETFs and stocks may not
  be available to every European retail investor (PRIIPs/KID rules): the 18 UCITS ETFs of the catalogue are.
- Accounts are intentionally simple: no e-mail verification, no password reset, no "remember me" cookie, and the e-mail,
  name and portfolios are stored unencrypted at application level (passwords are hashed; use an encrypted managed
  database). Add what you need — or an identity provider — before exposing the app to the public.
- On Streamlit Community Cloud the default SQLite file is not persistent — use `GOALGA_DATABASE_URL`.
- Preview numbers on the risk cards are estimates from a shorter search; the plan page shows the verified result.

## Credits and license

- **Model**: Pomante, Farina & Cucurachi (2024) — see [The paper](#the-paper) for the full reference and how to cite it.
- **Code**: released under the [MIT License](LICENSE). The licence covers the source code only: the Inter font keeps its
  own (SIL Open Font License, [`static/fonts/OFL.txt`](static/fonts/OFL.txt)) and the price archive in `data/` follows the
  terms of its data provider (see [Data](#data)).
- **Built with** [Streamlit](https://streamlit.io), [Plotly](https://plotly.com), [pandas](https://pandas.pydata.org),
  [SciPy](https://scipy.org), [SQLAlchemy](https://www.sqlalchemy.org) and [yfinance](https://github.com/ranaroussi/yfinance)
  (price archive builder); typeset in [Inter](https://rsms.me/inter/).

## Contributing

Issues and pull requests are welcome. Before opening one, run `ruff check .` and `pytest -q` — the CI does the same on
Python 3.11 and 3.12 — and, for changes to the interface, `python scripts/e2e_smoke.py` (see [Testing](#testing)). The design
principles are in [`docs/DESIGN.md`](docs/DESIGN.md); new texts go in every catalog of `goalga/i18n/catalogs/` (see
[Languages](#languages)).

> Also available in Italian: [`README.it.md`](README.it.md).
