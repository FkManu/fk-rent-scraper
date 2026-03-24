# Codex Workflow - 2.1_stable

Workflow Codex ridotto all'essenziale per la baseline stabile.

## File presenti
- `HISTORY.md` -> storico sintetico delle patch che hanno portato a questa baseline
- `REVIEW_2_1_STABLE.md` -> review finale utile della root pulita
- `TASK_FIRST_RUN_RELIABILITY.md` -> task pronto per la prima patch della nuova fase
- `TASK_OBSERVABLE_AUTOHEALING.md` -> task pronto per la seconda patch della nuova fase
- `ACTIVE_PATCH.md` -> patch attiva corrente
- `PROMPT_CURRENT.md` -> prompt corrente da dare a Codex
- `OUTPUT_CURRENT.md` -> output corrente da salvare in repo
- `REVIEW_CURRENT.md` -> review corrente della patch attiva

## Regola pratica
Questa root mantiene il workflow standard repo-first per la patch attiva.

I task `TASK_*` sono documenti stabili di handoff.
I file `*_CURRENT.md` rappresentano invece il ciclo di lavoro corrente con Codex.

Quando una patch si chiude:
- si aggiorna `HISTORY.md`
- si aggiorna la review
- poi si sovrascrivono i file `*_CURRENT.md` per la patch successiva
