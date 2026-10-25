# Design dell'interfaccia

Note per chi mantiene o rimarca l'applicazione. L'obiettivo: **minimale, guidata, viva** — un *robo-advisor* in cui
l'algoritmo genetico non è nascosto dietro un pulsante ma si osserva mentre prende forma.

## Principi

1. **Una domanda per schermata.** Pochi input, anche visivi: importi scritti liberamente, linea del tempo degli
   obiettivi, tre carte per il rischio con 100 puntini ciascuna. Niente sidebar, niente pannelli di controlli.
2. **Pilota automatico, con una porta aperta.** Mercati, rendimenti attesi e parametri dell'algoritmo sono scelti
   dall'app. Il riepilogo lo dice (*«Al resto penso io»*) e, sotto, mette **a tutta larghezza e con lo stesso peso**
   del pulsante principale il pulsante **«Usa impostazioni avanzate»** (niente interruttori né link piccoli). La
   configurazione avanzata è **guidata**: cinque passi, ognuno con una spiegazione («a cosa serve», «cosa puoi
   cambiare») invece di una parete di controlli. «Indietro» tiene le modifiche (e la conferma dice quali passi sono
   cambiati); «Torna alle scelte automatiche» azzera tutto **e riporta alla schermata di partenza**.
3. **L'algoritmo è l'eroe.** La schermata «Evoluzione» riproduce la ricerca reale: strategie come filamenti luminosi, il
   «DNA» del campione, contatori che salgono, didascalie che cambiano («Simulazioni lanciate» → «Sto generando i
   percorsi» → … → «Scelgo il percorso ottimale»). Mai un'animazione scollegata dai dati. **Non si salta e non si
   rivede**: finita l'animazione è finita (chi torna indietro viene portato direttamente al piano).
4. **Onestà prima dell'effetto.** Si mostra la probabilità *verificata su scenari nuovi*, mai «100 su 100» se un solo
   scenario fallisce; i piani impossibili vengono spiegati (rendimento necessario contro rendimenti attesi); le cifre
   della scelta del rischio sono dichiarate **stime** («≈») perché frutto di una ricerca più breve; **ogni avvio usa un
   seed nuovo** (stesso piano e stesso profilo → un altro campione dell'universo), salvo seed fisso scelto a mano.
5. **Degradare con grazia.** Senza JavaScript esteso, senza font, con *riduci animazioni* o con versioni di Streamlit
   senza `st.iframe`, l'app resta utilizzabile (i contatori della home mostrano comunque i valori finali).
6. **Una lingua per volta, tutta la lingua.** Ogni testo — interfaccia, grafici, errori, Excel, email — passa dal
   catalogo `goalga/i18n/catalogs/<lingua>.py`; numeri, valute e plurali seguono la lingua (vedi sotto).

## Flusso

```
home → 1 punto di partenza → 2 obiettivi → 3 rischio → 4 conferma → 5 evoluzione → 6 piano → composizione nel tempo
                                                          ↘ configurazione avanzata (da 4 e da 6) ↗
                                           account: accesso · salvataggio (da 6) · spazio personale · avvisi
```

Ogni accesso dalla home inizia **sempre un piano nuovo** (importi a zero, nessun obiettivo, profilo equilibrato).

Lo stato vive in `st.session_state` (`ui/state.py`): i valori canonici (`w0`, `contribution`, `goals`, `risk`) sono
separati dai widget, che ripartono dai valori canonici a ogni schermata; le impostazioni avanzate sono «fissate» a ogni
esecuzione (`init_state` → `pin`) perché Streamlit scarta lo stato dei widget non mostrati. `state.setting(chiave)`
restituisce il valore avanzato solo se le impostazioni avanzate sono attive (`use_advanced`: si accende aprendo l'area
avanzata e si spegne con «Torna alle scelte automatiche» o uscendo senza modifiche), altrimenti l'automatico.

### Importi e obiettivi (`ui/inputs.py`, `ui/goals.py`)

- Gli importi si scrivono come si vuole (`ui.inputs.parse_amount`): con o senza separatori (`20000`, `20.000`, `1,250,000`,
  `€ 1.250,50`), con abbreviazioni e parole nelle sei lingue (`20k`, `1,5M`, `2 milioni`, `un millón`, `2 million`,
  `2 млн`, `100万`, `3 mld`, `2 mil millones`), con la valuta e il «di» (`3 mln di euro`). Regola dei separatori: l'ultimo
  è il decimale solo se lo seguono una o due cifre, altrimenti raggruppa le migliaia **anche con gruppi irregolari**:
  aggiungere uno zero a «250.000» dà «250.0000», cioè 2,5 milioni (prima veniva letto come 250 euro). «mil» vale mille
  solo in spagnolo; oltre 10¹² o testo non riconosciuto → rifiutato (`input.bad_amount`, anche nelle schede degli obiettivi).
  `format_amount` e `parse_amount` si invertono in tutte le lingue fino a 12 milioni.
- Ogni obiettivo ha **un solo cursore** (chiave `gw_<id>`) che sceglie un **anno di calendario** (2027–2086: da 1 a 60 anni da
  oggi); il piano continua a contare gli anni da oggi (`goal["start"]`, `goal["end"]`). L'interruttore **«Si ripete ogni anno»**
  (`gm_<id>`) lo sostituisce con l'intervallo (`gy_<id>`, subito di cinque anni) e `_keep_range` impedisce che le due estremità
  si sovrappongano (sovrapposte, quella in cima non si sposta indietro e l'altra non si raggiunge più). Perché in anni di
  calendario: il numero che segue il dito mentre si trascina (l'etichetta nativa del cursore) è già «l'anno», senza conti.
  Sopra il cursore compare un fumetto con **l'anno in grande** e «tra 36 anni» sotto, e l'intestazione della scheda si
  aggiorna nel browser («Tra 36 anni · 2062») senza aspettare il rilascio. Le frasi, plurali compresi, le prepara il server
  (`goals.live_texts`, nel segnaposto `data-gx-live` della sola pagina degli obiettivi) e sono le stesse che scrive dopo il
  rilascio: lo script non conosce lingue né regole dei plurali (test e controllo nel browser ne verificano l'identità).

### Rischio: «quanto rischio sei disposto ad assumere?»

Il profilo non cambia l'obiettivo dell'algoritmo: **limita lo spazio di ricerca** (`goalga/risk.py`). *Prudente* può usare
i portafogli P1–P3, *Equilibrato* P1–P6, *Dinamico* P1–P9; l'algoritmo trova il percorso migliore dentro il limite. Gli
scenari di un profilo sono un **prefisso** di quelli completi (stesse estrazioni, solo le prime colonne), e l'anteprima è
un prefisso della ricerca completa a parità di seed: il risultato finale non può peggiorare ciò che l'anteprima ha
trovato. Le carte mostrano la probabilità («su 100»), la quota azionaria massima e l'«anno sfavorevole» (5° percentile
del rendimento annuo del portafoglio più aggressivo consentito) e una frase che legge i numeri («anche il profilo
Prudente supera la soglia: più rischio non è necessario»).

### Configurazione avanzata guidata (`ui/lab.py`, `ui/lab_markets.py`)

Cinque passi in una barra segmentata (più la scheda *Metodo*), ciascuno aperto da un riquadro (`components.guide`) e
chiuso da «Indietro / Avanti»; sopra, una striscia mostra **quali passi si discostano dalle scelte automatiche**
(`lab.changed_groups`) e «Ripristina» torna al pilota automatico.

| Passo | Cosa decide l'utente | Cosa fa l'app |
|---|---|---|
| **1 · Universo** | categorie di fondi e settori (con il numero di asset idonei), quante azioni, storico minimo, esclusioni, oppure una lista scelta a mano | l'**imbuto** *valutati → idonei → usati*, i motivi di esclusione e l'esplorazione degli asset per categoria |
| **2 · Rendimenti** | fonte (lungo periodo / storico), un cursore di ottimismo (−2…+2 punti), ritocchi per classe | mostra l'intervallo dei rendimenti attesi dei 9 portafogli e avvisa su valori estremi |
| **3 · Portafogli** | diversificazione (tetto per asset e per classe), opzioni per esperti (shrinkage, bootstrap) | frontiera efficiente e composizione per categoria; con asset scelti a mano si possono scrivere i pesi dei 9 portafogli (*plug-and-play*) |
| **4 · Ricerca** | livello di impegno (rapido/standard/approfondito), parametri del piano, seed fisso, parametri dell'algoritmo | spiega ogni parametro nei popup d'aiuto (mai con il prefisso «Paper:»: il lavoro è citato nella scheda Metodo e nel README) |
| **5 · Verifiche** | — | analisi completa dell'ultimo risultato (KPI, proiezioni, rischio, benchmark, convergenza, robustezza) |

Non ci sono più file da caricare né dati sintetici, e il fornitore dei prezzi non compare nell'interfaccia: i prezzi sono
quelli dell'archivio mensile (`goalga/snapshot.py`).

### Universo, seed e avvii (`ui/state.py`, `goalga/selection.py`)

- L'algoritmo **valuta tutto il catalogo** a ogni avvio (`screen_universe`, con cache) ed estrae un **pool** dal seed
  (`draw_pool`): tutti i fondi idonei più alcune azioni per settore, con probabilità crescente col rischio remunerato (CAPM).
  Le azioni entrano nella frontiera come **una cesta** a pesi uguali con quota minima dell'esposizione azionaria
  (`market.Basket`): lasciato libero, l'ottimizzatore media-varianza concentra le azioni su 3-5 nomi (sull'archivio
  reale fino al 100% in tre titoli nel portafoglio più aggressivo) sfruttando il rumore delle stime; la cesta le tiene
  diversificate. Ogni asset class ha un tetto complessivo (altrimenti due ETF simili aggirerebbero il tetto per asset).
- `pending_seed()` è il seed del **prossimo avvio**: le anteprime del rischio lo usano (la ricerca breve è un prefisso della
  completa), poi `begin_launch()` lo consuma entrando in «Evoluzione» e ne estrae uno nuovo. La firma del risultato include
  il seed: un nuovo avvio ricalcola, lo stesso seed fisso ripropone il risultato in cache. I pulsanti «E con un altro
  livello di rischio?» riusano il seed del risultato (`keep_seed`), così cambia solo il rischio.
- Un portafoglio salvato porta con sé seed e **pool esplicito** di ticker: il monitor non rimescola gli asset, e il primo
  avvio dopo «modifica» riusa lo stesso pool (`pool_pin`); dal secondo avvio si estrae di nuovo.

### Pagina del piano e composizione

- **Perché questa strategia** usa colonne separate (etichetta · barra · valore) per ogni riga: con strategie sotto soglia
  le etichette non si sovrappongono più alle barre (test: `test_the_comparison_keeps_labels_values_and_bars_in_separate_columns`
  e il controllo geometrico di `scripts/e2e_smoke.py`).
- **«Di quali asset è fatto il tuo portafoglio?»** è un collegamento ben visibile nella pagina del piano. La pagina
  *Composizione* mostra per ogni anno ticker, nome e peso **raggruppati per categoria** (ciambella in CSS puro + elenco; le
  azioni singole hanno il loro gruppo e righe compatte), le fasi del glide path, il prossimo cambio e una mappa di calore
  anno × asset (le azioni sono una sola colonna; il dettaglio titolo per titolo è nell'elenco e nel CSV); i colori sono per
  categoria e sono gli stessi ovunque (`_palette`).

### Account e avvisi

- Registrazione/accesso (`ui/account.py`): email + password; hash *scrypt* con sale, blocco temporaneo dopo 5 tentativi
  falliti, errori identici per email inesistente e password errata. Non ci sono (ancora) verifica email, recupero password
  né cookie «ricordami».
- Un portafoglio salvato ha **versioni** (creata, modificata, rivista dal monitor), un inizio dell'investimento e un
  riferimento dei pesi già comunicati. **Seguire** il portafoglio attiva gli avvisi.
- `goalga/accounts/monitor.py` crea un avviso quando lo scostamento massimo dei pesi di un asset raggiunge la soglia
  (5 punti percentuali di default) per: passaggio previsto del glide path, revisione periodica (rilancia l'algoritmo
  con prezzi aggiornati, ogni 90 giorni) o modifica del piano. `scripts/monitor_portfolios.py`
  (workflow `monitor.yml`) lo esegue a intervalli regolari e invia le email (SMTP) nella lingua dell'utente.
- **Il tempo del piano.** Ogni versione ha un'origine (il giorno della revisione o della modifica), un `anchor` (anni
  interi dall'inizio dell'investimento) e un **primo anno parziale** (`first_period`): i flussi restano sugli anniversari
  dell'investimento, quindi il primo arriva tra `1 − frazione` anni. Il patrimonio di partenza di una revisione è la
  mediana prevista dalla versione per quel giorno (interpolata tra due anniversari come patrimonio *prima* dei flussi del
  successivo) più lo scarto dell'ultimo valore registrato dopo l'inizio della versione: i flussi tra le due date sono già
  nella mediana. «Modifica» riparte da questo stesso piano residuo e non può produrre un nuovo portafoglio dal piano
  parziale (si aggiorna quello esistente).
- L'archivio è SQLAlchemy Core: SQLite in locale, PostgreSQL in produzione (`GOALGA_DATABASE_URL`).

## Internazionalizzazione

`goalga/i18n` è indipendente da Streamlit: `t("chiave", n=…)` restituisce il testo nella lingua attiva (ripiego: inglese,
poi italiano), `tn` sceglie la forma plurale (`.one/.few/.many/.other`, il russo ne ha quattro), `fmt` formatta numeri,
importi e percentuali (separatori, spazi non separabili, `万/亿` in cinese). I messaggi d'errore sono `Msg`/`LocalizedError`:
conservano chiave e parametri e si possono riprodurre in un'altra lingua (le email partono nella lingua dell'utente).

- La lingua della sessione si sceglie con `?lang=`, poi la lingua del browser, poi `GOALGA_DEFAULT_LANG`; il selettore è
  in alto a destra e la scelta viene salvata nell'account.
- `python -m goalga.i18n.check [lingua]` confronta ogni catalogo con quello italiano (chiavi, segnaposto `{x}`, modelli
  Plotly `%{…}`, tag `[[ ]]` e `**`, forme plurali); la suite lo esegue per tutte le lingue.
- **I callback dei widget girano prima dello script**, quando la lingua della sessione non è ancora stata attivata: per
  questo `i18n.set_resolver` legge la lingua da `st.session_state` (altrimenti un importo riscritto in un callback uscirebbe
  sempre nel formato predefinito).
- Font: Inter (latino + cirillico, OFL) con `unicodeRange` in `.streamlit/config.toml`; per il cinese si usano i font di
  sistema (`theme.py`, `FONT`).
- Le colonne dei DataFrame restano in italiano come chiavi interne; l'etichetta mostrata è sempre `t(...)`.

## Sistema visivo (`ui/assets/theme.css`)

| Elemento | Scelta |
|---|---|
| Tema | Scuro, forzato (`[theme] base = "dark"`), sfumature ambientali diverse per schermata (`ui/theme.py`) |
| Tipografia | **Inter** variabile (OFL, in `static/fonts`), numeri tabulari, titoli con tracking stretto |
| Colore | Grigi freddi + gradiente d'accento teal → indaco → rosa; scala del rischio teal → arancio (9 livelli) |
| Forme | Pillole per le azioni, carte di vetro (`backdrop-filter`) con raggio 24–32 px, una sola azione primaria per schermata |
| Movimento | Ingresso `gx-rise`, dissolvenza della home (`gx-fade`), contatori che salgono, puntini in cascata, anello animato (`@property --p`), **dissolvenza tra schermate** (`gx-leaving`/`gx-swapped`) e **fumetto degli anni** sugli slider degli obiettivi |
| Responsive | Una colonna sotto i 640 px; la barra in alto riduce lingua e account a icone (sotto 860 px) e tra 860 e 1120 px lascia alla barra di avanzamento lo spazio che resta accanto a «Accedi o registrati» |

Variabili principali: `--bg`, `--ink`, `--mute`, `--a1…--a6`, `--grad`, `--radius`, `--maxw` (larghezza per schermata).
Il marchio si cambia con `GOALGA_BRAND`.

### Vincoli tecnici da conoscere

- `st.html` passa il contenuto a **DOMPurify**: un `<` dentro un foglio di stile (anche in una stringa CSS come
  `"<number>"`) fa scartare l'intero `<style>`. Vale anche per gli **script**: un `<script>` il cui testo contiene `<`
  seguito da lettera, cifra o `/` (es. `i<n`, `p<1`) viene rimosso in silenzio. Si scrive `n>i`; i test
  (`test_theme_css_survives_the_html_sanitizer`, `test_inline_scripts_survive_the_html_sanitizer`,
  `test_behaviors_script_survives_the_html_sanitizer_and_is_well_formed`) lo impediscono.
- `st.html` rimuove `<svg>`; per SVG si usa `st.markdown(..., unsafe_allow_html=True)` oppure forme CSS (linea del tempo,
  anello, puntini e ciambella della composizione sono CSS puro).
- Le personalizzazioni di Streamlit usano `data-testid` e classi `st-key-*` (contenitori con `key=`); i selettori con
  prefisso (`[class*="st-key-pfcard-"]`) valgono anche per i pulsanti con lo stesso prefisso: per questo i nomi
  distinguono contenitore e pulsante (`rk-<profilo>` / `rk-btn-<profilo>`, `pfcard-<id>` / `pf-*`).
- Un pulsante con `help=` genera un secondo `<button>` nascosto (di misura zero): nei test del browser si usa `:visible`.
- Versioni testate: Streamlit 1.63 e 1.66 (anche i controlli nel browser, 85 su 85, in un ambiente pulito con la 1.66.1);
  `requirements.txt` limita la versione a `<1.67` perché l'interfaccia personalizza elementi interni di Streamlit: si alza il
  limite solo dopo aver eseguito `scripts/e2e_smoke.py` sulla nuova versione.
- Streamlit conserva lo scorrimento tra una schermata e l'altra: `theme.scroll_top` lo riporta in alto con un piccolo
  script (`st.html(..., unsafe_allow_javascript=True)`, ignorato se non supportato).
- **Comportamenti nel browser** (`ui/assets/behaviors.js`, inserito da `theme.inject` nello stesso `st.html` che imposta la
  lingua; l'elenco dei pulsanti di navigazione è `theme.NAV_KEYS`). Lo script è **versionato**: `window.__gx` tiene
  l'impronta del testo (`__VERSION__`, sostituita da `theme.behaviors`) e un `off()` che smonta tutti i listener (passano da
  `on()`/`watch()`); riesecuzioni con lo stesso testo (cambio di lingua) non fanno nulla, con un testo diverso (app aggiornata
  mentre la scheda è aperta) quello vecchio si disattiva e il nuovo lo sostituisce, senza dover ricaricare la pagina:
  1. *Cambio schermata.* Al clic su un pulsante di navigazione la pagina sfuma subito (`html.gx-leaving`, solo gli
     elementi del contenuto: barra in alto e controlli restano), senza aspettare il server. Appena arriva la nuova schermata
     (il segnaposto `[data-scroll]` cambia) e sono passati almeno 130 ms, la classe si toglie e gli elementi nuovi compaiono
     con la propria animazione. Gli elementi della schermata precedente che Streamlit marca `data-stale="true"` e rimuove
     solo a fine esecuzione restano nascosti (`html.gx-swapped`) finché lo script non termina: senza questo ricomparirebbero
     per un attimo sotto la nuova pagina. Limiti di tempo (4 s, 180 s nella seconda fase) tolgono comunque le classi;
     con `prefers-reduced-motion` non fa nulla. Si usano pochi fatti stabili del front-end: `data-test-script-state` su
     `stApp` e il marcatore di schermata; se mancano, resta solo il limite di tempo.
  2. *Importi.* Entrando in un campo (`st-key-amt-*`, `st-key-gamt-*`) il valore si seleziona tutto; dopo un invio lo si
     riseleziona quando Streamlit ha riscritto il testo formattato; un clic dentro il campo già attivo sposta il cursore.
  3. *Fumetto e intestazione degli obiettivi.* Il numero grande del fumetto è l'etichetta del cursore (l'anno, che Streamlit
     aggiorna mentre si trascina). Lo script aggiunge `data-cap` (la didascalia «tra 36 anni», da `data-gx-live`) e
     `data-edge` (vicino ai bordi, per non uscire dallo schermo sui telefoni) e riscrive `.gx-goal-sub` con la frase
     corrispondente; il resto è CSS (`[data-dragging="true"]` sul cursore di react-aria).
- Il tempo di «Torna alle scelte automatiche» era soprattutto la ricostruzione del mercato automatico: `market_tab.market_for`
  tiene in `ss["market_cache"]` il mercato automatico del seed corrente e gli ultimi 4 personalizzati (chiave = firma di
  scelte, seed e archivio), quindi dopo aver provato impostazioni avanzate si torna alla conferma in pochi centesimi di secondo.
- **AppTest** valuta i `format_func` dei widget nel thread del test: nei test che cambiano lingua a metà, la lingua del
  thread deve coincidere con quella con cui la pagina è stata disegnata (`GOALGA_DEFAULT_LANG` o `i18n.use`).

## La scena dell'evoluzione

```
run_ga(callback=EvolutionTrace)  →  trace.payload()  →  stage.stage_html()  →  iframe (evolve.js)
 popolazione e campione per        fotogrammi scelti       pagina autonoma        canvas 2D + statistiche
 ogni generazione                  (fitti all'inizio),     senza risorse           in tempo reale
                                   80 individui, base64    esterne
```

- **`goalga/trace.py`** registra popolazione ordinata e miglior individuo di ogni generazione e ne produce una versione
  compatta (≤ 100 fotogrammi, ≤ 80 individui, byte in base64, ~0,5 MB al massimo).
- **`ui/assets/evolve.js`** disegna ogni individuo come una scala di livelli di rischio, con mescolanza additiva
  (più strategie sovrapposte → più luce), *scie* delle posizioni precedenti, il campione con alone, onde sui geni che
  mutano e una striscia di «DNA» colorata. Il ritmo della riproduzione dà più tempo dove la popolazione cambia di più. Con
  un profilo prudente o equilibrato una linea tratteggiata mostra il **limite di rischio**. Le didascalie cambiano per fasi
  e le etichette dell'asse usano la forma plurale giusta (`yearLabels`, calcolate in Python).
- La stessa pagina in modalità `ambient` anima la home con un mini algoritmo genetico simulato (decorativo).
- Test: payload (`tests/test_trace.py`), pagina e browser (`tests/test_ui_helpers.py`, `scripts/e2e_smoke.py`).

## Accessibilità

Anello e linea del tempo hanno `role="img"` e `aria-label`; i puntini e la ciambella sono decorativi (`aria-hidden`); la
narrazione dell'animazione è in una regione `aria-live`; con `prefers-reduced-motion` la scena mostra subito il risultato e
i contatori i valori finali; la lingua della pagina è dichiarata in `<html lang>`; tutti i controlli restano widget nativi
di Streamlit (tastiera, focus, schermi piccoli).
