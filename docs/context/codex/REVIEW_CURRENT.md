# REVIEW_CURRENT.md

## Patch corrente
Stabilizzazione VM / site guard + private_only

## Stato review
Verde tecnico nel workspace. Validazione operativa VM ancora da ripetere sulla dist piu recente del 2026-03-25.

## Findings chiusi
- GUI bundle non avviabile:
  - il packaging PyInstaller non includeva in modo affidabile `tkinter` e i runtime Tcl/Tk
  - il bundle usciva subito all'avvio invece di restare vivo
- cooldown percepito come loop del site guard:
  - dopo `interstitial_datadome` il guard restava in `cooldown_active` senza una recovery intermedia leggibile
  - il reset manuale sbloccava il ciclo, segnale che mancava una probe controllata durante il cooldown
- routing browser non abbastanza robusto su bundle VM:
  - `idealista` preferiva `msedge`, ma alcuni launch fallivano e il sito degradava su `chrome`
  - questo peggiorava la probabilita di `interstitial_datadome` invece di mantenere il browser piu sano per sito
- volume detail-check troppo alto in `private_only`:
  - gli annunci gia noti nel DB venivano comunque riaperti, aumentando interazioni sospette non necessarie
  - la strategia corretta e aprire il dettaglio solo per annunci nuovi, senza label agenzia e non gia classificati

## Verifiche eseguite
- `python -m unittest discover -s 2.1_stable/tests -p test_private_only_and_logging.py -v` con `PYTHONPATH=2.1_stable` -> OK
- smoke locale della nuova dist:
  - `affitto_gui.exe` resta vivo all'avvio
  - `affitto_cli.exe --help` risponde
- review log VM aggiornati in `docs/tmp_logs.md`:
  - `idealista` riparte su `msedge` dopo reset del site guard
  - `immobiliare` continua a lavorare su `chrome`
  - i run precedenti mostravano degradazione `msedge -> chrome -> interstitial_datadome`
- review DOM/live precedente:
  - schermata "Verifica del dispositivo ..." osservata su `idealista`
  - pagina completa caricata dopo attesa di alcuni secondi
  - diversi annunci agenzia esposti tramite link `/pro/` con nome nel logo `img[alt]`
  - pagina dettaglio annuncio privato con label `Privato`
  - pagina dettaglio annuncio professionale con label `Professionista`

## Focus della review
- non e emerso un hard block irreversibile generalizzato, ma una catena di attriti reali:
  - dist GUI rotta
  - recovery del guard troppo opaca
  - fallback browser non allineato con l'affinita per sito
  - volume detail-check non abbastanza parsimonioso
- il fix corretto non era un bypass piu aggressivo, ma:
  - packaging valido
  - browser installati reali
  - probe controllata nel cooldown
  - riuso del DB per ridurre aperture
- `immobiliare` resta il benchmark piu sano:
  - DOM piu stabile
  - hook agenzia piu forti
  - filtro `private_only` gia efficace in modo credibile

## Esito
- Patch approvata nel workspace.
- Residui aperti:
  - nuova validazione VM/log reali su `idealista` per misurare il delta di probe guard + browser retry + DB cache
  - confermare che il pacing piu lento e il riuso DB riducano davvero le aperture dettaglio sui cicli successivi
  - decidere se il tema browser "gestito" richiede una patch a parte o va accettato come limite dell'automazione corrente
  - pulizia pre-push verso la repo GitHub privata
