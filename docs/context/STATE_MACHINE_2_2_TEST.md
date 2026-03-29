# STATE_MACHINE_2_2_TEST.md

## Scopo
Definire il modello di stato minimo della linea `2.2_test`.

## Regola generale
Gli stati non sono solo etichette di log.
Ogni stato deve implicare:
- azioni consentite
- azioni vietate
- logging obbligatorio
- criterio di uscita
- eventuale effetto sul risk budget residuo

## Stati

### `warmup`
Contesto nuovo o troppo giovane per considerare la sessione stabile.

### `stable`
Sessione considerata coerente e utilizzabile.

### `suspect`
Segnali deboli ma non conclusivi di degrado o scoring in aumento.

### `challenge_seen`
Interstiziale o challenge visibile/inferita.

### `degraded`
La sessione produce output tecnicamente utile ma peggiore del normale, o il trust e basso.

### `cooldown`
Fase di attesa protettiva controllata.

### `frozen`
La sessione non va piu toccata automaticamente fino a decisione esplicita.

### `assist_required`
Serve intervento umano o modalita `real_browser_assisted`.

### `blocked`
Esito chiaramente non utilizzabile o policy di stop definitivo per il run.

## Contratto minimo per stato

| Stato | Consentito | Vietato | Logging obbligatorio | Uscita minima |
| --- | --- | --- | --- | --- |
| `warmup` | navigazione iniziale parsimoniosa | retry cross-browser immediato | `state_transition=warmup` | passa a `stable` o `suspect` |
| `stable` | run normale entro budget | allargare budget senza motivo | `state_transition=stable` | resta stabile o degrada |
| `suspect` | riduzione budget, freeze dettagli non essenziali | escalation impulsiva | `state_transition=suspect`, `risk_pause_reason` | torna `stable` o sale a `challenge_seen` / `degraded` |
| `challenge_seen` | stop pulito, eventuale handoff assistito | loop sullo stesso URL | `state_transition=challenge_seen`, `outcome_code` | va a `cooldown`, `assist_required` o `frozen` |
| `degraded` | output minimo prudente, probe ridotta se prevista | insistere come se nulla fosse | `state_transition=degraded`, `outcome_tier=degraded` | torna `stable` o sale a `assist_required` |
| `cooldown` | sola attesa, probe solo se policy lo consente | bypass di routine del cooldown | `state_transition=cooldown`, `cooldown_origin` | torna a `warmup` o passa a `frozen` |
| `frozen` | nessuna automazione sul sito | resume implicito | `state_transition=frozen`, `risk_pause_reason` | solo decisione esplicita |
| `assist_required` | handoff a umano o modalita assistita | recovery automatica a cascata | `state_transition=assist_required`, `manual_assist_used` | torna a `warmup` o `stable` dopo assistenza |
| `blocked` | chiusura leggibile del run | qualunque nuovo tentativo nello stesso run | `state_transition=blocked`, `outcome_tier=blocked` | fine run |

## Regole pratiche

### In `warmup`
Consentito:
- pacing prudente
- una singola navigazione iniziale limitata

Vietato:
- retry cross-browser immediato
- detail budget alto

### In `suspect`
Consentito:
- riduzione del budget residuo
- freeze di aperture dettaglio non essenziali

Vietato:
- escalation impulsiva
- cambio browser reflex

### In `challenge_seen`
Consentito:
- stop pulito
- eventuale handoff a recovery assistita

Vietato:
- loop di retry sullo stesso URL

### In `cooldown`
Consentito:
- sola osservazione
- eventuale probe se la policy lo consente esplicitamente

Vietato:
- bypass di routine del cooldown

## Trigger di riferimento
I passaggi a `cooldown`, `frozen`, `assist_required` e `blocked` devono seguire la tabella in:

- `STOP_TRIGGERS_2_2_TEST.md`

## Regola finale
In `2.2_test` il passaggio di stato vale piu del singolo fetch outcome.

## Traduzione attuale in codice
- la state machine del run e ora estratta in `src/affitto_v2/scrapers/guard/state_machine.py`
- `live_fetch.py` la usa come orchestratore invece di contenere tutta la logica inline
- il mapping corrente tradotto in codice copre:
  - `healthy`
  - `suspect`
  - `degraded`
  - `cooldown`
  - `blocked`
  - `challenge_seen`
- su `blocked` con famiglia `hard_block` la decisione non si limita al cooldown:
  - ruota `profile_generation`
  - lega il cooldown alla generazione vecchia
  - distrugge il vecchio profilo persistente sotto la root gestita

## Stato del servizio continuo
Accanto allo stato del singolo run esiste ora anche uno stato minimo del servizio 24/7.

Stati correnti del servizio:
- `warmup`
- `stable`
- `degraded`
- `assist_required`

Trigger gia tradotti in codice:
- ciclo pulito -> `stable`
- failure singolo / overrun singolo / backlog singolo -> `degraded`
- failure ripetuti del servizio -> `assist_required`
- `run_state=assist_required` -> `service_state=assist_required`
- `run_state` degradato ripetuto -> degrado persistente del servizio e possibile recycle dello slot sito

Trigger non ancora tradotti del tutto:
- overrun ripetuti -> oggi contati, ma ancora da validare in soak reale
- backlog ripetuto come segnale strutturale di degrado lungo
- invalidazione automatica del runtime condiviso in base al `run_state`
