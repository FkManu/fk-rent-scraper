# NEXT_STEPS.md

## Punto di partenza
Questa root `2.1_stable` e la baseline privata pulita da cui ripartire.

Per ricostruire il contesto operativo minimo leggere prima:
1. `docs/context/HANDOFF.md`
2. `docs/context/2_1_STABLE_MANIFEST.md`
3. `docs/context/codex/REVIEW_2_1_STABLE.md`

## Priorita ragionevoli da qui in avanti
1. Preparare la repo GitHub privata di `2.1_stable`:
   - ricontrollo `.gitignore`
   - verifica finale file sensibili/template
   - primo commit pulito
   - push su repo privata condivisa solo con collaboratori scelti
2. Fare un primo deploy bundle-oriented in VM Windows pulita:
   - apertura GUI
   - creazione runtime al primo avvio
   - salva configurazione
   - test Telegram
   - test email
   - `Run Once`
   - lettura log e problemi da "PC nuovo"
3. Fare review mirata dei log live quando compaiono outcome `degraded`, `blocked` o `parser_drift`.
4. Valutare solo dopo questi due passaggi eventuali patch nuove su:
   - installazione/distribuzione Windows
   - rifinitura UX mirata
   - tuning soglie parser/guard basato su evidenza reale

## Cose da evitare
- non reimportare runtime, build, dist o transcript grezzi in questa root
- non riaprire `v1_stable` come base tecnica
- non aggiungere nuove feature solo perche la root e pulita

## Regola pratica
Nuove patch si aprono da qui, con scope piccolo e verificabile.
