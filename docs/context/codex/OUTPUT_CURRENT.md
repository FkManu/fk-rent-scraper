# OUTPUT_CURRENT.md

## Patch corrente
Release stabilization aggiornata:
- consolidamento finale della linea `camoufox`
- validazione VM del servizio continuo con soak reale
- fix memoria negativa `private_only`
- fix `idealista` sul `detail_touch_count`
- riallineamento docs e release da `preview` a `stable`

## Stato
Pivot `camoufox` integrato nel ramo e soak VM del `2026-03-26` positivo.
La linea viene ora promossa a `2.2 stable`, pur restando nella root tecnica `2.2_test`.

## Implementazione eseguita
- backend browser predefinito portato a `camoufox`
- alias legacy `auto|firefox|chromium|chrome|msedge` mantenuti solo per compatibilita CLI e normalizzati a `camoufox`
- launch Camoufox con profilo Windows umanizzato:
  - `humanize=True`
  - `locale=it-IT`
  - `timezone=Europe/Rome`
  - `screen=1920x1080`
- root profili persistenti riallineata a `runtime/camoufox-profile`
- GUI riallineata al nuovo default backend
- setup Windows aggiornato per eseguire `python -m camoufox fetch`
- spec di packaging aggiornate per includere dipendenze `camoufox`
- servizio continuo confermato come percorso operativo reale del ramo
- soak VM reale documentato in `docs/tmp_logs.md`
- memoria negativa `private_only` introdotta nel DB per i professionali trovati dal detail-check
- fix chiuso sul `detail_touch_count` Idealista che poteva produrre `unexpected_error` e cooldown artificiale
- coercizione osservabile del `detail_touch_count` con warning se il contratto dovesse rompersi di nuovo
- documentazione di contesto ripulita e riallineata al ruolo di release stable

## Stato operativo osservato in VM
- finestra osservata: `2026-03-26 11:59:51` -> `2026-03-26 16:55:19`
- comando usato: `affitto_cli.exe fetch-live-service ... --browser-channel camoufox ...`
- cicli completati: `60`
- outcome osservati:
  - `healthy`: `240`
  - `degraded`: `0`
  - `blocked`: `0`
  - `cooling`: `0`
  - `assist_required`: `0`
  - `ERROR`: `0`
  - `Traceback`: `0`
- servizio:
  - sempre `stable`
  - `runtime disposition=keep` in `56` cicli
  - `recycle_site_slot` in `4` cicli
  - nessun `recycle_runtime`
  - nessun `stop_service`

## Lettura tecnica utile
- `idealista` tiene molto bene la sessione lunga su `camoufox`
- `immobiliare` lavora bene ma ricicla periodicamente il solo slot locale per `slot_reuse_cap`
- la distinction locale vs globale del runtime sta quindi funzionando:
  - si preserva il runtime condiviso
  - si ricrea solo lo slot del sito quando la policy prudente lo richiede

## File toccati
- `README.md`
- `requirements.txt`
- `scripts/setup_test_env.ps1`
- `packaging/affitto_cli.spec`
- `packaging/affitto_gui.spec`
- `src/affitto_v2/gui_app.py`
- `src/affitto_v2/main.py`
- `src/affitto_v2/scrapers/__init__.py`
- `src/affitto_v2/scrapers/live_fetch.py`
- `tests/test_private_only_and_logging.py`
- `docs/cli_test_matrix.md`
- `docs/windows_packaging.md`

## Limiti residui
- il problema aperto piu concreto oggi non e la tenuta del motore ma la precisione del filtro `private_only`
- una prima correzione strutturale e gia stata chiusa:
  - gli annunci professionali trovati dal detail-check Idealista vengono ora persistiti in una cache negativa dedicata
  - questo dovrebbe ridurre il pattern osservato nei log in cui gli stessi `ad_id` professionali venivano riaperti a ogni ciclo
- nei log VM il warning `guarantee_private_only=False` resta il principale punto di attenzione
- il guard distingue ancora poco bene, lato osservabilita, tra degrado da errore interno e degrado da sito
- la policy di recycle preventivo dello slot `immobiliare` funziona, ma va ancora formalizzata meglio nei docs come scelta di ramo
- `assist_entry_mode` e i percorsi `cdp_bootstrap` / `cdp_recovery` restano predisposti ma non implementati
- la GUI bundle e il companion CLI sono coerenti col nuovo backend, ma il flusso interattivo end-to-end da bundle resta meno verificato del soak CLI/servizio

## Come verificare
- da `C:\\Users\\panda\\Desktop\\sboorrra\\affitto\\2.2_test`:
- `.\\.venv\\Scripts\\python.exe -m unittest tests.test_private_only_and_logging`
- `python -m unittest discover -s tests`
- in VM:
  - eseguire `python -m camoufox fetch` o provisioning equivalente
  - lanciare `fetch-live-service`
  - verificare in `docs/tmp_logs.md` o nei log runtime:
    - `Using persistent Camoufox profile`
    - `Fetch URL result. ... channel=camoufox`
    - `Live fetch service cycle state. ... service_state=stable`
    - riduzione o sparizione del pattern ripetuto:
      - `Idealista detail verification flagged professional listing. ad_id=35256447`
      - `Idealista detail verification flagged professional listing. ad_id=35231585`
    - comparsa di `reused_professional>0` nelle righe `Idealista private-only DB cache reuse`
    - assenza del vecchio pattern:
      - `unsupported operand type(s) for +=: 'int' and 'NoneType'`
      - `code=unexpected_error` su `idealista` a parita di condizioni
