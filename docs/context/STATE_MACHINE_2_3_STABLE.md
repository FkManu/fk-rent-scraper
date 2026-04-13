# STATE_MACHINE_2_3_STABLE.md

## Scopo
Definire il modello di stato minimo della linea `2.3_stable`.

## Regola generale
La linea `2.3_stable` eredita la state machine osservabile gia consolidata in `2.2`.

Ogni stato continua a implicare:
- azioni consentite
- azioni vietate
- logging obbligatorio
- criterio di uscita
- eventuale effetto sul risk budget

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
La sessione produce output utile ma peggiore del normale, o il trust e basso.

### `cooldown`
Fase di attesa protettiva controllata.

### `frozen`
La sessione non va piu toccata automaticamente fino a decisione esplicita.

### `assist_required`
Serve intervento umano o decisione operativa esplicita.

### `blocked`
Esito chiaramente non utilizzabile o policy di stop definitivo per il run.

## Contratto minimo per stato

| Stato | Consentito | Vietato | Logging obbligatorio | Uscita minima |
| --- | --- | --- | --- | --- |
| `warmup` | navigazione iniziale parsimoniosa | retry cross-browser immediato | `state_transition=warmup` | passa a `stable` o `suspect` |
| `stable` | run normale entro budget | allargare budget senza motivo | `state_transition=stable` | resta stabile o degrada |
| `suspect` | riduzione budget, freeze dettagli non essenziali | escalation impulsiva | `state_transition=suspect`, `risk_pause_reason` | torna `stable` o sale a `challenge_seen` / `degraded` |
| `challenge_seen` | stop pulito, eventuale handoff operativo | loop sullo stesso URL | `state_transition=challenge_seen`, `outcome_code` | va a `cooldown`, `assist_required` o `frozen` |
| `degraded` | output minimo prudente, probe ridotta se prevista | insistere come se nulla fosse | `state_transition=degraded`, `outcome_tier=degraded` | torna `stable` o sale a `assist_required` |
| `cooldown` | sola attesa, probe solo se policy lo consente | bypass di routine del cooldown | `state_transition=cooldown`, `cooldown_origin` | torna a `warmup` o passa a `frozen` |
| `frozen` | nessuna automazione sul sito | resume implicito | `state_transition=frozen`, `risk_pause_reason` | solo decisione esplicita |
| `assist_required` | handoff a umano o decisione esplicita | recovery automatica a cascata | `state_transition=assist_required`, `manual_assist_used` | torna a `warmup` o `stable` dopo intervento |
| `blocked` | chiusura leggibile del run | qualunque nuovo tentativo nello stesso run | `state_transition=blocked`, `outcome_tier=blocked` | fine run |

## Trigger di riferimento
I passaggi a `cooldown`, `frozen`, `assist_required` e `blocked` devono seguire la tabella in:

- `STOP_TRIGGERS_2_3_STABLE.md`

## Traduzione attuale in codice
Alla nascita della linea `2.3_stable` la traduzione in codice e ereditata pari dalla baseline `2.2 stable`.

Restano quindi attivi:
- state machine tabellare in `src/affitto_v2/scrapers/guard/state_machine.py`
- rotate di `profile_generation` su `hard_block`
- legame del cooldown alla generazione vecchia
- distruzione del profilo persistente precedente nella root gestita

## Nota pratica
La `2.3_stable` non nasce per ridefinire subito questa state machine.

Le prime patch sensate lavorano sopra il modello esistente, non contro di esso.
