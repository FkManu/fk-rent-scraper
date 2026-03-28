# ACTIVE_PATCH.md

## Patch corrente
Riallineamento post-patch su stabilita operativa, osservabilita e docs vive:
- registrato nello storico il nuovo hardening di render context deterministico cross-host
- registrato il nuovo `adaptive interaction pacing` nel percorso live
- registrato il nuovo bootstrap tecnico delle static resources nel setup browser
- aggiunti log dettagliati sui punti critici delle nuove patch
- review locale completa eseguita sulle patch recenti, inclusa la coerenza con `profile_generation`
- corretti i markdown che raccontavano ancora il ramo pre-render-context / pre-pacing / pre-bootstrap

## Obiettivo
Tenere allineata la linea `2.2.1 stable` dopo l'introduzione di render normalization deterministica, pacing adattivo, bootstrap static resources e logging di osservabilita, producendo la nuova dist per validazione VM.

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
- le patch del `2026-03-28` hanno aggiunto due layer tecnici nuovi:
  - render context deterministico via `init_script` globale
  - pacing asincrono Gamma sulle interazioni Playwright chiave
- la patch successiva ha aggiunto:
  - bootstrap tecnico degli endpoint infrastrutturali comuni nel setup del `BrowserContext`
- la patch finale ha aggiunto:
  - logging dettagliato sui punti critici dei nuovi helper
  - riallineamento del bundle Windows a `2.2.1 stable`
- la review ha confermato che:
  - `hard_block` continua a ruotare `profile_generation`
  - `interstitial_datadome` continua a restare cooldown/probe sulla stessa identity
- il rischio immediato non e il codice, ma lasciare documenti e review fermi al contratto precedente

## Scope
- riallineare doc vive e memoria al nuovo stato del ramo
- registrare nello storico:
  - render context deterministico
  - adaptive interaction pacing
  - static resources bootstrap
  - logging di osservabilita sui nuovi path
- chiudere una review completa di coerenza locale su:
  - `live_fetch.py`
  - `render_context.py`
  - test nuovi
  - note CLI/backend
- ricostruire la dist Windows `2.2.1 stable` per soak VM

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
- i doc vivi riflettono correttamente le patch del `2026-03-28`
- la memoria agente riporta:
  - render context deterministico
  - adaptive interaction pacing
  - static resources bootstrap
  - review locale senza bug bloccanti
- `cli_test_matrix.md` non menziona piu flag o alias rimossi
- nuova dist Windows `2.2.1 stable` ricostruita
