# NEXT_STEPS.md

## Punto di partenza
`2.3_test` parte come copia completa della linea `2.2 stable`.

Prima di aprire nuove patch, la priorita e rendere esplicito che cosa e:
- baseline ereditata
- archivio storico
- backlog davvero nuovo della `2.3`

## Priorita ragionevoli da qui in avanti
1. Parity freeze della nuova root:
   - verificare che `2.3_test` parta osservabilmente allineata a `2.2`
   - trattare il delta locale su `requirements.txt` come decisione da confermare o scartare
   - evitare di leggere come regressione della `2.3` una differenza gia presente nella root copiata
2. Hygiene del cutover:
   - usare solo i file `2.3_*` come documentazione attiva
   - lasciare il contesto `2.2` dentro `archive/2_2`
   - non duplicare lo stesso stato tra `README`, `HANDOFF`, `NEXT_STEPS` e `OUTPUT_CURRENT`
3. Prima patch operativa plausibile:
   - scegliere un solo asse tra:
     - `immobiliare adaptive prepare`
     - notifica blocco lungo `>= 1h` + recovery
     - `soft mode` locale post-`hard_block`
     - scomposizione residua di `live_fetch.py`
4. Validazione soak della baseline ereditata:
   - confermare che `profile_generation`, `cooldown_generation` e `runtime_disposition` restino leggibili
   - confermare che la root nuova non alteri da sola il comportamento del servizio
5. Precisione `private_only`:
   - continuare a misurare `reused_professional`
   - continuare a osservare `allowed_without_agency_signal`
   - non mischiare questo fronte con prepare phase o lifecycle nella stessa patch
6. Release hygiene:
   - trattare `dist/` come artefatto locale
   - non committare log, runtime, bundle temporanei o dump di soak

## Primo ordine di lettura per chi riparte
1. `docs/risk_scoring_e_griglia_segnali_antibot.md`
2. `docs/context/HANDOFF.md`
3. `docs/context/STRATEGY_2_3_TEST.md`
4. `docs/context/STATE_MACHINE_2_3_TEST.md`
5. `docs/context/EXPERIMENT_PLAN_2_3_TEST.md`
6. `docs/context/STOP_TRIGGERS_2_3_TEST.md`
7. `docs/context/codex/OUTPUT_CURRENT.md`

## Cose da evitare
- non riaprire subito multi-browser o CDP
- non trasformare il taglio repo in patch di prodotto
- non mischiare packaging, parser e strategia live
- non trattare come “nuova idea 2.3” qualcosa che e solo stato copiato dalla `2.2`

## Regola pratica
Ogni patch di `2.3_test` deve:
- preservare il comportamento sano della `2.2`
e inoltre
- ridurre rumore
oppure
- migliorare osservabilita
oppure
- migliorare in modo misurabile `private_only`
