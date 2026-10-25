# Rapporto di verifica dell'applicazione

**Oggetto**: dashboard *Goal-Based Asset Allocation* (`app.py`, `ga_model.py`, `update_ticker.py`) rispetto al paper
*A "Plug-and-Play," Goal-Based, Dynamic Asset Allocation Model with Genetic Algorithms* (U. Pomante, V. Farina,
P. A. Cucurachi, *The Journal of Wealth Management*, 26(4), 33–48, Spring 2024,
[doi:10.3905/jwm.2024.1.227](https://doi.org/10.3905/jwm.2024.1.227)).
**Metodo**: lettura integrale del paper, revisione del codice, esperimenti riproducibili sul codice originale (conservato
fuori da questo repository) e riscrittura con test automatici.

## Esito

L'applicazione **non era né coerente con il paper né logicamente corretta**. La struttura del modello (funzione
obiettivo, codifica, scelta del torneo/crossover) era corretta, ma:

1. **i parametri inseriti dall'utente non arrivavano al modello**;
2. gli operatori genetici più importanti si discostavano dal paper (mutazione, popolazione iniziale, terminazione);
3. la pipeline dati **inventava** rendimenti e usava ~10 osservazioni annuali;
4. l'ottimizzazione richiedeva **~15 minuti** (il paper: ~10 secondi).

La nuova versione corregge tutti i punti, riproduce i numeri del paper e aggiunge verifiche automatiche (167 test).

> **Aggiornamento (interfaccia).** Dopo la prima riscrittura l'interfaccia è stata ridisegnata come percorso guidato
> (vedi [DESIGN.md](DESIGN.md)). Il nucleo di calcolo (`goalga/`) non è cambiato, salvo la registrazione opzionale della
> popolazione per generazione usata dalla scena animata; le verifiche della sezione «Verifiche sulla nuova versione»
> sono state ripetute sulla nuova interfaccia, anche in un ambiente pulito con le librerie più recenti.

> **Aggiornamento (universo completo e seed).** La modalità automatica usava sempre gli stessi 10 ETF e, a parità di
> obiettivi e rischio, riproponeva il piano in cache. Ora ogni avvio valuta **tutti** gli asset del catalogo, estrae un
> pool diversificato da un seed nuovo e ricalcola; i prezzi vengono da un archivio mensile in euro e non più da scarichi
> durante l'uso. Vedi «Difetti trovati con l'universo completo» più sotto.

> **Aggiornamento (denaro reale).** Verifica indipendente dei calcoli per l'uso con denaro vero: il nucleo matematico è
> risultato corretto; sono stati corretti i difetti nel modo in cui il piano viene **seguito nel tempo** (valori
> registrati, revisioni a metà anno, modifica), nei confronti presentati all'utente (rendimento composto, scenari
> nuovi) e in alcune scelte di modello (inflazione, posizioni minime, finestra storica). Vedi «Verifica per l'uso con
> denaro reale».

## Difetti riscontrati e correzioni

Severità: **C** critico (risultati errati), **A** alto (si discosta dal paper / distorce i risultati), **M** medio, **B** basso.

| # | Sev. | Area | Difetto | Evidenza | Correzione |
|---|---|---|---|---|---|
| 1 | **C** | UI/stato | Gli input dello Step 1 (capitale, versamento, orizzonte) **si perdevano**: Streamlit elimina lo stato dei widget non renderizzati e il codice li reinizializzava ai default. Il GA riceveva sempre 160.000 € / 10.000 € / 30 anni. | Con `AppTest`: utente imposta 250.000 € / 20.000 € / 20 anni → il GA riceve `160000 / 10000 / 30`. Anche il testo dello Step 2 mostrava "30 anni". | Valori canonici in `session_state` separati dai widget (che ripartono da essi a ogni schermata) e impostazioni avanzate «fissate» a ogni esecuzione; test di regressione `test_user_inputs_reach_the_model_and_survive_navigation`. |
| 2 | **C** | Obiettivi | Più obiettivi **nello stesso anno** venivano sovrascritti (`{anno: importo}` da dict comprehension); obiettivi oltre l'orizzonte scartati **in silenzio**; era possibile procedere **senza obiettivi** (problema degenere: `Pr = 100%`). | `{10: 30.000, 10: 20.000}` → il GA riceve `{10: 20.000}`. | Obiettivi sommati per anno; validazione esplicita con messaggi; almeno un obiettivo obbligatorio. |
| 3 | **C** | Dati | `bfill()` e `fillna(0)` **fabbricavano rendimenti nulli** per gli anni in cui l'asset non esisteva; l'ultimo anno (parziale) contava come anno intero; media/covarianza da ~10 osservazioni annuali. | Asset quotato da 5 anni su 10: **4 anni con rendimento esattamente 0,000**; correlazione stimata 0,376 contro 0,129 reale (serie sintetiche con storico noto). Ultima osservazione datata 31/12/2026 con dati al 23/10/2026. | Rendimenti **mensili** sulla finestra comune, mai dati inventati, mese incompleto escluso, asset con storico insufficiente esclusi con motivo; centinaia di osservazioni (finestre mobili di 12 mesi). |
| 4 | **A** | GA | **Mutazione**: la riparazione "a spianamento in avanti" annullava ogni mutazione al rialzo; l'esempio del paper (pag. 40) dava il risultato sbagliato; la mutazione trascinava verso il basso tutta la coda. | Paper: `8 8 7 7 7 3 2 1` con 5° gene +1 → `8 8 8 8 8 3 2 1`; originale → invariato. Su ~6.000 mutazioni effettive: 10% al rialzo, 36% al ribasso, 54% senza effetto (anche il passo 0 era ammesso). | Riparazione a modifiche minime come nel paper (si alzano i geni precedenti o si abbassano i successivi); passo mai nullo; test sull'esempio del paper. |
| 5 | **A** | GA | **Popolazione iniziale** senza diversità: 100% degli individui partiva da P8–P9 e finiva a P1–P2 (nessuno con rischio medio ≤3 o ≥7). Il paper (nota 8) richiede intervalli di variazione diversi. | Statistica su 2.000 individui, T=50. | Ogni individuo ha il proprio intervallo [min, max] (metà a gradini). |
| 6 | **A** | GA | **Terminazione**: numero fisso di generazioni (250); il paper si ferma dopo 200 generazioni senza miglioramenti. | Codice. | Criterio `patience` (200 predefinito) + tetto massimo. |
| 7 | **A** | Portafogli | I 9 portafogli erano estratti da **10.000 pesi casuali** divisi in 9 fasce di volatilità: con molti asset i pesi casuali si concentrano sul portafoglio equipesato (fascia di volatilità ristrettissima, frontiera non raggiunta); fasce vuote duplicavano il portafoglio precedente. | 30 asset: volatilità 1,2–3,2%, miglior rendimento casuale 10,5% contro 15,0% del miglior asset; 200 asset: 8,4% contro 18,4% (universo sintetico). | Frontiera efficiente media-varianza con vincoli (SLSQP), covarianza con shrinkage di Ledoit-Wolf, 9 portafogli equispaziati in volatilità, pesi massimi per asset. |
| 8 | **A** | Rendimenti | Nessuna **normalizzazione sui rendimenti attesi** (paper, sez. I): si usavano medie storiche campionarie. | Esempio con NVDA: portafoglio P9 con +68% annuo atteso. | Ricentratura delle distribuzioni su ipotesi di lungo periodo / storici / personalizzati (tabella modificabile) e avviso per rendimenti > 20%. |
| 9 | **A** | Prestazioni | Valutazione a cicli Python: 24 ms per individuo (T=30) → pop. 150 × 250 generazioni ≈ **15 minuti** per ottimizzazione, oltre a ~750.000 chiamate a `npf.irr`. | Misura diretta. | Valutazione vettorizzata sull'intera popolazione (7 ms per 100 individui) e IRR esatto per inversione di `V(r)`: ottimizzazione in 0,2–2 s. |
| 10 | **M** | Riproducibilità | Nessun seed: `random` e `np.random` globali, risultati diversi a ogni lancio (e non sicuri con più utenti). | Codice. | `numpy.random.Generator` con seed esplicito e riproducibile. |
| 11 | **M** | Validazione | Nessuna verifica fuori campione: il GA ottimizza su 1.000 scenari e sovrastima la probabilità di successo ("maledizione del vincitore"). | Errore standard della probabilità a 95%: ±0,7 pp. | Rivalutazione su 10.000 scenari nuovi con intervallo di Wilson; test di robustezza su lanci indipendenti (Exhibit 9–10). |
| 12 | **M** | Output | La pagina dei risultati mostrava solo livelli "1–9" **senza dire cosa fossero** i portafogli; nessuna composizione, proiezione del patrimonio, analisi per obiettivo o confronto con alternative. | UI. | Composizione dei portafogli e nel tempo, fasi operative, fan chart, probabilità per obiettivo, coda, confronto con strategie alternative (Exhibit 11), export. |
| 13 | **M** | UI | API **deprecate e già scadute** (`use_container_width` dal 31/12/2025, `components.html` dal 01/06/2026); le "card" CSS non racchiudevano i widget (barre nere vuote, tema scuro hard-coded su tema chiaro); script JS di scroll fragile. | Avvisi di Streamlit 1.63; screenshot. | API correnti e tema in `config.toml`; JavaScript limitato alla scena animata (iframe isolato, senza risorse esterne) e al ritorno in cima alla pagina, con ripiego se non supportati. |
| 14 | **M** | UI | Selezione "tutti i 958 asset" di una categoria senza limiti (download e covarianza ingestibili). | Codice. | Massimo 40 asset, con avviso. |
| 15 | **M** | Dati | `yf.download(...)['Close']` dipende dalla versione di yfinance (prezzi aggiustati o no); nessun retry né gestione degli errori; nessun fallback offline. | Codice. | Archivio mensile dei prezzi aggiustati, in euro (`goalga/snapshot.py`), costruito da uno script con retry, secondo giro per i ticker mancanti e scrittura atomica; l'app non scarica nulla mentre è in uso; motivi di esclusione per ogni asset. |
| 16 | **B** | GA | Torneo con due individui **distinti** (paper: estrazione con reinserimento); figli non validi sostituiti da un genitore (paper: scartati); `n_worst = int(S·α)` può dare 0 o errori di arrotondamento; fallback IRR = −100% su `NaN`. | Codice. | Torneo con reinserimento, figli scartati e popolazione rifornita, `max(1, round(S·α))`, IRR esatto senza `NaN`. |
| 17 | **B** | Flussi | Il versamento anche a fine ultimo anno dà un rendimento minimo di 4,414% contro il 4,43% del paper (4,427% senza l'ultimo versamento). | Calcolo con le tre convenzioni. | Convenzione del paper come predefinita (parametro "anni finali senza versamenti"). |
| 18 | **B** | `update_ticker.py` | Percorso assoluto di un altro utente (`C:\Users\<utente>\...`), `display()` inesistente fuori da IPython, esecuzione all'import, screener predefiniti che ignorano `offset`. | Codice. | Script portabile con CLI (`scripts/update_ticker.py`). |
| 19 | **B** | Progetto | `requirements.txt` senza `pyarrow`/`scipy` né versioni; file spurio `streamlit run app.py.txt`; `__pycache__` per due versioni di Python. | Cartella. | Dipendenze con intervalli di versione, Dockerfile, CI, `.gitignore`, pulizia. |

### Cosa era già corretto

Funzione obiettivo `S = Pr` / `S = 2 + IRR_ES` (Eq. 1); codifica non crescente (Eq. 2); parametri `p_c = 0,55`, `p_m = 0,30`,
`±2`; 1.000 scenari bootstrap con reinserimento (le righe vengono ricampionate insieme: correlazioni ereditate);
definizione di successo ("capitale mai negativo": è sufficiente controllare dopo ogni obiettivo, perché tra due obiettivi il
patrimonio non può diventare negativo); definizione dell'IRR dei flussi dell'investitore. La selezione dei peggiori scenari
per patrimonio terminale è equivalente a quella per IRR (i flussi intermedi sono uguali in tutti gli scenari, quindi l'IRR è
una funzione monotona del patrimonio finale).

## Verifiche sulla nuova versione

| Verifica | Risultato |
|---|---|
| Rendimento minimo del caso di studio del paper (160.000 €, 10.000 €/anno, obiettivi dell'Exhibit 4, 50 anni) | **4,427%** (paper: 4,43%) |
| Coerenza IRR_ES / deficit (Exhibit 11: 3,493% ↔ −588.369 €) | `V(3,493%)` = −609 k€ / −619 k€ a seconda della convenzione; scarto compatibile con la disuguaglianza di Jensen sulla coda (deviazione standard implicita degli IRR ~0,4–0,5 pp) |
| Valutazione vettorizzata vs implementazione di riferimento a cicli e `numpy_financial.irr` | Probabilità e patrimonio di coda identici; IRR entro 1e-6 |
| Esempio di mutazione del paper (`8 8 7 7 7 3 2 1` → `8 8 8 8 8 3 2 1`) | Riprodotto esattamente |
| GA vs ricerca **esaustiva** su problemi piccoli (T=10, 4 portafogli: 286 percorsi) | Ottimo raggiunto |
| GA vs ricerca esaustiva delle strategie "a 3 gradini" su T=50 (218.790 percorsi), 20 seed, piano con margine e piano non raggiungibile | **20/20 seed** raggiungono (o superano) il punteggio dell'esaustiva |
| Frontiera efficiente | Nessun portafoglio casuale (20.000 estrazioni) domina P1–P9; volatilità e rendimento crescenti |
| Dati | Nessun rendimento inventato; mese in corso escluso; esclusioni motivate |
| Interfaccia guidata (Playwright, 85 controlli per esecuzione, `scripts/e2e_smoke.py`) | Percorso completo con l'archivio di prezzi reale su desktop (italiano) e smartphone (inglese): contatori della home, pulsante «Accedi o registrati», importi scritti con milioni (`2M`, zero aggiunto in coda al testo formattato, selezione al clic), obiettivi con un cursore su anni di calendario (estremi 2027 e 2086), **fumetto con l'anno scelto e intestazione della scheda aggiornata mentre si trascina, identica a quella che il server scrive al rilascio** (grande, dentro lo schermo, nascosto a riposo) e interruttore «Si ripete ogni anno», piano vuoto a ogni avvio, rischio, pulsante «impostazioni avanzate» a tutta larghezza (stessa misura del pulsante principale), area avanzata in cinque passi (imbuto, categorie, cinque schermate, riepilogo delle modifiche, «torna alle scelte automatiche» che azzera e riporta alla conferma **in 0,14 s e passando da una dissolvenza**), evoluzione senza salto né replay, piano, confronto senza sovrapposizioni (controllo geometrico), composizione nel tempo, **nuovo avvio con seed diverso** (stessi obiettivi e stesso profilo), registrazione, salvataggio e uscita; nessun overflow orizzontale né errore JavaScript |
| Profili di rischio | Il percorso trovato non supera mai il livello del profilo (P3 / P6 / P9); gli scenari di un profilo sono il prefisso di quelli completi; a parità di seed la ricerca completa non peggiora l'anteprima |
| Avvisi sui pesi | Soglia di scostamento (5 pp), tre cause (passaggio del glide path, revisione, modifica), nessun avviso doppio, piano concluso (l'ultimo anno non è un errore), revisione **dal giorno in cui gira** con primo anno parziale e patrimonio stimato dal valore registrato (mai scambiato con quello dopo un anniversario; valori vecchi, futuri o anteriori alla versione ignorati), modifica dal **piano rimasto**, messaggio di tracciamento interpolato tra gli anniversari, errori isolati per portafoglio, email nella lingua dell'utente; password con *scrypt* e blocco dopo 5 tentativi |
| Internazionalizzazione | I 5 cataloghi (en, es, fr, ru, zh) coincidono con quello italiano per chiavi, segnaposto, tag e forme plurali (`python -m goalga.i18n.check`); ogni schermata, l'Excel e le email si generano in tutte e sei le lingue; formati numerici locali |
| Suite automatica | 636 test (`pytest`, archivio di prezzi sintetico, senza rete): core, GA, frontiera con tetti, regole e posizioni minime, flussi con primo anno parziale, universo e valutazione (ogni motivo di esclusione, pool con seed, rendimenti CAPM, cesta e tetti di classe), archivio dei prezzi, profili di rischio, rendimento composto (anche con 2 milioni di estrazioni lognormali), confronto su scenari nuovi, account e monitor (stima del patrimonio, anniversari, modifica dal piano rimasto), esportazioni, i18n, importi scritti a mano (cifre e parole in sei lingue, zero aggiunto in coda, round trip fino a 12 milioni), interfaccia (AppTest: percorso guidato, cursore in anni di calendario o intervallo per obiettivo, testi del fumetto e dell'intestazione in sei lingue con i plurali, area avanzata in cinque passi, mercato in memoria al ritorno alle scelte automatiche, seed a ogni avvio, inflazione), script del browser (senza `<`, elenco dei pulsanti di navigazione, versione), documentazione pubblicata (link, immagini, ancore, riferimento al paper, licenza, assenza di segnaposto e percorsi personali) e scena nel browser; eseguita anche in un ambiente pulito (senza `yfinance`, Streamlit 1.66) |

### Difetti trovati con l'universo completo e il seed

| Difetto | Evidenza | Correzione |
|---|---|---|
| **Stesso piano a ogni rilancio**: seed fisso (42) e risultato in cache per firma dei parametri | stessi obiettivi e profilo → nessun ricalcolo, stesso piano | Seed nuovo a ogni avvio (`begin_launch`); la firma include il seed; seed fisso solo a richiesta; i confronti tra profili riusano il seed (stesso pool e stessi scenari) |
| **La modalità automatica usava sempre 10 ETF**: i 3.400+ asset del database non venivano mai valutati | `DEFAULT_ETF_SELECTION` in ogni esecuzione | Valutazione di tutto il catalogo a ogni avvio (`screen_universe`) e pool estratto dal seed (`draw_pool`): tutti i fondi idonei + 33 azioni dagli 11 settori |
| **Frontiera concentrata sulle azioni**: lasciato libero, l'ottimizzatore media-varianza mette l'esposizione azionaria su 3-5 titoli e sfrutta il rumore delle stime di beta e covarianza | pool reale (39 fondi + 33 azioni), tre estrazioni: portafoglio più aggressivo = 100% in 3 titoli (40/40/20), sesto portafoglio = 56-71% in 4-5 titoli | Le azioni formano **una cesta** a pesi uguali con quota minima dell'esposizione azionaria (30%, modificabile) e massima del portafoglio (60%) |
| **Più ETF della stessa asset class aggirano il tetto** del 40% per asset (es. IHYG + HYG) | somma della classe oltre il 40% | Tetto complessivo per asset class (regole lineari nella frontiera) |
| **Fondi chiusi classificati come azioni «finanziarie»** dai listini (obbligazionari municipali, a reddito, buy-write…) | 304 titoli su 764 del settore, quasi tutti in «Asset Management» | Motivo di esclusione `fund` (non sono azioni ordinarie); gestori e società operative (BlackRock, Northern Trust Corporation…) restano |
| **Valute miste**: rendimenti in dollari e in euro nello stesso mercato | titoli USA e ETF UCITS insieme | Archivio in euro: i prezzi in dollari sono convertiti con il cambio di fine mese |
| Rendimenti attesi **storici delle azioni** ottimistici (chi è fallito non c'è più) e rumorosi | medie storiche a 10 anni | Fondi: ipotesi di lungo periodo; azioni: CAPM (`rf + β·premio`) con beta corretto di Blume sull'S&P 500 in euro; fonte storica solo a richiesta, con avviso |
| Rendimenti «anomali» (split inversi, fallimenti) nel pool | movimenti mensili oltre +100% / −60% | Esclusi dalla valutazione (`extreme`), come la volatilità oltre l'80% annuo (`volatile`) |

### Difetti trovati e corretti durante la verifica delle nuove funzioni

| Difetto | Correzione |
|---|---|
| Importi riscritti dal campo nel formato inglese anche con l'interfaccia in italiano: Streamlit esegue i callback *prima* dello script, quando la lingua della sessione non è ancora attiva | `i18n.set_resolver` legge la lingua da `st.session_state` |
| Il contatore della home non partiva: DOMPurify scartava in silenzio lo `<script>` perché conteneva `<` seguito da cifra | Script senza `<`; test sui `<script>` di `st.html` |
| Con etichetta «Strategia» (italiano) l'Excel e la tabella dei benchmark perdevano o duplicavano la colonna | Colonna interna rimossa prima di aggiungere quella localizzata; test su tutte le lingue |
| Importi nel formato inglese/cinese (`€1,250,000`) rifiutati dal campo | `parse_amount` riconosce anche i raggruppamenti americani |
| Il pulsante del profilo scelto era disabilitato e quasi invisibile | Resta attivo, con stile evidenziato |
| La ciambella della composizione (Plotly) veniva tagliata e la tabella nativa troncava l'ultima colonna | Ciambella in CSS e elenco HTML |
| Etichette dell'asse con unità fisse («лет»): forme plurali sbagliate in russo | Etichette già pluralizzate calcolate in Python |
| Stime del «cosa cambierebbe con più rischio» assenti dopo un piano modificato dall'area avanzata | Le anteprime vengono calcolate al momento della ricerca se mancano |
| **I milioni non si potevano scrivere** (pagine 1 e 2): aggiungendo uno zero a «€ 250.000» il campo leggeva «250.0000» come 250 euro (l'ultimo separatore veniva preso per decimale); le parole («2 milioni», «un millón», «2 млн») erano rifiutate; nella pagina 2 il rifiuto era silenzioso (riprodotto nel browser) | `parse_amount` riscritto: i separatori raggruppano le migliaia anche con gruppi irregolari (l'ultimo è decimale solo con 1–2 cifre), unità e parole nelle sei lingue (`k`, `M`, `mld`, `milioni`, `millones`, `млн`, `万`…), valuta e «di» ignorati, tetto di 10¹²; avviso anche nelle schede degli obiettivi; un clic nel campo ne seleziona il valore; 1 M€ tra le scorciatoie |
| **«Torna alle scelte automatiche» lento e a scatti**: il mercato automatico veniva ricostruito (0,42 s lato server) perché la cache teneva un solo mercato; la nuova schermata compariva senza transizione e gli elementi «stale» della precedente restavano sotto la nuova intestazione fino a fine esecuzione | `market_cache` (mercato automatico del seed corrente + ultimi 4 personalizzati, chiave = firma): 0,02 s; dissolvenza al clic sui pulsanti di navigazione, nuova schermata che compare con la propria animazione e resti della precedente nascosti (`behaviors.js`); nessuna transizione con *riduci animazioni* |
| **Slider degli obiettivi difficili da usare**: il valore compariva solo di lato e piccolo; in un obiettivo di un solo anno i due cursori coincidevano (quello in cima, trascinato a sinistra, non si muoveva; a destra l'obiettivo diventava ricorrente senza avvisare) | Un cursore per obiettivo e interruttore «Si ripete ogni anno» che apre l'intervallo (estremità sempre separate, `_keep_range`); mentre si trascina, fumetto grande sopra il cursore (anche su telefono, senza uscire dallo schermo) |
| **Durante il trascinamento non si vedeva «che anno» si stava scegliendo**: il numero grande del fumetto erano gli anni da oggi («36») e l'anno vero («2062») era una didascalia piccola e grigia; l'intestazione della scheda si aggiornava solo al rilascio. Provato in Edge e Chrome (148), WebKit, scala 150%, movimento ridotto, tocco, pause e scatti: il fumetto compariva sempre, ma non diceva l'anno in modo leggibile | Il cursore sceglie **anni di calendario** (2027–2086): il numero grande è l'anno, la didascalia dice «tra 36 anni» e l'intestazione si aggiorna in tempo reale con la stessa frase che scrive poi il server (testi e plurali dal server, `live_texts`; verificata l'identità in italiano, russo, cinese e inglese su telefono, con uno e due cursori). Lo script del browser è ora versionato: un aggiornamento sostituisce quello vecchio anche in una scheda già aperta |
| Il pulsante di accesso diceva solo «Accedi» | «Accedi o registrati» (e le altre lingue); la barra in alto non sovrappone mai marchio, avanzamento e controlli (verificato da 390 a 1440 px in tre lingue); sotto 860 px resta l'icona con il testo come nome accessibile |

## Verifica per l'uso con denaro reale

Richiesta: controllare che le logiche di calcolo siano coerenti e affidabili per gestire denaro vero. La verifica ha
combinato **controlli numerici sull'archivio reale** (cambi, finestra, pesi, variabilità tra lanci) e **una revisione
indipendente**: flussi, scenari, validazione, algoritmo genetico, profili, conti e monitor sono stati riscritti in Python
puro e confrontati con il codice dell'app su migliaia di casi. Il nucleo matematico è risultato corretto; i difetti
erano nel modo in cui il piano **viene seguito nel tempo** e in alcune scelte di presentazione e di modello.

### Cosa è risultato corretto

| Area | Verifica | Esito |
|---|---|---|
| Flussi, successo, IRR | 60 piani casuali contro un ciclo in Python puro; IRR di ogni scenario contro un risolutore di radici | patrimonio entro 5e-16, nessuna discordanza sul successo, IRR entro 3e-8 |
| Rendimento richiesto | confronto con ricerca per forza bruta; caso del paper | scarto 9e-6; **4,4267%** (paper: 4,43%) |
| Piano residuo | `Plan.advance` ricostruisce gli stessi flussi spostati di *k* anni (152 piani) | identici |
| Scenari | medie dei portafogli ricentrate sui rendimenti attesi; limite inferiore dei rendimenti; flussi casuali di ricerca e di verifica | scarto 6e-17; mai attivo su 8.804 finestre; nessuna riga in comune |
| Validazione | stessa simulazione in Python puro su 10.000 scenari nuovi | 5.845 successi su 10.000 in entrambe, stessa IRR di coda |
| Algoritmo genetico | 19.864 individui (vincoli, elitismo, miglior individuo); ricerca esaustiva di 125.970 percorsi su 3 piani | nessuna violazione; ottimo raggiunto da 8 seed su 8 per piano |
| Profili di rischio | tetti P3/P6/P9 in 18 lanci; scenari del profilo = prefisso di quelli completi | rispettati |
| Account | `years_elapsed` contro `relativedelta` su 20.000 coppie di date; livelli, completamento, variazioni dei pesi | identici |
| Cambi e date | allineamento dei mesi (correlazione massima a ritardo zero); SPY convertito in euro contro SXR8.DE | correlazione annua 0,90–0,99; scarto di tracciamento 2–7% (chiusure non sincrone) |
| Ricentratura sull'archivio reale | rendimento medio dei portafogli del mercato contro i rendimenti attesi | scarto 0,0 pp |

### Difetti trovati e corretti

| # | Sev. | Difetto | Evidenza | Correzione |
|---|---|---|---|---|
| 1 | **A** | **Un valore registrato prima di un anniversario veniva scambiato per il patrimonio dopo l'anniversario** (monitor): qualunque valore fino a 400 giorni prima valeva come patrimonio al compimento dell'anno | obiettivi da 40 k€ (anno 4) e 150 k€ (anno 10), valore di 120 k€ registrato 6 giorni prima del quarto anniversario: il piano residuo ripartiva da 120 k€ senza l'obiettivo da pagare → **probabilità 100%** (corretta: 71%) | il patrimonio di partenza è la mediana prevista dalla versione per quel giorno, corretta dello scarto del valore registrato (i flussi del piano tra le due date sono già nella mediana); i valori anteriori alla versione in corso, futuri o più vecchi di 400 giorni non si usano |
| 2 | **A** | **«Modifica» riportava capitale e scadenze iniziali** e salvare spostava l'orologio del piano | piano di 5 anni salvato di nuovo dopo 2 anni: livello da P2 a P3, fine da 2031 a 2033, nessun avviso | la modifica riparte dal **piano rimasto**: capitale stimato di oggi (valore registrato o mediana prevista), anni degli obiettivi contati da oggi, avviso che dice da dove arriva il capitale; l'ultimo anno non è modificabile |
| 3 | **M** | La revisione a metà anno trattava il patrimonio di oggi come quello dell'ultimo anniversario: **un mese prima dell'anniversario il primo obiettivo sembrava ancora a 2 anni** (invece di 1,08) | 300 k€, versamento 10 k€, obiettivo 360 k€: probabilità 37,1% contro 21,5% con il tempo reale; rendimento richiesto 7,9% contro 12,8% | **primo anno parziale** nel motore (`Flows.first_period`, `Plan.advance(..., fraction)`): il primo flusso resta al prossimo anniversario e il primo anno rende la frazione d'anno che manca; il monitor e la modifica lo usano. Con anno intero i calcoli sono identici a prima |
| 4 | **M** | Il **rendimento richiesto** (composto) era confrontato con il rendimento **atteso aritmetico** del percorso: la volatilità fa crescere il capitale meno della media aritmetica | portafoglio P9: 8,19% atteso contro 7,2% composto; la scala «prudente–dinamico» e le frasi «servirebbe più del …» sovrastimavano il margine | rendimento annuo **composto** atteso (`Market.compound_returns`, lognormale; verificato con 2 milioni di estrazioni) usato in ogni confronto con il richiesto; l'aritmetico resta nelle tabelle dei portafogli |
| 5 | **M** | Il **confronto con le strategie semplici** era calcolato sugli stessi scenari della ricerca, dove il glide path parte avvantaggiato | casa e pensione, seed 7: «solo la tua strategia raggiunge la soglia» in ricerca; su scenari nuovi bastano i mix costanti P4/P5 e la IRR di coda di P4 (3,93%) supera quella del glide path (3,78%) | confronto rifatto sugli scenari nuovi (gli stessi del numero in evidenza); verdetto con soglia di rumore (0,1 pp) e due casi nuovi («un'alternativa semplice rende di più», «la tua resta sotto la soglia») |
| 6 | **M** | **Posizioni minuscole** nei portafogli (non acquistabili, e illusione di diversificazione) | pool reale: 32 posizioni su 307 sotto l'1% nei fondi, titoli della cesta allo 0,05–0,07% | minimi: nessun fondo sotto l'**1%**, nessun titolo sotto lo **0,5%** (la cesta compare solo se vale ≥ 33 × 0,5% = 16,5%: dal sesto portafoglio in su); il portafoglio è rifatto senza la posizione, a pari rischio (`portfolios.prune_positions`); i portafogli salvati prima restano identici |
| 7 | **M** | I primi anni di vita di alcuni **ETF giovani** contengono **mesi errati** del listino: entrerebbero nella finestra di stima se si imponesse molto storico | SXR8.DE −20% (11/2010), IEMA −33% (10/2009), SEML −22% (10/2011), IBTM −25% (01/2009), EXXT −21% (01/2009) | la finestra di stima è al massimo di **14 anni** (la più recente) e lo storico minimo richiesto non supera 14 anni; il limite è nelle specifiche salvate, quindi i piani già salvati non cambiano |
| 8 | **B** | Percentuali sotto il 100% **arrotondate a «100%»** | probabilità 99,996% mostrata come 100,0%; 99,5% come 100% nei confronti | mai «100%» se anche un solo scenario fallisce |
| 9 | **B** | Il **JSON** scaricato non conteneva la verifica su scenari nuovi e non diceva quale probabilità fosse | `success_probability` (in ricerca) 0,909 contro 0,906 su scenari nuovi | blocco `out_of_sample` (scenari, probabilità, intervallo al 95%, IRR di coda), rendimenti atteso aritmetico e composto; Excel con percentuali formattate e colonna degli obiettivi «rivalutati» se c'è inflazione |
| 10 | **B** | Titolo e testo potevano **contraddirsi** (ricerca sotto soglia, verifica sopra); un quasi-successo mostrava «95,0% … sotto 95»; una coda del 2,5% era scritta «2%» | casi riprodotti forzando i flag | vale il numero verificato su scenari nuovi; due decimali nei quasi-successi; decimali nelle code non intere |
| 11 | **B** | Ultimo anno del piano: **errore** «nessun piano residuo» a ogni controllo | codice di uscita 1 del monitor | nessun errore: non c'è nulla da rivedere |
| 12 | **B** | Portafogli personalizzati **non ordinati per rischio** (il glide path «mai in aumento» crescerebbe di rischio); piano con importi non finiti; tipo di obiettivo assegnato per posizione dopo che alcuni obiettivi erano stati pagati | volatilità 6,4% → 8,1% con colonne invertite | portafogli ordinati per volatilità; importi non finiti rifiutati; tipo assegnato per anno |

### Scelte di modello cambiate

- **Inflazione**: importi nominali con inflazione 0% rendevano ottimistica la probabilità (250 k€ tra 20 anni valgono
  168 k€ di oggi al 2%). Ora gli obiettivi sono in **euro di oggi e rivalutati del 2% l'anno** (modificabile nell'area
  avanzata, anche a 0%); riepilogo, pagina del piano ed export lo dicono. I versamenti restano costanti, salvo diversa
  impostazione. Il piano di esempio (casa 40 k€ + pensione 300 k€, 50 k€ + 6 k€/anno) con inflazione non è più raggiungibile
  al 90%: è l'effetto atteso, non un errore.

### Variabilità e sensibilità (da conoscere prima di dare cifre a un cliente)

- **Seed**: stesso piano, 12 seed diversi (profilo equilibrato). Obiettivo facile: 98,5–99,3% (dev. std 0,3 pp); medio:
  87,5–90,8% (1,1 pp: la soglia del 90% può essere superata o no a seconda del seed); difficile: 73–77,5% (1,5 pp). La
  probabilità in ricerca supera di circa 1 pp quella su scenari nuovi («maledizione del vincitore»): per questo il numero
  in evidenza è quello su scenari nuovi.
- **Finestra storica**: con le serie in euro del catalogo la finestra comune è di circa 11–12 anni (07/2015–09/2026 nel
  pool di prova) e **non comprende il 2008**. Le code poggiano su 12/2018, 03–04/2020 e 2022 (5° percentile del
  portafoglio più dinamico −9,4%, peggiore finestra di 12 mesi −19,3%). Togliendo il 2022 la probabilità dello stesso
  piano passa dal 90,5% al 94,6%; senza 2020 e 2022 al 96,9%; con un solo anno aggiunto a −40% scende all'87,7%.
  L'intervallo di Wilson (±0,5 pp) misura il rumore del campionamento, **non** l'incertezza del modello.
- **Selezione dei titoli**: allentare il filtro (da +100%/−60% a +300%/−90% mensili) porta una cesta di 33 titoli da
  volatilità 18,0% e peggiore finestra a 12 mesi −20,2% a 18,7% e −23,3%: le code dei titoli sono sottostimate, e il
  *survivorship bias* resta.
- **Il profilo «dinamico»** si comporta come l'equilibrato: negli esperimenti l'algoritmo non ha mai usato oltre P5, perché
  da P6 a P9 il rendimento atteso sale di 0,19 pp a fronte di 5,2 pp di volatilità in più.
- **Volatilità**: quella mostrata nelle tabelle (da covarianza con shrinkage) può differire dalla volatilità degli scenari
  simulati (P9: 15,0% contro 14,2% con finestre annuali e 16,3% con quelle mensili).
- **Convenzioni**: versamenti e obiettivi a fine anno (un versamento mensile reale rende circa il 2,5% in più sul capitale
  costruito con i versamenti); gli obiettivi sono rivalutati dall'anno 1, la crescita dei versamenti parte dall'anno 2;
  il rendimento richiesto è composto, quello della singola simulazione è il percorso reale.
- **Costi e tasse**: non modellati. Cambi non coperti. Strumenti in dollari non sempre acquistabili da un risparmiatore
  europeo.

## Limiti residui e raccomandazioni

- **Ipotesi di rendimento**: le ipotesi di lungo periodo predefinite sono quelle dell'Exhibit 6 del paper (2022). Per uso
  professionale vanno sostituite con le capital market assumptions della casa. Per le azioni il CAPM usa un premio azionario
  unico (S&P 500 meno tasso privo di rischio) e un beta stimato su 10 anni di dati mensili: è un'ipotesi semplice, non una
  previsione.
- **Valuta**: tutti i prezzi sono in euro; le attività in dollari includono il cambio EUR/USD **non coperto** (il paper usa
  indici in euro non coperti). ETF e azioni quotati negli USA possono non essere acquistabili da tutti i risparmiatori
  europei (PRIIPs/KID): i 18 ETF UCITS del catalogo lo sono.
- **Universo azionario**: derivato dagli screener correnti di Yahoo → *survivorship bias*; il filtro sui fondi chiusi è
  euristico (nome e industria), quindi qualche fondo può restare tra le azioni; il paniere di azioni è un campione con
  seed, non una raccomandazione. La quota minima del 30% dell'esposizione azionaria è una scelta di progetto.
- **Modello**: nessun costo, commissione o tassa; inflazione del 2% annuo per impostazione predefinita (gli obiettivi
  sono in euro di oggi); versamenti e obiettivi a fine anno; ribilanciamento annuale implicito; scenari bootstrap su una
  sola finestra storica di 11–12 anni (la qualità dell'output dipende da quella dei dati e senza il 2008 le code sono più
  leggere di quelle di una crisi lunga). Il paper suggerisce di rilanciare il modello ogni anno con dati aggiornati.
- **Fonte dati**: Yahoo Finance non è una fonte contrattuale e i suoi dati sono per uso personale/di ricerca: per un uso
  commerciale va sostituita con un data provider con licenza (il downloader di `goalga/snapshot.py` è intercambiabile) e
  l'archivio va tenuto privato.
- **Account**: niente verifica email, recupero password né cookie «ricordami»; email, nome e portafogli sono salvati senza
  cifratura applicativa (le password sono sempre *hash scrypt*): prima di un uso pubblico vanno aggiunti i controlli
  mancanti (o delegati a un identity provider) e il database deve essere cifrato a riposo. L'archivio SQLite predefinito
  non è persistente su Streamlit Community Cloud: in produzione usare PostgreSQL (`GOALGA_DATABASE_URL`).
- **Concorrenza**: ogni visitatore ha una sessione isolata, ma un processo Streamlit condivide la CPU: un avvio costa
  ≈6 secondi di CPU (misurato: 4 avvii simultanei → anteprime in ~10 s; 8 → 22-54 s; 16 → ~75 s). Per un pubblico reale
  servono più repliche (sessioni «appiccicose») o una coda di calcolo.
- **Avvisi**: le email partono solo se l'SMTP è configurato; il monitor gira a intervalli (il workflow è giornaliero) e
  rilancia l'algoritmo solo per i piani con portafogli efficienti costruiti sull'archivio dei prezzi (con il pool di asset
  salvato); gli altri ricevono gli avvisi dei passaggi previsti dal glide path. Il patrimonio di una revisione è una
  **stima** (mediana prevista più lo scarto dell'ultimo valore registrato): per un piano preciso conviene registrare il
  valore reale ogni mese; con un'attesa di 400 giorni i check-in non vengono più usati.
- **Anteprime del rischio**: i numeri mostrati nella scelta del profilo sono stime (ricerca più breve, stesso seed); sulle
  prove i valori delle anteprime differivano da quello finale fino a 2 punti su 100 (6 lanci su 18); il piano riporta
  sempre il risultato completo, verificato su scenari nuovi.
- **Prima di usarlo con clienti reali**: oltre ai controlli qui descritti servono la validazione del modello da parte della
  funzione di risk management, le ipotesi di rendimento della casa al posto di quelle del paper (2022), una fonte dati con
  licenza, il trattamento di costi e tasse e le verifiche regolamentari previste per gli strumenti di consulenza.
