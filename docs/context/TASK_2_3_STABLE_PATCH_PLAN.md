# TASK_2_3_PATCH_PLAN.md

## Titolo
Piano patch `2.3_stable` - stealth, operativa e GUI

## Owner
Backend / Codex

## Stato
Ready con gate obbligatori.

## Linea di riferimento
`2.3_stable` - baseline ereditata da `2.2.2 refactorizzata`

Patch attiva precedente:
- `2.3-patch-01`
- allineamento UA/TLS Firefox/135.0
- rimozione patch `navigator.deviceMemory`
- gia applicata, non ritoccare

## Contesto operativo
- Servizio 24/7 su PC Windows casalingo con connessione residenziale
- Due URL fissi: un Idealista, un Immobiliare
- Target operativo diurno: 3 minuti
- `private_only=True` su entrambi i siti
- Backend: `camoufox`
- Profili persistenti per `site/channel/generation`

## Regola generale
Ogni patch deve:
- preservare il comportamento sano della `2.2`
- cambiare un solo asse per volta
- restare verificabile con KPI gia presenti nei log
- non introdurre dipendenze nuove salvo esplicita indicazione
- non toccare state machine, guard logic, selettori sito, pipeline `private_only` salvo patch che li riguarda esplicitamente

## Gate globali

### Gate 0 - Baseline green prima di aprire nuove patch
- aggiornare i test ancora fermi al pre-`2.3-patch-01`
- portare `pytest -q` a verde sulla baseline attuale
- non mischiare questa hygiene con patch di prodotto

### Gate tra una patch e la successiva
Prima di passare alla patch successiva devono essere veri tutti questi punti:
- working tree pulito o comunque limitato alla patch corrente
- test rilevanti verdi
- se la patch richiede soak, soak eseguito e sintetizzato nei doc correnti
- nessuna regressione evidente su guard, pacing, `private_only`, parser

### Gate documentale minimo per ogni patch
- aggiornare `docs/context/codex/ACTIVE_PATCH.md`
- aggiornare `docs/context/codex/OUTPUT_CURRENT.md`
- aggiornare `docs/context/codex/REVIEW_CURRENT.md`

## Tema congelato
- `soft mode` post-`hard_block` congelato per ora
- non rientra nell'ordine di esecuzione attivo

---

## Patch A1 - Canvas noise seed per-generazione

### Priorita
1 di 8

### File coinvolti
- `src/affitto_v2/scrapers/render_context.py`
- `src/affitto_v2/scrapers/browser/persona.py`
- `tests/test_render_context.py`

### Problema
Il canvas noise usa delta hardcoded `+1, +2, +3`.

Questo rende il rumore identico su ogni macchina e su ogni sessione, invece di restare deterministico per persona/generazione.

### Soluzione
Derivare gli offset dal seed gia usato in `build_camoufox_persona()`.

Meccanismo:
1. Calcolare tre offset dal seed.
2. Portarli nella persona o passarli esplicitamente al builder del render context.
3. Aggiungere placeholder `__CANVAS_R_OFFSET__`, `__CANVAS_G_OFFSET__`, `__CANVAS_B_OFFSET__`.
4. Sostituirli nel template JS.

### Invarianti
- stessa `profile_generation` -> stessi offset
- generazioni diverse -> offset diversi
- `GLOBAL_RENDER_CONTEXT_INIT_SCRIPT` puo restare col fallback statico
- nessuna variazione a pacing, guard, state machine, profili

### Done
- test unitari aggiornati
- offset diversi tra generazioni diverse
- fingerprint stabile dentro la stessa generazione
- `pytest -q` verde

### Rollback
Ripristinare `+1, +2, +3`.

---

## Patch C2 - Fix finestra CMD visibile all'avvio automatico

### Stato
Codice e test chiusi. Verifica reale post-reboot ancora da eseguire.

### Priorita
2 di 8

### File coinvolti
- `src/affitto_v2/gui_app.py`

### Problema
L'autostart Windows usa un `.bat` e apre una finestra CMD visibile al boot.

### Soluzione
Sostituire il `.bat` con un `.vbs` che lancia il processo con finestra invisibile.

### Invarianti
- checkbox "Avvio automatico GUI" invariata
- `gui_state["autostart_enabled"]` invariato
- disattivazione autostart -> rimozione script
- assenza di `APPDATA` -> warning come oggi
- rimozione silenziosa del vecchio `.bat` se presente

### Done
- reboot con autostart attivo senza finestra CMD
- presenza di `wscript.exe` -> `affitto_gui.exe` o `pythonw.exe`
- vecchio `.bat` rimosso

### Rollback
Ripristinare il `.bat`.

---

## Patch C1 - Autostart avvia il servizio continuo automaticamente

### Priorita
3 di 8

### Stato
Codice e test chiusi. Verifica reale post-reboot ancora da eseguire.

### File coinvolti
- `src/affitto_v2/gui_app.py`

### Problema
L'autostart oggi apre la GUI ma non avvia il servizio continuo.

### Soluzione
Aggiungere una seconda checkbox dipendente, salvata in `gui_state` come `autostart_service_enabled`, e avviare il servizio automaticamente solo quando le condizioni operative concordate sono soddisfatte.

### Requisiti di prodotto chiariti
- il servizio deve partire solo quando la GUI e stata aperta dal boot di Windows tramite autostart
- il flag `autostart_service_enabled` e valido solo se `autostart_enabled` e attivo
- se entrambe le spunte sono attive, al boot il servizio puo ripulire automaticamente un vecchio `live_service.stop` e partire

### Implicazioni implementative
- l'apertura manuale della GUI non deve avviare il servizio anche se `autostart_service_enabled=True`
- serve un segnale affidabile di "launch da autostart Windows" distinto da una normale apertura manuale
- quando `autostart_enabled=False`, anche `autostart_service_enabled` va trattato come non operativo o forzato a `False`
- prima dello start automatico va rimossa la stop-flag stale solo nel percorso boot-autostart

### Invarianti
- checkbox GUI e checkbox servizio devono restare separate in UI, ma la seconda dipende logicamente dalla prima
- start/stop manuali invariati
- config non valida -> nessun crash, nessun dialog bloccante
- apertura manuale GUI -> nessun avvio automatico del servizio
- stop-flag stale pulita solo nel percorso di boot autostart con entrambe le spunte attive

### Done
- reboot con entrambe le spunte attive -> GUI aperta e servizio avviato automaticamente
- apertura manuale della GUI con stesse spunte -> servizio non avviato automaticamente
- `autostart_service_enabled=True` con `autostart_enabled=False` -> nessun avvio automatico
- stop-flag vecchia presente al boot -> rimossa e servizio avviato
- config non valida -> nessun crash, solo log warning

### Rollback
Rimuovere checkbox e avvio automatico del servizio.

---

## Patch A2a - Jitter del ciclo su cadenza gia configurata

### Priorita
4 di 8

### File coinvolti
- `src/affitto_v2/main.py`

### Problema
Il ciclo usa una cadenza metronomica troppo regolare.

### Soluzione
Applicare jitter al delta di ciclo mantenendo invariata la logica di griglia basata su `next_cycle_monotonic`.

Nota:
- il target diurno a 3 minuti resta decisione/configurazione operativa
- questa patch non introduce ancora la fascia notturna

### Invarianti
- `next_cycle_monotonic` resta la griglia di riferimento
- stop flag e overrun check invariati
- `missed_cycle_count` e `overrun_count` continuano a funzionare

### Osservabilita obbligatoria
- log con `actual_cycle_sec`

### Done
- soak diurno 2h
- spread visibile nei log
- nessun pattern rigido fisso
- nessuna regressione su overrun e stop logic

### Rollback
Ripristinare il delta fisso.

---

## Patch A2b - Fascia notturna 01:00-07:00 timezone locale PC

### Priorita
5 di 8

### File coinvolti
- `src/affitto_v2/main.py`

### Problema
Il servizio preme sui siti di notte come in fascia diurna.

### Soluzione
Applicare un moltiplicatore di cadenza solo in fascia `01:00-07:00` letta dalla timezone locale del PC, mantenendo separata la logica dal jitter diurno gia introdotto in `A2a`.

### Invarianti
- nessun cambio a guard, pacing, parser, state machine
- nessuna dipendenza nuova, solo stdlib
- logica notturna indipendente e facilmente rollbackabile

### Osservabilita obbligatoria
- log con `night_mode=True/False`
- log con `actual_cycle_sec`

### Done
- osservazione in fascia notturna
- `night_mode=True` nei log
- cadenza notturna realmente dilatata

### Rollback
Rimuovere il moltiplicatore notturno.

---

## Patch A3 - Ordine URL randomizzato tra cicli

### Priorita
6 di 8

### File coinvolti
- `src/affitto_v2/scrapers/live_fetch.py`

### Problema
Gli URL vengono visitati sempre nello stesso ordine.

### Soluzione
Fare uno shuffle locale della lista URL all'inizio di `fetch_live_once()`.

### Invarianti
- tutti gli URL visitati ogni ciclo
- ordine solo locale, config invariata
- independence per sito invariata

### Done
- 10+ cicli con ordine variabile nei log
- nessuna regressione di outcome tier

### Rollback
Ripristinare l'ordine originale.

---

## Patch B3 - Long block observability >= 1h

### Priorita
7 di 8

### File coinvolti
- `src/affitto_v2/scrapers/guard/store.py`
- `src/affitto_v2/main.py` oppure post-run equivalente

### Problema
Cooldown lunghi restano silenziosi lato utente.

### Soluzione
Inviare una sola notifica all'ingresso del blocco lungo e una sola notifica alla recovery.

### Invarianti
- nessuna modifica alla logica di cooldown
- nessuna notifica per cooldown brevi
- flag persistente per sito
- con `notify_mode=none` nessun crash

### Done
- blocco reale >= 1h -> 1 notifica ingresso + 1 notifica recovery
- zero notifiche nei cicli intermedi

### Rollback
Rimuovere flag e notifiche.

---

## Patch B1 - Immobiliare adaptive prepare

### Priorita
8 di 8

### File coinvolti
- `src/affitto_v2/scrapers/live_fetch.py`
- `src/affitto_v2/scrapers/sites/immobiliare.py`

### Problema
Switch-to-list e scroll sono oggi meccanici e sempre eseguiti.

### Soluzione
Rendere condizionali:
- click su list mode solo se non gia attiva
- scroll solo se il container lista non e gia visibile

### Invarianti
- confronto sempre contro baseline `2.2`
- nessuna modifica ai selettori
- nessun impatto su Idealista
- nessun aumento di `parse_issue`

### Done
- soak comparativo 24h
- log con `clicked/skipped`
- log con `executed/skipped`
- nessun peggioramento visibile su Immobiliare

### Rollback
Ripristinare prepare phase fissa.

---

## Riepilogo ordine di esecuzione

| Ordine | ID  | Nome                                      | Rischio     | Soak richiesto |
|---|---|---|---|---|
| 0 | G0  | Baseline test hygiene post `2.3-patch-01` | Basso       | No             |
| 1 | A1  | Canvas noise seed per-generazione         | Basso       | No             |
| 2 | C2  | Fix CMD -> `.vbs` silenzioso              | Basso       | Reboot         |
| 3 | C1  | Autostart servizio continuo               | Medio       | Reboot         |
| 4 | A2a | Jitter del ciclo                          | Basso       | Si, 2h diurna  |
| 5 | A2b | Fascia notturna                           | Basso       | Si, osservazione |
| 6 | A3  | Ordine URL randomizzato                   | Molto basso | Si, 10+ cicli  |
| 7 | B3  | Long block observability >= 1h            | Basso       | Si             |
| 8 | B1  | Immobiliare adaptive prepare              | Medio       | Si, 24h        |

## Cosa NON toccare in nessuna patch
- state machine e transizioni
- guard jitter min/max sec
- pacing Gamma `(shape=2.0, scale=1.5)`
- bootstrap static resources
- DataDome detection e challenge handling
- rotazione profilo su `hard_block`
- rotazione preventiva 24h Immobiliare
- WebGL strings e `hardwareConcurrency`
- pipeline `private_only` e memoria negativa
- selettori Idealista
- `soft mode` post-`hard_block` finche resta congelato

## Output atteso da Codex per ogni patch
- file modificati con descrizione sintetica
- invarianti verificate
- esito test
- criterio di done soddisfatto: si/no con motivazione
- effetti collaterali osservati
