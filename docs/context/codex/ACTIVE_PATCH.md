# ACTIVE_PATCH.md

## Patch corrente
`2.3-patch-04` - Autostart servizio continuo solo da boot Windows

## Obiettivo
Permettere l'avvio automatico del servizio continuo solo quando la GUI viene aperta dal boot Windows tramite autostart, senza far partire il servizio nelle aperture manuali.

## Scope
- `src/affitto_v2/gui_app.py`
  - nuova checkbox dipendente `autostart_service_enabled`
  - autostart GUI salva lo stato anche del servizio
  - marker esplicito `AFFITTO_V2_GUI_AUTOSTART=1` nel wrapper Startup `.vbs`
  - start automatico del servizio solo nel ramo "boot Windows via autostart"
  - rimozione della stop-flag stale solo nel ramo boot-autostart
  - avvio non interattivo senza dialog bloccanti se la config e invalida
- `tests/test_private_only_and_logging.py`
  - copertura dedicata per marker env, checkbox dipendente e start automatico condizionato

## Non-scope
- nessuna variazione a scheduler, guard, parser, `private_only`
- nessun cambio al comportamento delle aperture manuali della GUI
- nessuna variazione ai criteri di stop del servizio continuo

## Invarianti preservati
- checkbox GUI e start/stop manuali invariati
- `autostart_service_enabled` e operativo solo se `autostart_enabled=True`
- assenza di `APPDATA` -> warning invariato
- bundle e sorgente continuano a usare lo stesso launcher applicativo di prima

## Stato
COMPLETO lato codice e test.
In attesa di verifica reale post-reboot su Windows.
