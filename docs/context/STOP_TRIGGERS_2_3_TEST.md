# STOP_TRIGGERS_2_3_TEST.md

## Scopo
Definire i trigger minimi di stop, freeze o assistenza della linea `2.3_test`.

## Regola generale
In `2.3_test` non si insiste per salvare il ciclo a tutti i costi.

Quando il rischio supera il budget, il motore deve:
- ridurre pressione
- fermarsi in modo leggibile
- lasciare una traccia chiara del motivo

## Trigger minimi

| Trigger | Effetto minimo | Escalation | Log obbligatorio |
| --- | --- | --- | --- |
| primo `challenge_seen` nel run | `cooldown` breve o `suspect` forte | se il sito ripresenta challenge -> `assist_required` o `frozen` | `risk_pause_reason=challenge_seen_first` |
| due `challenge_seen` ravvicinati sullo stesso sito | `frozen` | se serve continuita -> `assist_required` | `risk_pause_reason=challenge_repeat` |
| `identity_budget` superato | stop del sito corrente | nessun altro switch identita nel run | `risk_pause_reason=identity_budget_exceeded` |
| `detail_budget` superato | blocco aperture dettaglio | il run puo proseguire solo su listing parsimonioso | `risk_pause_reason=detail_budget_exceeded` |
| `retry_budget` superato | stop pulito del sito | nessun retry extra nel run | `risk_pause_reason=retry_budget_exceeded` |
| `cooldown_budget` superato | `frozen` | assistenza manuale facoltativa | `risk_pause_reason=cooldown_budget_exceeded` |
| sessione in `degraded` per due finestre consecutive | `assist_required` | valutare recovery manuale o freeze esplicito | `risk_pause_reason=persistent_degraded` |

## Trigger minimi del servizio continuo

| Trigger | Effetto minimo | Escalation | Log obbligatorio |
| --- | --- | --- | --- |
| ciclo singolo con failure | `service_state=degraded` | se ripetuto -> `assist_required` | `failure_count`, `service_state` |
| ciclo singolo oltre soglia | `service_state=degraded` | se ripetuto -> revisione manuale del servizio | `overrun_count`, `cycle_elapsed_sec` |
| backlog singolo con slot persi | `service_state=degraded` | se ripetuto -> valutare freeze del servizio | `missed_cycle_count`, `cycle_delay_sec` |
| failure ripetuti del servizio | `assist_required` | stop pulito del comando continuo | `service_assist_reason=repeated_cycle_failures` |
| `run_state=assist_required` | `assist_required` immediato del servizio | stop pulito del comando continuo | `service_assist_reason=<run_reason>` |
| `run_state` degradato ripetuto | recycle dello slot del sito | valutare ricreazione del runtime solo se il problema si allarga | `runtime_disposition=recycle_site_slot` |
| run con degrado su piu siti nello stesso ciclo | `recycle_runtime` | valutare stop del servizio se ricorrente | `runtime_disposition=recycle_runtime` |

## Runtime disposition

| Caso | Decisione consigliata |
| --- | --- |
| ciclo pulito | `keep` |
| `run_state=cooldown` o `blocked` con sito noto | `recycle_site_slot` |
| failure tecnico del ciclo | `recycle_runtime` |
| degrado/cooling/blocked su piu siti nel run | `recycle_runtime` |
| `run_state=assist_required` | `stop_service` |

## Nota pratica
La linea `2.3_test` eredita questi trigger dalla baseline `2.2 stable`.

Le prime patch della nuova linea non dovrebbero cambiare questi contratti senza una motivazione molto esplicita e comparabile.
