# HANDOFF.md

## Stato attuale
- `2.3_test` e stata creata il `2026-03-30` come copia completa e separata di `2.2_test`
- il codice prodotto della nuova root parte allineato alla baseline `2.2.2 refactorizzata`
- `2.2_test` resta la linea di riferimento appena congelata come `2.2 stable`
- la documentazione viva e stata riallineata alla nuova linea
- il contesto `2.2` necessario al recupero storico e stato archiviato in:
  - `docs/context/archive/2_2/`
  - `docs/context/codex/archive/2_2/`

## Decisione di progetto
La `2.3_test` non nasce per introdurre subito nuove feature.

Nasce per:
- tenere l'ambiente locale separato dalla `2.2`
- congelare con chiarezza la memoria della linea stabile appena chiusa
- aprire il prossimo ciclo di lavoro con documentazione meno ambigua

## Cosa eredita dalla `2.2 stable`
- backend operativo `camoufox`
- servizio continuo `fetch-live-service`
- profili persistenti per sito
- rotate di `profile_generation` su `hard_block`
- render context deterministico
- pacing Gamma
- bootstrap static resources
- refactor strutturale gia avviato del motore live

## Cosa e cambiato nel taglio
- nuova root locale `2.3_test`
- nuovo manifest di linea `2_3_TEST_MANIFEST.md`
- nuova strategia e nuovi documenti `2.3`
- archivio interno del contesto `2.2`

## Cosa non e cambiato intenzionalmente
- nessuna modifica intenzionale al codice prodotto nel momento del cutover
- nessun cambio di backend
- nessuna ridefinizione della state machine o dei trigger del guard

## Nota importante sul working tree ereditato
La copia completa ha trascinato anche stato locale della root sorgente.

In particolare:
- `requirements.txt` include `undetected-playwright==0.3.0`

Nel primo rilascio `2.3_test` questo delta viene portato avanti cosi com'e, senza introdurre ancora un uso operativo dichiarato nel codice prodotto.

## File da leggere per ripartire
- `README.md`
- `docs/context/README.md`
- `docs/context/NEXT_STEPS.md`
- `docs/context/STRATEGY_2_3_TEST.md`
- `docs/context/codex/OUTPUT_CURRENT.md`
- `docs/risk_scoring_e_griglia_segnali_antibot.md`

## Prossimo passo sensato
- verificare la parita osservabile tra `2.2_test` e `2.3_test`
- decidere il primo asse sperimentale della `2.3`
- aprire poi una patch piccola e comparabile, senza mischiare piu fronti
