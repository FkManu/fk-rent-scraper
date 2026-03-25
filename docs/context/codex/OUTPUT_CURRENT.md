# OUTPUT_CURRENT.md

## Patch corrente
Stabilizzazione VM / site guard + private_only

## Stato
Implementazione completata nel workspace, dist ricompilata e review aggiornata ai test VM del 2026-03-25.

## Cosa e stato fatto
- introdotta e mantenuta la modalita `private_only_ads` in config/runtime/GUI
- confermata la coerenza con `extract_agency` quando la modalita e attiva
- applicato filtro locale con skip degli annunci con `agency` valorizzata e conteggio separato dei `private_only_unknown`
- hardening della log rotation Windows con `SafeRotatingFileHandler` e file handler disabilitato nel processo GUI
- migliorata la gestione del ramo `interstitial_datadome`:
  - clear della challenge non dichiarato piu troppo presto se URL/body restano interstitial
  - cooldown interstitial con probe controllata invece di skip cieco fino al reset
  - reset state GUI/runtime aggiornato per pulire anche i nuovi campi del guard
- migliorata la strategia browser su Windows bundle:
  - uso dell'eseguibile reale installato per `msedge` e `chrome` quando disponibile
  - `chromium` non preferito piu in auto-mode su bundle frozen
  - retry immediato con browser alternativo sui blocked outcome piu netti
- ridotte le aperture dettaglio `private_only` su `idealista`:
  - detail-check solo per annunci nuovi, senza etichetta agenzia e non gia presenti nel DB
  - riuso della classificazione professionale gia nota nel DB
  - annunci gia noti senza segnale agenzia trattati come `unknown` senza nuova apertura dettaglio
- packaging GUI Windows corretto:
  - inclusi `_tkinter`, `tcl86t.dll`, `tk86t.dll`, cartelle `tcl8.6` e `tk8.6`
  - aggiunto runtime hook per `TCL_LIBRARY` e `TK_LIBRARY`
- aggiornati i file di contesto operativo e aggiunta memoria sessione in `MultiAgent`

## Evidence raccolta
- dai log VM del 2026-03-25:
  - `idealista` poteva entrare in cooldown ripetuto dopo `interstitial_datadome`, percepito come loop di protezione
  - il reset manuale del site guard permetteva di ripartire su `msedge`
  - `immobiliare` continuava invece a lavorare su `chrome`, confermando il disaccoppiamento per sito
  - prima del fix browser, alcuni run di `idealista` cadevano da `msedge` a `chrome` e peggioravano in DataDome
- dai test successivi dell'utente:
  - dopo reset del site guard, `idealista` ha ripreso a ciclare correttamente su `msedge`
  - `immobiliare` ha continuato a lavorare su `chrome` come atteso
  - il filtro privati lato utente e stato giudicato buono, ma da rendere piu parsimonioso
- dalla review log+DOM precedente:
  - presenza reale della schermata "Verifica del dispositivo ..." con auto-risoluzione verso pagina completa dopo alcuni secondi
  - molte card professionali con link `/pro/`
  - nelle pagine dettaglio il publisher type e esposto in chiaro come `Privato` o `Professionista`

## File toccati
- `src/affitto_v2/scrapers/live_fetch.py`
- `src/affitto_v2/db.py`
- `src/affitto_v2/main.py`
- `src/affitto_v2/gui_app.py`
- `packaging/affitto_gui.spec`
- `packaging/runtime_hook_tk.py`
- `tests/test_private_only_and_logging.py`
- `docs/context/HANDOFF.md`
- `docs/context/NEXT_STEPS.md`
- `docs/context/ROADMAP_NEXT_MILESTONES.md`
- `docs/context/README.md`
- `docs/context/codex/ACTIVE_PATCH.md`
- `docs/context/codex/OUTPUT_CURRENT.md`
- `docs/context/codex/REVIEW_CURRENT.md`
- `docs/context/codex/HISTORY.md`

## Verifiche eseguite
- `python -m unittest discover -s 2.1_stable/tests -p test_private_only_and_logging.py -v` con `PYTHONPATH=2.1_stable` -> OK
- smoke build:
  - `affitto_gui.exe` resta vivo all'avvio
  - `affitto_cli.exe --help` risponde
- review dei log VM aggiornati in `docs/tmp_logs.md`
- ispezione live precedente via browser su ricerca e dettagli `idealista`

## Limiti residui
- il ramo `interstitial_datadome` resta prudente: se la verifica non si pulisce o la probe non recupera, il fetch viene comunque chiuso come bloccato
- il secondo controllo dettaglio Idealista e limitato da cap e si interrompe se emerge una challenge, quindi non garantisce riclassificazione completa in tutti i run
- l'impatto anti-bot del browser "gestito" non e eliminato: usare il browser installato aiuta, ma non rende Playwright indistinguibile da apertura manuale
- serve nuova validazione VM/log reali prima del push GitHub finale
