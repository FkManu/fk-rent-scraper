# TASK_2_2_M0_FOUNDATION.md

## Titolo task
2.2_test Milestone 0 / telemetry + risk budget + state model foundation

## Owner
Backend / Codex

## Stato
Ready

## Priorita
Massima nella nuova linea `2.2_test`

## Contesto
`2.2_test` nasce come laboratorio separato da `2.1_stable`.
Prima di aprire esperimenti su browser reale o continuita di sessione serve una base comune misurabile.

I documenti guida sono:
- `docs/risk_scoring_e_griglia_segnali_antibot.md`
- `docs/context/STRATEGY_2_2_TEST.md`
- `docs/context/STATE_MACHINE_2_2_TEST.md`
- `docs/context/EXPERIMENT_PLAN_2_2_TEST.md`
- `docs/context/STOP_TRIGGERS_2_2_TEST.md`
- `docs/context/PROMOTION_GATE_2_2_TEST.md`

## Obiettivo
Preparare il foundation layer della nuova linea:
- telemetria minima comune
- risk budget esplicito
- stato di run/sessione piu strutturato
- trigger di stop coerenti con gli stati

## Non-obiettivi
- niente CDP in questo task
- niente GUI nuova
- niente packaging
- niente bypass aggressivi

## Cosa implementare
1. introdurre strutture dati o costanti coerenti per:
   - telemetria minima comune
   - risk budget
   - state labels
   - stop reasons principali
2. lasciare il codice pronto per distinguere almeno:
   - `managed_stable`
   - `real_browser_assisted`
   - `cdp_bootstrap`
   - `cdp_recovery`
3. evitare gia in questa fase il retry cross-browser immediato come default del nuovo ramo
4. aggiungere logging minimo utile a misurare:
   - `identity_switch`
   - `detail_touch_count`
   - `retry_count`
   - `risk_pause_reason`

## Criteri di accettazione
1. il nuovo ramo ha fondamenta misurabili
2. i log iniziano a parlare il linguaggio della nuova strategia
3. nessuna regressione o feature creep non necessaria

## Prompt finale per Codex
Agisci sulla root `2.2_test`.

Task: implementa **Milestone 0 / telemetry + risk budget + state model foundation**.

Obiettivo:
- preparare il ramo per i successivi esperimenti di continuita di sessione
- introdurre telemetria minima comune, risk budget e labels di stato coerenti

Vincoli:
- niente CDP in questo task
- niente GUI nuova
- niente packaging
- niente bypass aggressivi

Alla fine restituisci:
- cosa hai implementato
- file toccati
- cosa misura il nuovo layer
- cosa resta per il task successivo
