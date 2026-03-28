# REVIEW_CURRENT.md

## Patch corrente
Render context deterministico + adaptive interaction pacing + static resources bootstrap + riallineamento docs

## Stato review
Patch reviewata su base locale.

## Focus atteso della review
- wiring dell'`init_script` globale sul `BrowserContext`
- coerenza del nuovo pacing asincrono prima di `goto/click/close`
- coerenza del bootstrap tecnico `gstatic/google/cloudflare` nel setup della sessione
- compatibilita delle patch recenti con la rotate del profilo su `hard_block`
- compatibilita del contratto `camoufox-only` nei doc e nei comandi
- nessun drift tra storico patch, doc vive e comportamento reale del codice

## Esito sintetico
- nessun bug bloccante emerso nelle patch nuove
- review di coerenza completata su:
  - `src/affitto_v2/scrapers/live_fetch.py`
  - `src/affitto_v2/scrapers/render_context.py`
  - `tests/test_render_context.py`
  - `tests/test_interaction_pacing.py`
- review funzionale completata sul binding:
  - `hard_block` -> rotate `profile_generation`
  - `interstitial_datadome` -> cooldown/probe senza rotate
- bootstrap static resources coerente col setup del nuovo `BrowserContext` e non interferente con l'owner della sessione
- unico drift trovato: documentazione CLI/contesto ancora ferma al contratto precedente; riallineata
- copertura locale aggiornata; suite `81` test `OK`
- residuo principale: validazione soak del costo reale di pacing + bootstrap e dell'assenza di regressioni visuali cross-host
