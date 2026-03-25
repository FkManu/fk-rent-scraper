# ACTIVE_PATCH.md

## Patch corrente
Stabilizzazione VM / site guard + private_only

## Obiettivo
Chiudere gli intoppi prioritari emersi nei test VM lunghi senza allargare lo scope del prodotto:
- evitare cooldown percepiti come loop di protezione
- mantenere `idealista` su `msedge` reale quando disponibile
- ridurre le aperture dettaglio `private_only` che aumentano il rumore lato anti-bot
- garantire che la dist Windows parta davvero in GUI

## Contesto
- i fix del 2026-03-24 su `idealista` hanno migliorato la precisione, ma i run VM del 2026-03-25 hanno mostrato nuovi attriti reali
- la GUI bundle non partiva per packaging Tk incompleto
- il site guard poteva restare in cooldown ripetuto dopo `interstitial_datadome`, richiedendo reset manuale per sbloccarsi
- su bundle frozen `idealista` poteva fallire il launch `msedge`, degradare su `chrome` e prendere DataDome
- il secondo controllo `private_only` stava ancora aprendo troppi dettagli su annunci gia noti al DB

## Scope
- correggere il packaging GUI Windows includendo runtime Tcl/Tk e hook relativo
- rendere piu severa la logica di clear challenge e meno cieco il cooldown interstitial
- usare i browser reali installati per `msedge` e `chrome` quando presenti
- evitare `chromium` auto nel bundle frozen quando non e una scelta desiderabile
- introdurre un retry mirato con browser alternativo sui blocked outcome piu netti
- riusare il DB locale per tagliare i detail-check `private_only` sugli annunci gia noti
- lasciare log leggibili per distinguere site guard, browser routing e filtro privati

## Non-scope
- bypass aggressivi anti-bot
- retry cross-browser pesanti o illimitati sul singolo URL
- refactor ampio di tutto `live_fetch.py`
- nuove feature commerciali o UX non collegate al problema reale
- lavoro stealth dedicato per mascherare del tutto il browser come non gestito

## File principali coinvolti
- `src/affitto_v2/scrapers/live_fetch.py`
- `src/affitto_v2/db.py`
- `src/affitto_v2/main.py`
- `src/affitto_v2/gui_app.py`
- `src/affitto_v2/logging_live.py`
- `packaging/affitto_gui.spec`
- `packaging/runtime_hook_tk.py`
- `tests/test_private_only_and_logging.py`

## Done quando
- la GUI bundle parte in modo affidabile su Windows
- `idealista` non resta bloccato solo in `cooldown_active` fino al reset manuale
- nei log si vede l'uso dei browser installati e, se serve, il retry alternativo senza loop aggressivi
- i detail-check `private_only` si riducono in modo credibile dal secondo ciclo in poi grazie al DB cache reuse
- il summary `private_only` resta leggibile e misurabile
- `immobiliare` continua a lavorare anche se `idealista` entra in degrado

## Stato attuale
Implementazione completata nel workspace e nuova dist ricompilata; in attesa di validazione VM lunga sui nuovi fix combinati.

## Residui emersi
- `idealista` puo restare `partial_success_degraded` o `interstitial_datadome` anche senza loop del guard
- la modalita `annunci privati` resta best-effort: anche dopo il controllo dettaglio possono restare annunci `private_only_unknown`
- il browser puo ancora apparire "gestito" lato sito anche usando l'eseguibile reale installato
- prima del push su GitHub serve pulizia finale del working tree e selezione accurata dei file da versionare

## Idea da approfondire in seguito
Direzione possibile, ma non attiva e non prioritaria finche non chiudiamo la validazione VM lunga della patch corrente:

### Browser reale assistito via CDP
- introdurre una modalita opzionale separata dal path attuale `managed`
- collegamento a browser Chromium gia aperto tramite `connect_over_cdp("http://127.0.0.1:9222")`
- caso d'uso:
  - challenge iniziale da risolvere a mano
  - sessione gia autenticata o gia "calda"
  - recovery assistita nei casi in cui il browser gestito tende a degradare
- vincoli progettuali:
  - non usare come default
  - non chiudere il browser fisico dell'utente
  - non usare rotazione automatica canali o retry cross-browser aggressivi in questa modalita
  - richiedere profilo dedicato e browser avviato manualmente con remote debugging attivo
- first step raccomandato:
  - spike CLI-only
  - dataclass/handle esplicito per ownership di browser/context/page
  - nuova tab dedicata preferita rispetto al riuso implicito della tab utente, salvo override esplicito
