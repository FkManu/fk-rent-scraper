# 2_3_STABLE_MANIFEST.md

## Scopo
Descrivere cosa rappresenta oggi la root `2.3_stable`.

## Identita attuale
`2.3_stable` nasce come copia locale completa di `2.2_test` al momento in cui la linea `2.2` viene considerata pronta a diventare stable.

La root quindi e:
- un ambiente locale separato
- una linea di lavoro nuova
- una base tecnica inizialmente identica alla `2.2.2 refactorizzata`
- un perimetro in cui aprire la prossima iterazione senza sporcare `2.2_test`

## Regola chiave
Nel filesystem locale questa root e una copia completa e stagna.

Nel perimetro Git pulito della linea, invece, restano fuori:
- `.venv/`
- `runtime/`
- `build/`
- `dist/`
- log locali
- dump temporanei
- artifact diagnostici locali

## Cosa fa parte della linea `2.3_stable`
- codice sorgente
- test
- script
- packaging
- documentazione prodotto
- documentazione di contesto aggiornata alla nuova linea
- archivio storico minimo della linea `2.2`

## Cosa non significa ancora
`2.3_stable` al momento del taglio:
- non e ancora una nuova release
- non introduce automaticamente nuove feature
- non ridefinisce da sola la baseline shipping

All'apertura della root il comportamento del codice e ereditato da `2.2.2 refactorizzata`, salvo future patch deliberate.

## File guida obbligatori
- `docs/context/README.md`
- `docs/context/HANDOFF.md`
- `docs/context/NEXT_STEPS.md`
- `docs/context/2_3_STABLE_MANIFEST.md`
- `docs/context/codex/OUTPUT_CURRENT.md`
- `docs/risk_scoring_e_griglia_segnali_antibot.md`

## Nota pratica
Lo stato vivo della linea `2.3_stable` va letto nei markdown attivi.

Lo stato storico di provenienza `2.2` e stato archiviato in:
- `docs/context/archive/2_2/`
- `docs/context/codex/archive/2_2/`
