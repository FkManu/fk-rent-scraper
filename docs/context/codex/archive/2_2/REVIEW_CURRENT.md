# REVIEW_CURRENT.md

## Patch corrente
Refactor strutturale di `live_fetch.py` con Separation of Concerns:
- `browser/session_policy.py`
- `browser/bootstrap.py`
- `browser/factory.py`
- `guard/state_machine.py`
- `sites/idealista.py`
- `sites/immobiliare.py`
- `render_context.py` reso policy-driven
- launch path con log `fresh` vs `reused`

## Stato review
Patch reviewata su base locale dopo il refactor.

## Focus atteso della review
- correttezza dell'estrazione dei nuovi moduli senza regressioni di contratto
- coerenza della site-policy tra pacing, user-agent e hardware mimetics
- traduzione tabellare della state machine di run
- distruzione del profilo persistente sul ramo `blocked/hard_block`
- osservabilita del launch path `fresh` vs `reused`
- assenza di drift tra docs vive e struttura reale del codice

## Esito sintetico
- nessun bug bloccante emerso nel refactor
- i due drift non bloccanti emersi nella prima review sono stati chiusi:
  - `_accept_cookies_if_present()` ora e policy-aware per sito
  - `guard_jitter_min_sec` e `guard_jitter_max_sec` sono ora integrati come clipping del Gamma pacing
- ulteriore scomposizione strutturale completata senza regressioni osservate:
  - `core_types.py`
  - `guard/store.py`
  - `browser/persona.py`
  - `debug_artifacts.py`
- `live_fetch.py` mantiene i nomi privati gia usati dai test come layer di compatibilita locale
- review di coerenza completata su:
  - `src/affitto_v2/scrapers/core_types.py`
  - `src/affitto_v2/scrapers/debug_artifacts.py`
  - `src/affitto_v2/scrapers/guard/store.py`
  - `src/affitto_v2/scrapers/browser/persona.py`
  - `src/affitto_v2/scrapers/live_fetch.py`
  - `src/affitto_v2/scrapers/render_context.py`
  - `src/affitto_v2/scrapers/browser/*`
  - `src/affitto_v2/scrapers/guard/state_machine.py`
  - `src/affitto_v2/scrapers/sites/*`
  - `tests/test_render_context.py`
  - `tests/test_interaction_pacing.py`
  - `tests/test_session_policy_and_state_machine.py`
- review funzionale completata sul binding:
  - `hard_block` -> rotate `profile_generation` -> cooldown generazione vecchia -> distruzione profilo persistente vecchio
  - `interstitial_datadome` -> cooldown/probe senza rotate
- suite locale aggiornata; `85` test `OK`
- residuo principale:
  - soak VM per confermare che `rotate + destroy` non introduca churn eccessivo
  - prossima slice consigliata: estrarre da `live_fetch.py` il challenge/page flow e la decomposizione di `fetch_live_once()`
