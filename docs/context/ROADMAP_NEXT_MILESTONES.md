# ROADMAP_NEXT_MILESTONES.md

## Scopo
Definire la roadmap operativa della root `2.2_test`.

## Funzione della root
`2.2_test` non nasce per fare shipping.
Oggi va trattata come preview branch della prossima linea live e serve a validare un motore meno rumoroso e piu centrato su:
- session continuity
- pacing prudente
- identita stabile per sito
- recovery assistita

## Fase corrente
La fase corrente non e piu "foundation".
E `preview hardening`:
- soak reali comparabili
- precisione `private_only`
- packaging coerente
- docs vive non contraddittorie

## Milestone 0 - Foundation

### Obiettivo
Creare la base comune misurabile prima di ogni esperimento serio.

### Deliverable
- telemetria minima condivisa con `2.1_stable`
- risk budget esplicito
- state machine documentata
- stop trigger policy documentata
- active patch coerente

### KPI minimi
- esistenza dei campi telemetrici comuni
- esistenza del risk budget in codice o configurazione
- esistenza degli state labels supportati dal ramo
- esistenza di trigger leggibili per `cooldown`, `frozen` e `assist_required`

### Stato
Chiusa.

## Milestone 1 - Session Model Reset

### Obiettivo
Passare da profili e sessioni implicite a ownership esplicita per sito.

### Deliverable
- profilo persistente per sito
- fine del riuso implicito della stessa sessione tra siti
- browser/context/page ownership piu chiara

### Stato corrente
- primo slice gia aperto:
  - profilo persistente isolato per `site/channel`
  - chiave di ownership di sessione esplicita nel live loop
- secondo slice gia aperto:
  - pool di sessioni isolate per owner
  - riuso esplicito solo same-owner
- terzo slice gia aperto:
  - pruning same-site quando cambia owner
  - una sola identita viva per sito
- quarto slice gia aperto:
  - churn same-site trattato come segnale di rischio
  - escalation fino a `assist_required` sul churn ripetuto

### KPI minimi
- `identity_switch_per_run`
- `same_site_profile_reuse_rate`
- `cross_site_session_reuse_count`

### Stato
In gran parte chiusa sul perimetro attuale del ramo.

## Milestone 1.5 - Continuous Scheduler

### Obiettivo
Portare la cadenza 24/7 nel livello giusto, sopra il fetch one-shot e senza overlap.

### Deliverable
- comando `fetch-live-service`
- policy esplicita di cadence / overrun
- summary log sul backlog operativo

### Stato corrente
- primo slice gia aperto:
  - `fetch-live-service` introdotto in `src/affitto_v2/main.py`
  - cadenza dal `runtime.cycle_minutes`
  - cap operativo separato via `--cycle-max-minutes`
  - supporto a `--max-cycles` per soak test bounded
- secondo slice gia aperto:
  - stato minimo del servizio continuo
  - `warmup`, `stable`, `degraded`, `assist_required`
  - stop pulito su failure ripetuti del servizio
- terzo slice gia aperto:
  - runtime condiviso cross-cycle per `fetch-live-service`
  - riuso del pool di sessioni tra cicli consecutivi
  - chiusura pulita del runtime condiviso a fine servizio
- quarto slice gia aperto:
  - report di run dal fetch live
  - uso di `run_state` e `assist_required` nel servizio continuo
  - escalation del servizio su run degradati ripetuti
- quinto slice gia aperto:
  - runtime disposition minima del servizio
  - recycle del solo site slot su `cooldown/blocked`
  - recycle totale del runtime su failure tecnico del ciclo
- sesto slice gia aperto:
  - contesto per-sito nel run report
  - recycle totale del runtime anche su degrado multi-sito nello stesso ciclo

### KPI minimi
- `cycle_delay_sec`
- `overrun_count`
- `missed_cycle_count`
- `failure_count`
- `service_assist_required_rate`

### Stato
Chiusa come base operativa; resta hardening del comportamento in soak lunghi.

## Milestone 2 - Silent Risk Policy

### Obiettivo
Ridurre il rumore strutturale del run.

### Deliverable
- no retry cross-browser immediato di default
- budget chiari su pagine, dettagli e retry
- stop pulito quando il costo interazionale sale

### KPI minimi
- `detail_touches_per_run`
- `detail_touches_per_new_listing`
- `retry_per_site_per_run`
- `challenge_seen_per_100_runs`

### Stato
In corso.
Il fix piu recente e la memoria negativa `private_only` per i professionali Idealista.

## Milestone 3 - Real Browser Assisted

### Obiettivo
Aprire modalita assistite senza farle diventare default.

### Deliverable
- `cdp_bootstrap`
- `cdp_recovery`
- trigger separati
- log separati

### KPI minimi
- `cdp_bootstrap_success_rate`
- `cdp_recovery_success_rate`
- `assist_required_rate`

### Stato
Non aperta operativamente.

## Milestone 4 - Promotion Gate

### Obiettivo
Promuovere solo cio che migliora davvero.

### Deliverable
- confronto comparabile con `2.1_stable`
- nota rischi residui
- rollback chiaro

### Criterio di uscita
Una patch puo muoversi verso `2.1_stable` solo se:
- migliora una metrica chiave
- non peggiora l'altro sito
- non aumenta support cost
- non richiede nuovo rituale manuale

### Stato
Ancora futura: prima serve consolidare la preview.
