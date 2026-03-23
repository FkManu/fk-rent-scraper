# 2_1_STABLE_MANIFEST.md

## Scopo
Questo file registra il criterio usato per costruire davvero la root `2.1_stable`.

## Incluso nel taglio
### Base codice e packaging
- `src/affitto_v2/`
- `run.py`
- `requirements.txt`
- `requirements-packaging.txt`
- `.env.sample`
- `.gitignore`
- `scripts/`
- `packaging/`

### Documentazione prodotto
- `README.md`
- `docs/windows_packaging.md`
- `docs/cli_test_matrix.md`
- `docs/email_test_setup.md`
- `docs/v1_audit_report.md`

### Contesto operativo essenziale
- `docs/context/README.md`
- `docs/context/HANDOFF.md`
- `docs/context/NEXT_STEPS.md`
- `docs/context/codex.md`
- `docs/context/2_1_STABLE_MANIFEST.md`

### Workflow Codex slim
- `docs/context/codex/INDEX.md`
- `docs/context/codex/HISTORY.md`
- `docs/context/codex/REVIEW_2_1_STABLE.md`

## Escluso esplicitamente
- `.venv/`
- `build/`
- `dist/`
- `runtime/`
- `__pycache__/`
- `*.pyc`
- DB, log, config locali, sender profiles locali, browser profile, live debug
- transcript grezzi lunghi
- file Codex transitori:
  - `PROMPT_CURRENT.md`
  - `ACTIVE_PATCH.md`
  - `OUTPUT_CURRENT.md`

## Decisioni prese
- `chat_openclaw.md` non portato
- `chat_codex.md` non portato
- `codex.md` portato in versione sintetica e riallineata alla baseline
- review finale tenuta come `docs/context/codex/REVIEW_2_1_STABLE.md`

## Verifica rapida
Una root `2.1_stable` pulita deve mostrare:
- codice in `src/`
- docs utili in `docs/`
- nessuna cartella `runtime/`, `build/`, `dist/`, `.venv/`
- nessun file Codex di sessione momentanea

## Nota
Se questa baseline verra copiata altrove o inizializzata in una repo privata separata, mantenere lo stesso criterio di sottrazione.
