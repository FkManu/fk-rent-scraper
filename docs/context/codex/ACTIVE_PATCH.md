# ACTIVE_PATCH.md

## Patch corrente
Riallineamento post-refactor su struttura, review e docs vive:
- review locale completa del refactor `browser/guard/sites`
- registrazione nello storico della nuova session policy per sito
- registrazione della state machine tabellare estratta
- registrazione della disposition esplicita del profilo persistente su `hard_block`
- chiusura dei drift post-refactor:
  - `accept_cookies` policy-aware per sito
  - `guard_jitter_*` reintegrati come clipping del Gamma pacing
- correzione dei markdown che raccontavano ancora `live_fetch.py` come monolite e il refactor come prossimo step

## Obiettivo
Tenere allineata la linea `2.2.2 refactorizzata` dopo il refactor strutturale del motore live, fissando nello storico la nuova architettura, la chiusura dei drift e la nuova release.

## Contesto
- `2.2_test` deriva da `2.1_stable`, ma oggi e gia divergente nel motore live
- il soak VM del `2026-03-26` ha confermato una buona tenuta del backend `camoufox`
- il review dei log del `2026-03-27` ha mostrato un vero `hard_block` su `immobiliare` dopo oltre `44h` di session age
- il run mostrava pero un cooldown ancora efficace sul ciclo successivo, anche dopo rotate di `profile_generation`
- profile rotation, persona persistente e GUI debugger sono gia state chiuse
- l'osservabilita del guard e stata estesa per rendere leggibili rotate e generazioni attive
- il review del `2026-03-27` mostra che:
  - `idealista` e `immobiliare` hanno preso un solo `hard_block` ciascuno
  - entrambi hanno recuperato su `gen-001`
  - il fix su `cooldown_profile_generation` ha funzionato
- dopo le patch del `2026-03-28` il ramo e stato rifattorizzato il `2026-03-30`:
  - `browser/session_policy.py`
  - `browser/bootstrap.py`
  - `browser/factory.py`
  - `guard/state_machine.py`
  - `sites/idealista.py`
  - `sites/immobiliare.py`
- la review ha confermato che:
  - `hard_block` continua a ruotare `profile_generation`
  - `interstitial_datadome` continua a restare cooldown/probe sulla stessa identity
  - il vecchio profilo persistente viene ora distrutto in modo esplicito dopo la rotate su `hard_block`
- i due drift reali emersi nella prima review sono stati corretti nel passo successivo:
  - pacing cookie riallineato alla policy del sito corrente
  - `guard_jitter_*` reintegrati come clipping del Gamma pacing
- il rischio immediato e lasciare documenti e handoff fermi al contratto pre-refactor

## Scope
- riallineare doc vive e memoria al nuovo stato del ramo
- registrare nello storico:
  - session policy per sito
  - state machine tabellare
  - modularizzazione `browser/guard/sites`
  - destruction del profilo persistente su `hard_block`
  - clipping operativo del Gamma pacing tramite `guard_jitter_*`
- chiudere una review completa di coerenza locale su:
  - `live_fetch.py`
  - `render_context.py`
  - test nuovi
  - note CLI/backend

## Non-scope
- niente refactor strutturale di `live_fetch.py` prima del soak
- niente riapertura di una strategia multi-browser
- niente geolocation/proxy spoof non legati a un IP reale
- niente espansione aperta del fingerprint spoof oltre il set deterministico gia codificato nel render context
- niente jitter artificiale di rete sugli asset o pre-heating su domini esterni
- niente pacing artificiale fuori dalle interazioni Playwright esplicitamente presidiate
- niente commit di runtime, log o dist temporanee
- niente bypass aggressivi

## File principali coinvolti
- `docs/cli_test_matrix.md`
- `docs/context/HANDOFF.md`
- `docs/context/NEXT_STEPS.md`
- `docs/context/codex/OUTPUT_CURRENT.md`
- `docs/context/codex/ACTIVE_PATCH.md`
- `docs/context/codex/HISTORY.md`
- `src/affitto_v2/scrapers/live_fetch.py`
- `src/affitto_v2/scrapers/render_context.py`
- `tests/test_render_context.py`
- `tests/test_interaction_pacing.py`
- `tests/test_static_resource_bootstrap.py`
- `scripts/build_windows_bundle.ps1`

## Done quando
- i doc vivi riflettono correttamente il refactor del `2026-03-30`
- la memoria agente riporta:
  - session policy per sito
  - state machine tabellare
  - modularizzazione `browser/guard/sites`
  - review locale con drift chiusi e suite aggiornata
- `HANDOFF` e `NEXT_STEPS` non raccontano piu il refactor come lavoro futuro
