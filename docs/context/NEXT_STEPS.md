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
- rotazione profilo persistente guidata da `profile_generation`
- persona Camoufox persistente per generazione profilo
- modalita GUI `debugger` con artifact salvati in `runtime/debug` o `./debug` accanto alla dist
- render context deterministico cross-host
- adaptive interaction pacing su `goto/click/close`
- bootstrap static resources cache nel setup del `BrowserContext`

Per ricostruire il contesto minimo leggere prima:
1. `docs/risk_scoring_e_griglia_segnali_antibot.md`
2. `docs/context/HANDOFF.md`
3. `docs/context/STRATEGY_2_2_TEST.md`
4. `docs/context/STATE_MACHINE_2_2_TEST.md`
5. `docs/context/EXPERIMENT_PLAN_2_2_TEST.md`
6. `docs/context/STOP_TRIGGERS_2_2_TEST.md`
7. `docs/tmp_logs.md`

## Priorita ragionevoli da qui in avanti
1. Profile identity hardening:
- validare in soak la nuova `profile_generation`
- misurare se i `hard_block` reali su `immobiliare` si riducono dopo:
- reset reattivo su `hard_block`
- rotazione preventiva a `24h`
- verificare che la generazione nuova possa rilanciare al ciclo successivo senza restare bloccata dal cooldown del profilo precedente
- verificare che `idealista` resti stabile con sola rotazione reattiva su `hard_block`
   - non trasformare questa policy in regola globale identica per tutti i siti senza nuovi dati
2. Review soak e stabilita per-sito:
   - trattare il review del `2026-03-27` come nuova baseline breve di riferimento:
     - `19` cicli osservati
     - `17` completamente `healthy`
     - `2` `hard_block`
     - `2` recovery su nuova `profile_generation`
   - non leggere questo soak come "immobiliare molto peggiore di idealista":
     - in questa finestra entrambi hanno preso un solo `hard_block`
     - entrambi hanno recuperato
   - usare i prossimi soak per misurare:
     - block rate per sito
     - tempo medio tra block
     - durata media delle `profile_generation`
     - recovery rate
3. Prepare phase di `immobiliare`:
   - aprire una slice piccola `immobiliare adaptive prepare`
   - ridurre il `switch-to-list` ai casi necessari
   - rendere lo scroll condizionale:
     - fermarsi appena i risultati sono sufficienti
     - fermarsi se il conteggio non cresce
     - evitare scroll inutile quando la lista e gia pronta
   - non attribuire automaticamente i block al solo scroll:
     - i `hard_block` del soak passano da DataDome gia in `after_goto`
4. Precisione `private_only`:
   - verificare in soak che la nuova memoria negativa venga davvero riusata
   - osservare `reused_professional`
   - confermare la riduzione delle riaperture ripetute sugli stessi `ad_id`
   - ridurre `allowed_without_agency_signal`
   - capire se il problema residuo e piu forte su `immobiliare`, su `idealista`, o su entrambi
   - aggiungere segnali forti solo dove migliorano la precisione senza rialzare troppo il costo interazionale
   - mantenere la distinzione tra:
     - filtro URL lato sito
     - filtro hard locale del parser/pipeline
5. Camoufox-only cleanup:
   - chiudere formalmente `Milestone 3 / Real Browser Assisted` come ipotesi dismessa
   - mantenere la CLI su `auto|camoufox`
   - non reintrodurre alias legacy o rotazioni multi-browser nel percorso standard
   - non tenere nel core nuovi percorsi "assistiti" che non fanno piu parte della strategia reale
6. Refactor prudente di `live_fetch.py`:
   - evitare rewrite ampia
   - estrarre prima moduli meccanici e a basso rischio:
     - `profile_identity.py`
     - `browser_runtime.py`
     - `site_guard.py`
     - `debug_artifacts.py`
   - lasciare il loop orchestrativo principale in `live_fetch.py` finche i soak non restano stabili
   - mantenere invariati:
     - shape dei log
     - contract del run report
     - comportamento dei parser sito
7. Orchestrazione 24/7:
   - promuovere il soak del `2026-03-26` a baseline comparativa del ramo
   - validare se i recycle locali periodici su `immobiliare` restano necessari dopo la nuova rotazione profilo
   - raffinare la policy del runtime condiviso solo dopo confronto su run comparabili
   - tenere separati:
     - `recycle_site_slot`
     - `recycle_runtime`
     - `stop_service`
8. Stable release hygiene:
   - mantenere ordinati i markdown vivi di contesto
   - evitare duplicazioni tra `README`, `HANDOFF`, `NEXT_STEPS` e `codex/OUTPUT_CURRENT`
   - trattare `dist/` come artefatto build locale, non come contenuto repo
9. Osservabilita residua:
   - usare la modalita GUI `debugger` come strumento standard di soak quando il guard scatta
   - valutare osservabilita aggiuntiva su network/TLS/device checks solo se i log attuali restano ambigui
10. Notifiche operative:
   - aggiungere una notifica singola quando un sito entra in blocco lungo `>= 1h`
   - includere nel messaggio:
     - `site`
     - `reason`
     - `profile_generation`
     - `next_attempt_local`
   - inviare una seconda notifica solo alla recovery del sito
11. Soft mode locale post-block:
   - evitare di allungare la cadence globale del servizio
   - valutare invece un `soft mode` per `1-2` cicli solo sul sito che ha appena preso `hard_block`
   - obiettivo:
     - ridurre pressione locale
     - non perdere troppa operativita complessiva
12. Validazione delle patch del `2026-03-28`:
   - verificare in soak che il render context deterministico non introduca drift visivo o regressioni di parsing
   - verificare che il nuovo pacing Gamma non degradi inutilmente throughput o cadence del servizio
   - verificare che il bootstrap static resources non alteri il tasso di block o il tempo di setup per sito
   - osservare in log:
     - tempi medi ciclo
     - eventuale accumulo anomalo di `cycle_delay_sec`
     - differenze reali tra siti dopo il pacing pre-`goto` e pre-`click`
     - tempi di launch/session setup dopo il bootstrap tecnico `gstatic/google/cloudflare`

## Cose da evitare
- non usare `2.2_test` per bugfix generici della baseline shipping
- non riaprire subito la discussione multi-browser: nel ramo oggi il backend reale e `camoufox`
- non riaprire `Milestone 3` come fallback implicito se non riemerge un bisogno reale da dati nuovi
- non confondere "browser slot recycle" con "profile identity rotate"
- non promuovere a "problema motore" una questione che oggi sembra soprattutto di precisione `private_only` o di errore interno
- non fare patchone che mischia parser, packaging e session strategy
- non aprire patch orientate a spoofing avanzato di fingerprint hardware/GPU o rete oltre il perimetro deterministico gia codificato
- non introdurre pre-heating su domini esterni
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
  - rotazione profilo reattiva su `hard_block`
  - rotazione preventiva a `24h` su `immobiliare`
  - persona Camoufox persistente per generazione
  - riduzione churn e retry impulsivi
  - telemetria minima del run
  - orchestrazione continua del servizio
  - runtime condiviso tra cicli del servizio
  - allineamento esplicito tra `run_state` e `service_state`
  - runtime disposition minima del servizio
  - soak VM lungo comparabile con servizio `stable`
  - modalita GUI `debugger` con artifact bundle-aware
  - render context deterministico cross-host
  - pacing adattivo sulle interazioni chiave
  - bootstrap static resources cache nel setup sessione
- coperto solo in parte:
  - precisione forte del filtro `private_only`
  - refactor di `live_fetch.py` in moduli piu piccoli
- non ancora coperto:
  - segnali rete/TLS
  - JS runtime / device checks come osservabilita dedicata
  - evidenza comparabile abbastanza lunga per promotion gate
