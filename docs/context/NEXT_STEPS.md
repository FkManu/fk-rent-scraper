# NEXT_STEPS.md

## Punto di partenza
Questa root `2.2_test` non e piu una foundation embrionale.
Va trattata come linea `2.2 stable` ancora in hardening operativo.

Oggi il ramo ha gia:
- backend operativo predefinito `camoufox`
- GUI e CLI allineate allo stesso backend
- servizio continuo reale sopra `fetch-live-once`
- soak VM lungo del `2026-03-26` con esito molto pulito
- fix del `2026-03-27` sul cooldown artificiale `idealista` da `detail_touch_count`

Per ricostruire il contesto minimo leggere prima:
1. `docs/risk_scoring_e_griglia_segnali_antibot.md`
2. `docs/context/HANDOFF.md`
3. `docs/context/STRATEGY_2_2_TEST.md`
4. `docs/context/STATE_MACHINE_2_2_TEST.md`
5. `docs/context/EXPERIMENT_PLAN_2_2_TEST.md`
6. `docs/context/STOP_TRIGGERS_2_2_TEST.md`
7. `docs/tmp_logs.md`

## Priorita ragionevoli da qui in avanti
1. Precisione `private_only`:
   - verificare in soak che la nuova memoria negativa venga davvero riusata
   - osservare `reused_professional`
   - confermare la riduzione delle riaperture ripetute sugli stessi `ad_id`
   - ridurre `allowed_without_agency_signal`
   - capire se il problema residuo e piu forte su `immobiliare`, su `idealista`, o su entrambi
   - aggiungere segnali forti solo dove migliorano la precisione senza rialzare troppo il costo interazionale
   - mantenere la distinzione tra:
     - filtro URL lato sito
     - filtro hard locale del parser/pipeline
2. Guard readability / session model:
   - consolidare l'ownership di browser/context/page sul lifecycle lungo
   - mantenere `cross_site_session_reuse_count` a zero salvo decisione esplicita contraria
   - introdurre una lettura piu chiara del perche uno slot venga riciclato
   - distinguere meglio `unexpected_error` dai blocchi sito veri
   - decidere se il recycle preventivo same-site debba restare solo su `immobiliare` o diventare policy piu generale
3. Orchestrazione 24/7:
   - promuovere il soak del `2026-03-26` a baseline comparativa del ramo
   - validare se i recycle locali periodici su `immobiliare` sono fisiologici o conservativi oltre il necessario
   - raffinare la policy del runtime condiviso solo dopo confronto su run comparabili
   - tenere separati:
     - `recycle_site_slot`
     - `recycle_runtime`
     - `stop_service`
4. Silent risk policy:
   - mantenere niente retry cross-browser immediato di default
   - preservare il budget basso di identita
   - non allargare i budget solo per inseguire qualche listing in piu
5. Stable release hygiene:
   - mantenere ordinati i markdown vivi di contesto
   - evitare duplicazioni tra `README`, `HANDOFF`, `NEXT_STEPS` e `codex/OUTPUT_CURRENT`
   - trattare `dist/` come artefatto build locale, non come contenuto repo
6. Solo dopo i punti sopra:
   - `cdp_bootstrap`
   - `cdp_recovery`
   - osservabilita avanzata su network/TLS/device checks

## Cose da evitare
- non usare `2.2_test` per bugfix generici della baseline shipping
- non riaprire subito la discussione multi-browser: nel ramo oggi il backend reale e `camoufox`
- non promuovere a "problema motore" una questione che oggi sembra soprattutto di precisione `private_only` o di errore interno
- non fare patchone che mischia parser, packaging e session strategy
- non committare log, runtime, build temporanei o dump locali

## Regola pratica
Ogni patch di `2.2_test` deve:
- ridurre rumore
oppure
- aumentare continuita
oppure
- migliorare in modo misurabile la precisione `private_only`

Se non fa nessuna di queste cose, probabilmente non appartiene a questa root.

## Copertura attuale sintetica
- coperto bene:
  - continuita di sessione per sito
  - backend `camoufox` come percorso operativo unico del ramo
  - riduzione churn e retry impulsivi
  - telemetria minima del run
  - orchestrazione continua del servizio
  - runtime condiviso tra cicli del servizio
  - allineamento esplicito tra `run_state` e `service_state`
  - runtime disposition minima del servizio
  - soak VM lungo comparabile con servizio `stable`
- coperto solo in parte:
  - policy documentata del recycle preventivo per sito
  - precisione forte del filtro `private_only`
  - recovery assistita
- non ancora coperto:
  - segnali rete/TLS
  - JS runtime / device checks come osservabilita dedicata
  - percorso `cdp_bootstrap` / `cdp_recovery` operativo
