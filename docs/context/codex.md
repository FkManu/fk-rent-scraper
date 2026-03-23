# codex.md

## Sintesi progetto
`2.1_stable` nasce come taglio pulito del lavoro consolidato in `v2_test`.

Questa baseline include:
- scraping live e pipeline notifiche
- GUI operativa per setup e runtime
- preset SMTP + Custom SMTP
- sender profile cifrati con DPAPI
- packaging Windows con GUI bundle + companion CLI
- hardening runtime notifiche
- anti-block pragmatico e drift detection minima

## Storia minima utile
- `v1_stable` resta storico e archivistico
- `v2_test` e stato il laboratorio attivo dove sono state chiuse e approvate le patch prodotto
- `2.1_stable` e la nuova base privata pulita ottenuta per sottrazione

## Cosa non entra nella baseline
- runtime locali
- build/dist
- cache e `__pycache__`
- transcript grezzi lunghi
- file Codex transitori di singola sessione

## Workflow Codex in questa root
Tenere solo:
- `docs/context/codex/INDEX.md`
- `docs/context/codex/HISTORY.md`
- `docs/context/codex/REVIEW_2_1_STABLE.md`

Se in futuro serve un nuovo ciclo Codex piu esteso, creare file di lavoro nuovi senza riportare automaticamente quelli transitori della repo precedente.
