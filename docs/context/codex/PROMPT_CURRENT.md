# PROMPT_CURRENT.md

Agisci sul progetto `affitto` nella root `2.1_stable`.

## Task
Implementa una patch mirata di **precisione fetch / modalita `annunci privati`**.

## Contesto
- `2.1_stable` e la baseline viva del progetto.
- La patch `Observable autohealing / browser affinity per sito` e stata chiusa con esito operativo positivo.
- Nei log VM di alcune ore:
  - nessun `hard_block` osservato
  - `idealista` tende a stabilizzarsi su `msedge`
  - `immobiliare` tende a stabilizzarsi su `chrome`
- Il prodotto ha gia:
  - site guard con cooldown/jitter
  - strike/recovery
  - channel rotation
  - profilo persistente Playwright per canale
  - artifact diagnostici
  - quality signals parser come `partial_success_degraded`
- Il problema dominante si e spostato sulla precisione utile del fetch:
  - il filtro URL "solo privati" non garantisce da solo risultati davvero solo privati
  - quando i siti esauriscono i privati disponibili possono emergere annunci agenzia tra i suggeriti
  - `idealista` resta spesso `partial_success_degraded`, soprattutto sui segnali agenzia

## Obiettivo
Migliorare la precisione dei risultati quando l'utente vuole monitorare solo annunci privati.

In particolare il sistema deve:
- offrire una modalita opzionale `annunci privati`
- escludere localmente gli annunci in cui viene rilevata una agenzia
- mantenere separati:
  - filtro URL lato sito
  - filtro hard locale lato parser/pipeline
- rendere misurabile con log l'impatto del filtro sulla qualita utile dei risultati

## Direzione desiderata
Introdurre una patch piccola e verificabile, senza toccare la filosofia prudente del motore live.

Direzione pratica:
- checkbox GUI o controllo equivalente per abilitare `annunci privati`
- filtro locale basato sui segnali agenzia gia esistenti o migliorati
- distinzione chiara tra:
  - annunci privati realmente passati
  - annunci scartati per agenzia rilevata
  - casi incerti dove il segnale agenzia non e affidabile

Se utile, aggiungere log/summary compatti che aiutino a capire:
- quanti annunci sono stati esclusi
- su quale sito
- con quale segnale

## Cose da fare
1. aggiungere il controllo configurabile per la modalita `annunci privati`
2. introdurre l'esclusione locale degli annunci in cui viene rilevata una agenzia
3. mantenere ben separati il filtro remoto del sito e il filtro locale del progetto
4. migliorare i log o il summary per misurare gli annunci esclusi e i casi dubbi
5. evitare regressioni sul comportamento standard quando la modalita non e attiva

## Vincoli
- non fare bypass aggressivi
- non fare un refactor enorme del core live in questa patch
- non introdurre euristiche opache difficili da spiegare
- non scambiare `URL filter` del sito con `private-only guarantee`
- mantenere un approccio conservativo coerente con la natura del progetto

## File principali da toccare
- `src/affitto_v2/scrapers/live_fetch.py`
- `src/affitto_v2/gui_app.py`
- eventuali file config/runtime collegati al nuovo toggle
- docs minime se servono per riallineare il comportamento

## Criteri di accettazione
1. l'utente puo abilitare o disabilitare la modalita `annunci privati`
2. con modalita attiva, gli annunci con agenzia rilevata vengono esclusi localmente
3. il comportamento standard resta invariato quando la modalita e disattivata
4. i log o summary rendono visibile quanti annunci vengono esclusi
5. il codice resta leggibile e non introduce caos gratuito
6. la patch e verificabile con log reali su `idealista` e `immobiliare`

## Output finale richiesto
Alla fine dimmi:
- cosa hai implementato
- file toccati
- limiti residui
- come verificare la patch con log reali e modalita attiva/disattiva
