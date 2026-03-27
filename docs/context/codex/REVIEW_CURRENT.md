# REVIEW_CURRENT.md

## Patch corrente
Stable release alignment e hardening finale `idealista`

## Stato review
Patch reviewata su base locale.

## Focus atteso della review
- persistenza reale della memoria negativa `private_only`
- assenza del vecchio `unexpected_error` su `detail_touch_count`
- doc vivi coerenti con lo stato reale della release
- nessun trascinamento di artefatti locali nel changeset
- packaging coerente con il backend `camoufox`

## Esito sintetico
- il ramo salva ora i professionali Idealista rilevati dal detail-check in una cache negativa dedicata, invece di perderli nel filtro `private_only`
- i test locali coprono sia il salvataggio sia il riuso della memoria professionale
- il fix `detail_touch_count` evita il cooldown artificiale di `idealista` causato da errore interno
- `README`, `HANDOFF`, `NEXT_STEPS`, `codex/OUTPUT_CURRENT` e `codex/INDEX` tornano ad avere ruoli distinti e non piu quasi duplicati
- il naming della root resta `2.2_test`, ma la documentazione la posiziona in modo coerente come linea `2.2 stable`
- residuo principale: confermare nel prossimo soak che `reused_professional` salga sopra `0`, che il pattern ripetuto sui due `ad_id` Idealista sparisca davvero e che non ricompaiano `unexpected_error`
