# OUTPUT_CURRENT.md

## Patch corrente
`2.3-patch-04` - Autostart servizio continuo solo da boot Windows

## Stato
Patch applicata. Suite test verde.

Backend operativo: `camoufox`.
State machine, guard, parser, `private_only`: invariati.

## Implementazione eseguita

### C1 - Autostart servizio continuo
- `gui_app.py`
  - aggiunta checkbox dipendente "Avvia anche il servizio continuo al boot"
  - stato GUI esteso con `autostart_service_enabled`
  - il wrapper Startup `.vbs` esporta `AFFITTO_V2_GUI_AUTOSTART=1`
  - la GUI avvia il servizio automaticamente solo se:
    - e stata lanciata dal boot Windows tramite autostart
    - `autostart_enabled=True`
    - `autostart_service_enabled=True`
  - le aperture manuali della GUI non avviano mai il servizio da sole
  - una vecchia `live_service.stop` viene rimossa solo nel percorso boot-autostart
  - configurazione invalida durante l'avvio automatico: log warning e nessun dialog bloccante

## Test
- `pytest -q` -> `100 passed`
- test aggiunti/aggiornati su:
  - marker env `AFFITTO_V2_GUI_AUTOSTART`
  - contenuto VBS aggiornato
  - checkbox dipendente quando l'autostart GUI e off
  - start automatico del servizio solo nel launch da boot
  - cleanup della stop-flag stale
  - persistenza corretta del flag servizio

## Nota residua
- manca verifica reale post-reboot su Windows per confermare il launch condizionato del servizio
- `A2` resta comunque in attesa di soak operativo diurno/notturno
