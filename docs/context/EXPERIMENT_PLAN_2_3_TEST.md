# EXPERIMENT_PLAN_2_3_TEST.md

## Scopo
Rendere `2.3_test` una linea misurabile fin dal primo step.

## Telemetria minima da conservare
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
- `profile_generation`
- `profile_age_sec`
- `runtime_disposition`
- `service_state`

## Risk budget minimo
Ogni run continua ad avere budget separati:
- `page_budget`
- `detail_budget`
- `identity_budget`
- `retry_budget`
- `cooldown_budget`
- `manual_assist_threshold`

## Regola di uscita minima
- nessuna patch si dichiara buona solo da lettura qualitativa
- ogni patch deve avere almeno:
  - una metrica primaria
  - una metrica di rischio
  - una finestra di osservazione
  - un rollback leggibile

## Esperimenti iniziali consigliati

### E0 - Parity freeze
- ipotesi: `2.3_test` parte con comportamento osservabile allineato a `2.2 stable`
- metrica primaria: parita di outcome tier e state transitions su run comparabili
- rischio: drift introdotto dal solo cutover locale

### E1 - `immobiliare adaptive prepare`
- ipotesi: ridurre `switch-to-list` e scroll non necessari abbassa il costo interazionale locale
- metrica primaria: riduzione di interazioni preparatorie inutili
- rischio: regressione di estrazione o peggioramento di `quality=good`

### E2 - Long block notification
- ipotesi: una notifica unica su blocco lungo migliora operativita senza aumentare rumore
- metrica primaria: leggibilita operativa / numero di alert utili
- rischio: alert duplicati o spam ad ogni ciclo

### E3 - Site-local soft mode
- ipotesi: ridurre per `1-2` cicli la pressione solo sul sito appena bloccato migliora recovery rate
- metrica primaria: tempo medio di recovery del sito colpito
- rischio: perdita eccessiva di throughput locale

### E4 - Orchestrator readability
- ipotesi: una scomposizione ulteriore piccola di `live_fetch.py` migliora review e manutenzione senza cambiare comportamento
- metrica primaria: riduzione responsabilita nel file orchestratore
- rischio: drift invisibile nel run loop

## Template minimo esperimento
Ogni esperimento deve dichiarare:
- ipotesi
- variabile cambiata
- metrica primaria
- metrica di rischio
- finestra di osservazione
- criterio di fallimento
- rollback

## Nota pratica
Il primo esperimento reale della linea dovrebbe essere sempre `E0 - Parity freeze`.

Senza quella verifica, ogni regressione futura diventa piu ambigua da leggere.
