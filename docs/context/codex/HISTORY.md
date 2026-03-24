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
- precisione fetch / `annunci privati` in avanzamento:
  - filtro locale sugli annunci agenzia gia introdotto
  - review Idealista estesa al dettaglio annuncio
  - professionali nel detail-check riconosciuti anche via link profilo `/pro/`
  - pacing del secondo controllo reso piu conservativo lato anti-bot

## Stato attuale
- baseline stabile con patch anti-bot/browser reviewata in pratica
- prossima area di lavoro: precisione fetch / esclusione annunci agenzia quando serve una modalita `annunci privati`
