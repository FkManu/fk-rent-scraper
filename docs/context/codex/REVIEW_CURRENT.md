# REVIEW_CURRENT.md

## Patch corrente
Preview hardening e memoria negativa `private_only`

## Stato review
Patch reviewata su base locale.

## Focus atteso della review
- persistenza reale della memoria negativa `private_only`
- doc vivi coerenti con lo stato reale della preview
- nessun trascinamento di artefatti locali nel changeset
- packaging coerente con il backend `camoufox`

## Esito sintetico
- il ramo salva ora i professionali Idealista rilevati dal detail-check in una cache negativa dedicata, invece di perderli nel filtro `private_only`
- i test locali coprono sia il salvataggio sia il riuso della memoria professionale
- `README`, `HANDOFF`, `NEXT_STEPS`, `codex/OUTPUT_CURRENT` e `codex/INDEX` tornano ad avere ruoli distinti e non piu quasi duplicati
- il naming della root resta `2.2_test`, ma la documentazione la posiziona in modo coerente come preview branch
- residuo principale: confermare nel prossimo soak che `reused_professional` salga sopra `0` e che il pattern ripetuto sui due `ad_id` Idealista sparisca davvero
