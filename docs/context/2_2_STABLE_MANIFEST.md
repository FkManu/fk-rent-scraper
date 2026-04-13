# 2_2_STABLE_MANIFEST.md

> DOCUMENTO STORICO DI CUTOVER.
> In `2.3_stable` questo file serve solo come baseline di provenienza.

## Scopo
Registrare cosa rappresentava la root `2.2_test` al momento dell'apertura di `2.3_stable`.

## Identita storica
La cartella `2.2_test` aveva ormai il ruolo reale di linea `2.2 stable`, pubblicata come release `2.2.2 refactorizzata`.

La root:
- manteneva il nome tecnico `2.2_test`
- non era piu una preview embrionale
- non era piu allineata alla baseline storica `2.1_stable`
- era la linea operativa con backend `camoufox`, servizio continuo e refactor strutturale del motore live

## Incluso nella baseline `2.2`
### Base codice e packaging
- `src/affitto_v2/`
- `run.py`
- `requirements.txt`
- `requirements-packaging.txt`
- `.env.sample`
- `.gitignore`
- `scripts/`
- `packaging/`
- `tests/`

### Documentazione prodotto
- `README.md`
- `docs/windows_packaging.md`
- `docs/cli_test_matrix.md`
- `docs/email_test_setup.md`
- `docs/v1_audit_report.md`
- `docs/risk_scoring_e_griglia_segnali_antibot.md`

### Contesto operativo vivo della linea `2.2`
- `docs/context/README.md`
- `docs/context/HANDOFF.md`
- `docs/context/NEXT_STEPS.md`
- `docs/context/ROADMAP_NEXT_MILESTONES.md`
- `docs/context/codex.md`
- `docs/context/2_2_TEST_MANIFEST.md`
- `docs/context/STRATEGY_2_2_TEST.md`
- `docs/context/STATE_MACHINE_2_2_TEST.md`
- `docs/context/STOP_TRIGGERS_2_2_TEST.md`
- `docs/context/EXPERIMENT_PLAN_2_2_TEST.md`
- `docs/context/PROMOTION_GATE_2_2_TEST.md`

### Workflow Codex utile
- `docs/context/codex/INDEX.md`
- `docs/context/codex/HISTORY.md`
- `docs/context/codex/ACTIVE_PATCH.md`
- `docs/context/codex/OUTPUT_CURRENT.md`
- `docs/context/codex/PROMPT_CURRENT.md`
- `docs/context/codex/REVIEW_CURRENT.md`
- `docs/context/codex/REVIEW_2_1_STABLE.md`

## Escluso dal perimetro Git pulito
- `.venv/`
- `runtime/`
- `build/`
- `dist/`
- `__pycache__/`
- `*.pyc`
- log locali
- DB locali
- artifact debug locali
- profili browser locali

## Nota pratica
`2.3_stable` e nata come copia filesystem completa di `2.2_test` per tenere gli ambienti locali separati.

Il perimetro Git pulito della nuova linea deve comunque continuare a escludere runtime, build, dist e virtualenv.
