# PROMPT_CURRENT.md

Agisci sul progetto `affitto` nella root `2.2_test`.

## Task
Porta `2.2_test` a uno stato di preview condivisibile.

## Contesto
- `2.2_test` e la linea di laboratorio derivata da `2.1_stable`
- il file `docs/risk_scoring_e_griglia_segnali_antibot.md` va trattato come riferimento guida
- il soak VM del `2026-03-26` ha validato bene `camoufox`
- il problema aperto piu concreto e la precisione `private_only`

## Obiettivo
Chiudere una preview coerente su tre assi:
- codice
- contesto documentale
- packaging

## Cose da fare
1. mantenere il fix `private_only` con copertura test
2. riallineare i markdown vivi e ridurre duplicazioni evidenti
3. verificare ignore e changeset
4. rigenerare la dist preview aggiornata
5. preparare commit e push senza file temporanei

## Vincoli
- niente CDP in questa patch
- niente GUI nuova
- niente bypass aggressivi
- non committare runtime, log, build o dist temporanee

## Output finale richiesto
Alla fine dimmi:
- cosa hai aggiornato
- come hai tenuto fuori i file temporanei
- che build/dist hai prodotto
- che cosa e stato pushato
