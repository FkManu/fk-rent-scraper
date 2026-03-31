# EXPERIMENT_PLAN_2_2_TEST.md

## Scopo
Rendere `2.2_test` un laboratorio misurabile.

## Telemetria minima condivisa tra `2.1_stable` e `2.2_test`
- `site`
- `browser_mode`
- `channel_label`
- `identity_switch`
- `session_age`
- `detail_touch_count`
- `retry_count`
- `risk_pause_reason`
- `outcome_tier`
- `outcome_code`
- `cooldown_origin`
- `manual_assist_used`
- `state_transition`
- `assist_entry_mode`

## Telemetria minima del servizio continuo
- `cycle_delay_sec`
- `cycle_elapsed_sec`
- `failure_count`
- `overrun_count`
- `missed_cycle_count`
- `service_state`
- `service_assist_reason`

## Risk budget minimo
Ogni run deve avere budget separati:
- `page_budget`
- `detail_budget`
- `identity_budget`
- `retry_budget`
- `cooldown_budget`
- `manual_assist_threshold`

## Definizioni operative minime
- `page_budget`: massimo numero di listing pages visitabili nel run
- `detail_budget`: massimo numero di aperture dettaglio nel run
- `identity_budget`: massimo numero di switch browser/context/profile nel run
- `retry_budget`: massimo numero di retry consentiti sul sito nel run
- `cooldown_budget`: numero massimo di ingressi in cooldown prima del freeze
- `manual_assist_threshold`: soglia oltre cui il run richiede `assist_required`

## KPI minimi per milestone

### Milestone 0
- esistenza della telemetria minima comune
- esistenza del risk budget
- esistenza della state machine documentata
- esistenza dei trigger di stop documentati

### Milestone 1
- `identity_switch_per_run`
- `same_site_profile_reuse_rate`
- `cross_site_session_reuse_count`

### Milestone 1.5
- `cycle_delay_sec`
- `overrun_count`
- `missed_cycle_count`
- `failure_count`
- `service_assist_required_rate`

### Milestone 2
- `detail_touches_per_run`
- `detail_touches_per_new_listing`
- `retry_per_site_per_run`
- `challenge_seen_per_100_runs`

### Milestone 3
- `cdp_bootstrap_success_rate`
- `cdp_recovery_success_rate`
- `assist_required_rate`

## Soglie di uscita minime
- nessuna milestone si chiude con solo impressioni qualitative
- ogni milestone deve avere almeno una metrica primaria e una metrica di rischio
- per promuovere una patch servono run comparabili raccolti prima e dopo il cambio

## Template esperimento
Ogni esperimento deve definire:
- ipotesi
- variabile cambiata
- metrica attesa
- finestra di osservazione
- criterio di fallimento
- rollback

Ogni esperimento dovrebbe anche dichiarare:
- sito o siti coinvolti
- rischio principale che prova a ridurre
- budget che puo consumare
- criterio di stop anticipato

## Esperimenti iniziali consigliati

### E1 - Per-site profile isolation
- ipotesi: profili per sito riducono rumore rispetto al riuso implicito

### E2 - No immediate cross-browser retry
- ipotesi: rimuovere il retry cross-browser nello stesso run riduce rumore

### E3 - Detail budget hard cap
- ipotesi: limitare i detail opens riduce pressione sul risk score

### E4 - Assisted recovery split
- ipotesi: distinguere `cdp_bootstrap` da `cdp_recovery` riduce ambiguita e costo supporto

### E5 - Continuous scheduler service state
- ipotesi: distinguere backlog, overrun e failure ripetuti migliora la stabilita 24/7 e la leggibilita dei stop

### E6 - Run state to service state alignment
- ipotesi: usare il `run_state` reale del fetch live nel servizio riduce falsi verdi e rende piu onesti gli stop del loop continuo
