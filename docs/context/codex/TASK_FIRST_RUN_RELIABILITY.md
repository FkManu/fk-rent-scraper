# TASK_FIRST_RUN_RELIABILITY.md

## Titolo task
First-run reliability / siteguard warmup refinement

## Owner
Backend / Codex

## Stato
Ready

## Priorita
Alta

## Contesto
La baseline `2.1_stable` e stata validata come nuova base viva del progetto.
Il bundle Windows e stato testato con successo anche in VM pulita, ma e emersa una anomalia residua importante:

- al primo tentativo su Idealista in VM/runtime nuovo e richiesto di fatto un reset del siteguard
- dopo quel reset il sistema poi si comporta bene

Questa anomalia non blocca il progetto, ma e tossica per affidabilita percepita, onboarding e futura vendibilita.

Il prodotto oggi ha gia:
- site guard con cooldown/jitter
- strike/recovery
- channel rotation
- persistent profile per canale
- artifact diagnostici
- pulsante GUI `Reset Site Guard`

Il problema e che il primo contesto vergine sembra essere trattato in modo troppo poco esplicito o troppo punitivo.

## Obiettivo
Rendere il comportamento del sistema piu robusto e leggibile nei casi di:
- primo avvio su PC/VM puliti
- runtime vergine
- profilo browser nuovo
- prima interazione Idealista in contesto senza storico utile

L'obiettivo e **ridurre o eliminare la necessita pratica del reset manuale** come parte del flusso normale di first-run.

## Non-obiettivi
- non introdurre bypass aggressivi
- non aumentare in modo temerario retry o frequenza
- non trasformare il guard in una logica opaca o magica
- non fare refactor enorme di tutto `live_fetch.py` in questo task

## Ipotesi di lavoro consigliata
Introdurre un concetto esplicito di stato iniziale / warmup per sito, almeno a livello di comportamento interno e logica outcome.

Esempi di segnali utili:
- nessun `last_success_utc`
- guard state appena creato
- profilo browser appena inizializzato
- prima run reale del sito in quel runtime

Quando il sito e in warmup:
- un primo fallimento `suspect` / `blocked` non va trattato subito come caso pienamente equivalente a una situazione gia stabile
- servono log piu espliciti
- eventuale cooldown iniziale deve essere coerente ma piu leggibile e meno inutilmente punitivo
- il passaggio fuori dal warmup dovrebbe avvenire dopo il primo successo sano

## File/area coinvolta
Principali:
- `src/affitto_v2/scrapers/live_fetch.py`
- `src/affitto_v2/gui_app.py`

Possibili ritocchi docs:
- `docs/context/NEXT_STEPS.md`
- o altra doc breve se utile al comportamento first-run

## Cosa implementare
### 1. Initial-state / warmup awareness nel guard
Valutare se il sito e in stato vergine / warmup.

### 2. Gestione piu coerente del primo fail sospetto
Se il primo tentativo in warmup produce outcome come challenge/block/suspect:
- non trasformarlo subito in comportamento troppo punitivo da stato consolidato
- registrare chiaramente che il problema e avvenuto in warmup
- mantenere prudenza, ma senza spingere l'utente verso reset manuale come rito standard

### 3. Exit condition dal warmup
Dopo il primo successo vero del sito:
- uscita dal warmup
- ritorno alle regole normali del guard

### 4. Log/supporto piu parlanti
Aggiungere logging e, se sensato, feedback GUI o status message che facciano capire:
- che il sistema e in first-run/warmup
- che il problema e collegato al contesto iniziale
- che il reset manuale non e normalmente il primo passo da fare

### 5. Nessuna regressione sul comportamento prudente
La patch deve restare coerente con una filosofia conservativa.

## Output atteso
- codice aggiornato
- eventuale minimo aggiornamento documentale se utile
- breve nota finale con:
  - cosa e stato cambiato
  - file toccati
  - limiti residui
  - come verificare

## Criteri di accettazione
1. Su runtime/VM puliti il caso Idealista first-run e trattato in modo piu leggibile.
2. Il sistema non richiede di fatto `Reset Site Guard` come passo normale del primo avvio.
3. Esiste un comportamento esplicito o almeno inferibile di `warmup` / `initial state`.
4. Dopo un successo sano il sito rientra nel comportamento standard.
5. Nessuna deriva verso retry aggressivi o politiche troppo rischiose.
6. Il codice resta leggibile e non introduce caos gratuito.

## Prompt finale per Codex
Agisci sul progetto `affitto` nella root `2.1_stable`.

Task: implementa una patch mirata di **first-run reliability / siteguard warmup refinement**.

Contesto:
- il bundle Windows e gia promosso anche in VM pulita
- la root `2.1_stable` e la baseline viva
- anomalia residua: su Idealista, in VM/runtime nuovo, al primo tentativo il sistema richiede di fatto reset del siteguard; dopo il reset tutto poi funziona
- il prodotto ha gia site guard, cooldown, jitter, channel rotation, profilo persistente e artifact diagnostici

Obiettivo:
- ridurre o eliminare la necessita pratica del reset manuale come parte del normale first-run
- introdurre una gestione piu coerente del contesto `warmup` / `initial state` per sito
- mantenere un approccio prudente, senza bypass aggressivi

Vincoli:
- non fare refactor enorme dell'intero scraping core in questa patch
- non aumentare in modo temerario retry o frequenza
- non nascondere il problema: renderlo piu leggibile e meglio gestito

Aree principali:
- `src/affitto_v2/scrapers/live_fetch.py`
- `src/affitto_v2/gui_app.py`

Cose da fare:
1. introdurre o esplicitare una nozione di warmup/initial-state nel guard
2. trattare il primo fail sospetto in warmup in modo meno punitivo ma comunque prudente
3. uscire dal warmup dopo il primo successo reale
4. migliorare log/status per far capire meglio il contesto first-run
5. mantenere il reset manuale come leva di emergenza, non come procedura normale

Alla fine restituisci:
- cosa hai implementato
- file toccati
- limiti residui
- come verificare la patch su VM/runtime puliti
