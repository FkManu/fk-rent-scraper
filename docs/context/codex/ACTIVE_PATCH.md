# ACTIVE_PATCH.md

## Patch corrente
Preview hardening:
- memoria negativa `private_only`
- riallineamento docs vive
- packaging e dist coerenti con il ramo `camoufox`

## Obiettivo
Chiudere il primo stato davvero condivisibile della preview `2.2_test`.

## Contesto
- `2.2_test` deriva da `2.1_stable`, ma oggi e gia divergente nel motore live
- il soak VM del `2026-03-26` ha confermato una buona tenuta del backend `camoufox`
- il collo di bottiglia piu evidente emerso dai log e la precisione `private_only`, non la stabilita del motore

## Scope
- memoria negativa dedicata per gli annunci professionali rilevati dal detail-check
- riallineamento dei markdown di contesto allo stato reale del ramo
- build della nuova dist preview
- preparazione del changeset repo senza file temporanei

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
- i log non riaprono piu all'infinito gli stessi professionali Idealista gia classificati
- i doc vivi non raccontano piu una milestone vecchia
- la dist preview viene ricostruita con le modifiche correnti
- il changeset finale e pushabile senza artefatti locali
