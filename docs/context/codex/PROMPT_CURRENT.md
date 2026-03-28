# PROMPT_CURRENT.md

Agisci sul progetto `affitto` nella root `2.2_test`.

## Task
Mantieni `2.2_test` allineata alla release `2.2 stable`.

## Contesto
- `2.2_test` e la linea di laboratorio derivata da `2.1_stable`
- il file `docs/risk_scoring_e_griglia_segnali_antibot.md` va trattato come riferimento guida
- il soak VM del `2026-03-26` ha validato bene `camoufox`
- `camoufox` resta il backend unico della linea
- il problema aperto piu concreto oggi e la qualita della profile identity persistente piu che il motore

## Obiettivo
Chiudere e mantenere una stable coerente su tre assi:
- codice
- contesto documentale
- packaging

## Cose da fare
1. mantenere il fix `private_only` con copertura test
2. mantenere il fix `idealista` sul `detail_touch_count` con copertura test
3. mantenere la policy `hard_block => rotate profile`
4. mantenere `immobiliare` con rotate preventivo a `24h`
5. mantenere il binding corretto tra cooldown e `profile_generation`
6. mantenere leggibili nei log `Profile identity rotated`, `profile_generation`, `profile_age_sec`, `cooldown_generation`
7. mantenere GUI e CLI allineate sul contratto live corrente
8. ricostruire la dist stable e validarla nel prossimo soak prima di aprire il refactor di `live_fetch.py`

## Vincoli
- niente CDP in questa patch
- niente riapertura multi-browser
- niente bypass aggressivi
- non committare runtime, log, build o dist temporanee

## Output finale richiesto
Alla fine dimmi:
- cosa hai aggiornato
- come hai tenuto fuori i file temporanei
- che cosa resta da validare nel prossimo soak
