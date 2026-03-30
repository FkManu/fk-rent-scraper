# ACTIVE_PATCH.md

## Patch corrente
Scomposizione conservativa ulteriore di `live_fetch.py` + riallineamento docs:
- estrazione dei contratti dati in `core_types.py`
- estrazione del guard store in `guard/store.py`
- estrazione di persona/profili/session identity in `browser/persona.py`
- estrazione degli artifact helper in `debug_artifacts.py`
- mantenimento di compatibilita dei nomi privati esposti ai test
- aggiornamento della memoria di progetto sulla nuova mappa del codice

## Obiettivo
Continuare la scomposizione di `live_fetch.py` senza alterare il comportamento della `2.2.2 refactorizzata`, fissando nei markdown cosa e gia uscito dal file e quali blocchi restano ancora da isolare.

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
- la nuova review strutturale mostra che `live_fetch.py` resta ancora pesante soprattutto in:
  - challenge/page flow
  - extraction quality + parser drift
  - orchestrazione di `fetch_live_once()`
- il rischio immediato e perdere traccia della scomposizione gia fatta e riaprire patch casuali sul file monolite

## Scope
- estrarre componenti non orchestrativi da `live_fetch.py`
- lasciare invariato il contratto dei nomi privati gia usati dai test
- aggiornare i markdown di contesto con la nuova mappa:
  - `core_types.py`
  - `guard/store.py`
  - `browser/persona.py`
  - `debug_artifacts.py`
- documentare quali blocchi restano ancora nel file orchestratore

## Non-scope
- niente refactor comportamentale del run loop
- niente variazioni a policy anti-bot, pacing o trigger del guard
- niente riapertura di una strategia multi-browser
- niente geolocation/proxy spoof non legati a un IP reale
- niente espansione aperta del fingerprint spoof oltre il set deterministico gia codificato nel render context
- niente jitter artificiale di rete sugli asset o pre-heating su domini esterni
- niente pacing artificiale fuori dalle interazioni Playwright esplicitamente presidiate
- niente commit di runtime, log o dist temporanee
- niente bypass aggressivi

## File principali coinvolti
- `docs/context/HANDOFF.md`
- `docs/context/NEXT_STEPS.md`
- `docs/context/codex/OUTPUT_CURRENT.md`
- `docs/context/codex/ACTIVE_PATCH.md`
- `docs/context/codex/HISTORY.md`
- `src/affitto_v2/scrapers/core_types.py`
- `src/affitto_v2/scrapers/debug_artifacts.py`
- `src/affitto_v2/scrapers/guard/store.py`
- `src/affitto_v2/scrapers/browser/persona.py`
- `src/affitto_v2/scrapers/live_fetch.py`
- `tests/test_private_only_and_logging.py`
- `tests/test_session_policy_and_state_machine.py`

## Done quando
- i doc vivi riportano anche questa seconda slice di scomposizione
- `live_fetch.py` non contiene piu:
  - contratti dati
  - persistenza guard state
  - persona/profili/session identity
  - helper artifact/debug
- la suite locale resta verde dopo l'estrazione
