# ACTIVE_PATCH.md

## Patch corrente
Stable release alignment:
- chiusura dei fix `idealista` e `private_only`
- riallineamento docs vive e memoria agente
- packaging e release coerenti con `2.2 stable`

## Obiettivo
Chiudere lo stato pubblicabile di `2.2 stable` senza trascinare ambiguita da preview.

## Contesto
- `2.2_test` deriva da `2.1_stable`, ma oggi e gia divergente nel motore live
- il soak VM del `2026-03-26` ha confermato una buona tenuta del backend `camoufox`
- il collo di bottiglia piu evidente emerso dai log e la precisione `private_only`, non la stabilita del motore

## Scope
- riallineamento dei markdown di contesto allo stato reale del ramo
- aggiornamento memoria sessione agente
- build della nuova dist stable
- sostituzione della vecchia release preview con release stable

## Non-scope
- niente CDP
- niente cambio di nome dei path runtime applicativi
- niente commit di runtime, log o dist temporanee
- niente bypass aggressivi

## File principali coinvolti
- `README.md`
- `docs/context/*.md`
- `docs/context/codex/*.md`
- `docs/cli_test_matrix.md`
- `docs/windows_packaging.md`
- `src/affitto_v2/db.py`
- `src/affitto_v2/scrapers/live_fetch.py`
- `tests/test_private_only_and_logging.py`
- `packaging/*.spec`

## Done quando
- i doc vivi non raccontano piu una milestone preview
- la memoria agente riflette i fix del `2026-03-27`
- la dist stable viene ricostruita con le modifiche correnti
- la vecchia prerelease `v2.2 Preview` viene rimossa e sostituita da `v2.2 stable`
