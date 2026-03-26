# 2_2_TEST_MANIFEST.md

## Scopo
Descrivere cosa rappresenta oggi la root `2.2_test`.

## Identita attuale
La cartella mantiene il nome `2.2_test`, ma il suo ruolo reale e di preview branch della prossima linea live.

Non e una copia dell'ambiente locale.
Non e la baseline shipping.

## Origine
`2.2_test` nasce come copia pulita di `2.1_stable` e poi diverge per:
- strategia live
- backend operativo
- session continuity
- servizio continuo
- osservabilita orientata a rischio e lifecycle

## Cosa fa parte della preview
- codice sorgente
- test
- script
- packaging
- documentazione prodotto
- documentazione di contesto

## Cosa non va committato
- `.venv`
- `runtime/`
- `build/`
- `dist/`
- log locali
- dump temporanei
- artifact diagnostici locali

## Regola pratica
Chi clona la preview deve ricreare localmente:
- virtualenv
- runtime
- profili persistenti
- artifact di soak o debug

## File guida obbligatori
- `docs/context/README.md`
- `docs/context/HANDOFF.md`
- `docs/context/NEXT_STEPS.md`
- `docs/context/codex/OUTPUT_CURRENT.md`
- `docs/risk_scoring_e_griglia_segnali_antibot.md`
