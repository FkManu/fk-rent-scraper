# HISTORY.md

## Patch chiuse che definiscono questa baseline
- Milestone 1 email / SMTP / GUI
- packaging Windows con primo bundle stabile
- anti-block adaptation / autohealing pragmatico
- drift detection minima + artifact parser/scraping
- consolidamento finale bundle/docs
- micro-fix GUI email validation/save flow
- preparazione concreta della linea privata `2.1_stable`
- taglio reale della nuova root privata `2.1_stable`
- observable autohealing / browser affinity per sito con validazione operativa su VM:
  - `idealista` -> `msedge`
  - `immobiliare` -> `chrome`
  - nessun `hard_block` osservato nei log lunghi revisionati
- fix packaging GUI Windows:
  - runtime Tcl/Tk incluso nel bundle
  - runtime hook aggiunto per `TCL_LIBRARY` e `TK_LIBRARY`
- hardening site guard su interstitial:
  - clear challenge piu severo
  - probe controllata durante il cooldown
  - reset state aggiornato
- hardening browser routing su bundle Windows:
  - uso dei browser reali installati per `msedge` e `chrome`
  - `chromium` non preferito in auto-mode frozen
  - retry mirato con browser alternativo sui blocked outcome
- precisione fetch / `annunci privati`:
  - filtro locale sugli annunci agenzia introdotto
  - review Idealista estesa al dettaglio annuncio
  - professionali nel detail-check riconosciuti anche via link profilo `/pro/`
  - pacing del secondo controllo reso piu conservativo lato anti-bot
  - riuso del DB per evitare detail-check inutili sugli annunci gia noti

## Stato attuale
- baseline stabile con packaging GUI riparato e routing browser/guard piu robusti
- patch viva ancora da chiudere sul piano operativo: validazione VM lunga di `idealista` e riduzione aperture dettaglio `private_only`
