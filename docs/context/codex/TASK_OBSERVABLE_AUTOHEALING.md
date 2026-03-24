# TASK_OBSERVABLE_AUTOHEALING.md

## Titolo task
Observable autohealing / support status per sito

## Owner
Backend / Codex

## Stato
Ready

## Priorita
Alta

## Contesto
Il progetto `affitto` ha gia una base prudente sul live scraping:
- outcome tier (`healthy`, `suspect`, `degraded`, `blocked`, `cooling`)
- cooldown e jitter
- strike/recovery
- artifact diagnostici
- parser drift minima
- differenziazione tra problemi di rete, parse issue e blocchi piu seri

Questa base e utile ma ancora troppo centrata su log e interpretazione tecnica.

Per diventare piu affidabile e supportabile il sistema deve essere piu **osservabile**.
Il supporto umano e l'utente devono poter capire meglio, in forma sintetica, cosa sta succedendo su ogni sito senza dipendere solo da lettura completa dei log.

## Obiettivo
Fare un passo da anti-block reattivo a **autohealing pragmatico e osservabile**, introducendo uno strato di stato sintetico e leggibile per sito.

## Non-obiettivi
- non costruire una dashboard grande
- non rifare tutta la GUI
- non fare un refactor completo di `live_fetch.py` in questa patch
- non aggiungere feature commerciali o multiutente

## Risultato desiderato
A valle di un run reale o di piu run il sistema deve poter esporre in modo piu chiaro almeno:
- ultimo outcome per sito
- stato sintetico del sito
- cooldown attivo / residuo se rilevante
- ultimo successo / ultimo blocco / ultimo recovery
- quality estrazione o segnale equivalente
- ultimo canale browser valido, se utile
- ultimo canale browser tentato e famiglia di blocco rilevata, se utile

## Possibili direzioni implementative
Non e obbligatorio seguire esattamente questa struttura, ma la direzione desiderata e:

### 1. Migliorare la tassonomia osservabile
Rendere piu leggibile la differenza tra:
- problema temporaneo di rete
- suspicious empty / challenge debole
- interstitial anti-bot esplicito
- block piu serio
- parser drift
- recovery avvenuta
- sito in warmup / sito stabile / sito degradato

### 2. Produrre uno stato sintetico per sito
Salvare o esporre in forma compatta uno stato utile al supporto, per esempio nel runtime o dove e piu coerente con l'architettura attuale.

### 2-bis. Rendere adattiva la scelta browser per sito
Se dai test emerge una preferenza concreta per browser/canale diversi tra siti, il sistema deve poter:
- ricordare l'ultimo canale valido per sito
- osservare l'ultimo canale che ha prodotto block/challenge
- riordinare in modo prudente i candidati browser senza retry aggressivi

### 3. Distinguere meglio `Run Once` e ciclo automatico
`Run Once` puo restare piu diagnostico.
Il ciclo automatico deve essere piu prudente.
Se emerge una differenza utile di stato/UX/log, esplicitarla.

### 4. Rendere piu pratici i segnali per supporto
Il supporto deve poter ragionare con meno intuizione e piu stati/codici leggibili.

## File/area coinvolta
Principali:
- `src/affitto_v2/scrapers/live_fetch.py`

Possibili aree secondarie se servono:
- `src/affitto_v2/gui_app.py`
- `src/affitto_v2/main.py`
- doc minima se utile

## Cosa implementare
### 1. Stato sintetico per sito
Aggiungere uno strato dati/supporto che consenta di sapere piu facilmente per ogni sito:
- ultimo esito
- severita/stato
- cooldown
- recovery
- health sintetica o equivalente
- ultimo canale valido / ultimo canale tentato
- ultima famiglia di blocco rilevata quando applicabile

### 2. Logging piu orientato a supporto
Log piu compatti e significativi sui passaggi chiave, evitando di aumentare rumore inutile.

### 3. Migliore leggibilita delle recovery policy
Quando il sistema osserva, raffredda, recupera o resta degradato, deve risultare piu comprensibile.

### 4. Nessuna deriva in feature overkill
La patch deve restare pragmatica e piccola/utile.

## Output atteso
- codice aggiornato
- eventuale minimo aggiornamento docs se necessario
- breve nota finale con:
  - cosa e stato implementato
  - file toccati
  - limiti residui
  - come verificare il nuovo stato osservabile

## Criteri di accettazione
1. Dopo run reali il supporto puo capire piu rapidamente lo stato dei siti.
2. Esiste una rappresentazione sintetica utile di stato/outcome/recovery per sito.
3. La differenza tra `healthy`, `suspect`, `degraded`, `blocked`, `cooling` e piu pratica da usare.
4. Il sistema comunica meglio i casi di recovery e i cooldown rilevanti.
5. La patch non introduce UI pesante o complicazione gratuita.
6. Se un sito mostra una preferenza concreta per un browser/canale, il sistema puo ricordare e riordinare i candidati in modo prudente.
7. Gli interstitial anti-bot rilevanti sono distinguibili nei codici/outcome da altri hard block generici.

## Prompt finale per Codex
Agisci sul progetto `affitto` nella root `2.1_stable`.

Task: implementa una patch di **observable autohealing / support status per sito**.

Contesto:
- il progetto ha gia un motore live prudente con outcome tier, cooldown/jitter, strike/recovery, drift minima e artifact diagnostici
- questa base e utile ma ancora troppo dipendente da log grezzi e interpretazione tecnica
- l'obiettivo della fase attuale non e vendere nuove feature, ma aumentare affidabilita percepita, supportabilita e leggibilita del comportamento live

Obiettivo:
- introdurre uno strato piu osservabile e sintetico di stato per sito
- rendere piu pratiche da capire le differenze tra suspect / degraded / blocked / cooling / recovery
- aiutare sia supporto sia utente a capire cosa sta succedendo senza leggere tutto il log grezzo

Vincoli:
- non costruire una dashboard grossa
- non fare refactor totale del core in questa patch
- evitare overengineering

Aree principali:
- `src/affitto_v2/scrapers/live_fetch.py`
- eventualmente `gui_app.py` / `main.py` se serve per esporre lo stato in modo minimo e coerente

Cose da fare:
1. introdurre o migliorare uno stato sintetico per sito utile al supporto
2. rendere piu leggibili outcome, cooldown, recovery e qualita di estrazione
3. migliorare log e segnali essenziali senza aumentare rumore inutile
4. mantenere approccio pragmatico, piccolo e verificabile

Alla fine restituisci:
- cosa hai implementato
- file toccati
- limiti residui
- come verificare la patch con run reali e lettura dello stato sintetico
