# Context Docs

Questa cartella contiene il contesto operativo vivo della linea `2.3_stable`.

La linea nasce come copia completa e separata di `2.2_test`, ma con documentazione attiva ripulita e storico `2.2` archiviato.

## Documenti vivi
- `HANDOFF.md` -> snapshot rapido dello stato reale della nuova root
- `NEXT_STEPS.md` -> priorita immediate della linea
- `ROADMAP_NEXT_MILESTONES.md` -> milestone operative della `2.3`
- `../repo_summary.md` -> resoconto completo della repo per bootstrap rapido di contesto
- `2_3_STABLE_MANIFEST.md` -> identita e regole della nuova root
- `STRATEGY_2_3_STABLE.md` -> charter strategico della linea
- `STATE_MACHINE_2_3_STABLE.md` -> modello di stato ereditato e confermato
- `STOP_TRIGGERS_2_3_STABLE.md` -> trigger minimi di stop e assistenza
- `EXPERIMENT_PLAN_2_3_STABLE.md` -> telemetria, KPI e template esperimenti
- `PROMOTION_GATE_2_3_STABLE.md` -> criteri minimi per eventuale promozione

## Documenti per agenti
- `codex.md` -> entrypoint sintetico
- `codex/INDEX.md` -> indice operativo dei file `codex/`
- `codex/ACTIVE_PATCH.md` -> focus corrente
- `codex/PROMPT_CURRENT.md` -> prompt operativo corrente
- `codex/OUTPUT_CURRENT.md` -> stato tecnico sintetico
- `codex/REVIEW_CURRENT.md` -> review sintetica della patch corrente
- `codex/HISTORY.md` -> storico breve della linea e del cutover

## Baseline e storico utile
- `2_1_STABLE_MANIFEST.md` -> baseline storica di provenienza lontana
- `2_2_STABLE_MANIFEST.md` -> baseline immediata da cui nasce `2.3_stable`
- `codex/REVIEW_2_1_STABLE.md` -> review storica baseline `2.1`
- `codex/REVIEW_2_2_STABLE.md` -> review di chiusura della linea `2.2`
- `codex/TASK_*.md` -> task storici utili come reference, non come stato corrente

## Archivio interno
- `archive/2_2/` -> snapshot dei documenti `2.2` archiviati
- `codex/archive/2_2/` -> snapshot dei file Codex vivi della `2.2`

## Ordine di lettura consigliato
1. `HANDOFF.md`
2. `NEXT_STEPS.md`
3. `codex/OUTPUT_CURRENT.md`
4. `../repo_summary.md`
5. `STRATEGY_2_3_STABLE.md`
6. `STATE_MACHINE_2_3_STABLE.md`
7. `EXPERIMENT_PLAN_2_3_STABLE.md`
8. `STOP_TRIGGERS_2_3_STABLE.md`
9. `PROMOTION_GATE_2_3_STABLE.md`

## Nota pratica
- `2.3_stable` parte con codice osservabilmente allineato alla `2.2.2 refactorizzata`.
- il backend operativo resta `camoufox`.
- lo storico `2.2` resta consultabile, ma non va usato come stato vivo.
