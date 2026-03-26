# HANDOFF.md

## Stato attuale
- la cartella resta `2.2_test`, ma oggi va trattata come preview branch della linea successiva.
- `2.1_stable` resta la baseline shipping.
- il ramo non e piu solo una copia con docs nuove:
  - il motore live predefinito e ora `camoufox`
  - GUI e CLI sono riallineate al default `camoufox`
  - il servizio continuo `fetch-live-service` e il percorso operativo reale del ramo
- la differenza rispetto alla baseline shipping e ora concreta:
  - continuita di sessione per sito
  - profili persistenti isolati per sito
  - risk budget e stato di run
  - orchestrazione 24/7 con runtime condiviso

## Decisione di progetto
- `2.1_stable` resta il percorso shipping e supportabile
- `2.2_test` serve come preview disciplinata di cambi che toccano sessione, lifecycle lungo e precisione live
- il file `docs/risk_scoring_e_griglia_segnali_antibot.md` resta la pietra miliare interna della nuova linea

## Cosa e gia consolidato
- telemetria minima, `RiskBudget`, `RunRiskState` e stop trigger leggibili nel fetch live
- profili persistenti isolati per `site/channel`
- ownership esplicita della sessione con chiave `site|channel|profile`
- pool di sessioni isolate per owner con riuso same-site e pruning dello churn same-site
- servizio continuo sopra il one-shot:
  - cadenza da `runtime.cycle_minutes`
  - no overlap
  - `LiveServiceState`
  - runtime disposition minima `keep / recycle_site_slot / recycle_runtime / stop_service`
- GUI allineata al servizio reale:
  - `Run Once` -> `fetch-live-once`
  - periodico -> `fetch-live-service`

## Pivot backend
- backend browser operativo del ramo: `camoufox`
- root profili persistenti predefinita: `runtime/camoufox-profile`
- alias legacy `auto|firefox|chromium|chrome|msedge` mantenuti solo per compatibilita CLI e normalizzati a `camoufox`
- launch predefinito Camoufox:
  - `humanize=True`
  - `locale=it-IT`
  - `timezone=Europe/Rome`
  - `screen=1920x1080`
- setup Windows aggiornato per eseguire `python -m camoufox fetch`

## Stato operativo visto in VM il 2026-03-26
- file di riferimento: `docs/tmp_logs.md`
- soak test lungo del servizio continuo osservato da `11:59:51` a `16:55:19`
- cicli completati: `60`
- esiti osservati:
  - `healthy`: `240`
  - `degraded`: `0`
  - `blocked`: `0`
  - `cooling`: `0`
  - `assist_required`: `0`
  - `ERROR`: `0`
  - `Traceback`: `0`
- il servizio resta `stable` per tutta la finestra osservata
- `runtime disposition`:
  - `keep`: `56`
  - `recycle_site_slot`: `4`
  - nessun `recycle_runtime`
  - nessun `stop_service`

## Fix piu recente gia chiuso
- il collo di bottiglia piu evidente emerso dai log era il riuso nullo della memoria `private_only` per gli annunci professionali Idealista trovati dal detail-check
- il ramo salva ora questa evidenza in una cache negativa dedicata nel DB
- effetto atteso nel prossimo soak:
  - `reused_professional > 0`
  - riduzione o sparizione delle riaperture ripetute degli stessi `ad_id` professionali

## Lettura tecnica del soak
- `idealista` mostra continuita forte:
  - un solo profilo persistente iniziale
  - riuso same-site fino a `max_reuse_count=59`
  - nessun segnale di degrado o cooldown nei log osservati
- `immobiliare` lavora bene su `camoufox`, ma il ramo applica un recycle preventivo dello slot:
  - trigger osservato: `slot_reuse_cap`
  - soglia attuale in codice: `max_reuse_count=12`
  - il recycle e locale al sito e non degrada il servizio
- la distinzione locale vs globale del runtime sta quindi lavorando come previsto:
  - il runtime condiviso viene preservato
  - solo lo slot del sito caldo viene ricreato quando serve

## Limite aperto piu concreto
Il tema aperto non e oggi l'anti-bot del soak Camoufox, ma la precisione del filtro `private_only`.

Nei log osservati:
- il detail-check Idealista intercetta regolarmente annunci professionali
- il filtro locale scarta molte agenzie
- resta pero il warning costante:
  - `guarantee_private_only=False`
  - `allowed_without_agency_signal` tra `15` e `16` per ciclo osservato

Tradotto:
- la tenuta del motore e buona
- la garanzia "solo privati" non e ancora forte

## File da leggere per ripartire
- `README.md`
- `docs/risk_scoring_e_griglia_segnali_antibot.md`
- `docs/context/STRATEGY_2_2_TEST.md`
- `docs/context/STATE_MACHINE_2_2_TEST.md`
- `docs/context/EXPERIMENT_PLAN_2_2_TEST.md`
- `docs/context/STOP_TRIGGERS_2_2_TEST.md`
- `docs/context/PROMOTION_GATE_2_2_TEST.md`
- `docs/context/codex/ACTIVE_PATCH.md`
- `docs/tmp_logs.md`

## Prossimo passo sensato
- validare nel prossimo soak la nuova memoria `private_only`
- mantenere il soak del `2026-03-26` come baseline comparativa della preview
- chiarire se il recycle preventivo di `immobiliare`:
  - e la soglia giusta
  - va esteso ad altri siti
  - va documentato come policy stabile del ramo
- non aprire ancora CDP o nuove superfici UI finche questa base non resta leggibile e misurabile
