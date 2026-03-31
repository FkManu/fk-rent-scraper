# STRATEGY_2_2_TEST.md

## Scopo
Definire la strategia della linea `2.2_test` come preview separata dalla baseline `2.1_stable`.

`2.1_stable` resta la base viva distribuibile e supportabile.
`2.2_test` esiste solo per sperimentare una strategia live piu silenziosa, meno meccanica e piu centrata sulla continuita di sessione.

## Pietra miliare da seguire
Il file guida da considerare riferimento stabile per questa linea e:

- `docs/risk_scoring_e_griglia_segnali_antibot.md`

Questo documento non va trattato come nota accessoria.
Va trattato come:
- baseline concettuale
- check-list di famiglie di segnali
- lente per leggere i sintomi reali nei log
- vincolo strategico contro soluzioni troppo semplicistiche

## Decisione di progetto
Il problema non e piu soltanto:
- evitare hard block
- recuperare il singolo run
- migliorare qualche selector o qualche retry

Il problema vero diventa:
- abbassare i segnali meccanici
- aumentare la continuita di sessione
- separare meglio identita, pacing e recovery per sito
- ridurre i costi interazionali inutili

## Copertura attuale contro la griglia dei segnali

### Coperto in modo utile
- continuita di sessione e identita per sito
- riduzione del churn di owner/browser nello stesso run
- pacing e retry meno impulsivi
- osservabilita di stato, budget e stop reason
- orchestrazione continua 24/7 con cadenza esplicita sopra il one-shot

### Coperto solo in parte
- continuita lunga di sessione tra molti cicli consecutivi
- backlog operativo e degrado di servizio nel loop continuo
- mapping esplicito tra stato del run e stato del servizio
- recovery assistita come percorso specialistico ma non ancora operativo

### Non ancora coperto davvero
- reputazione rete e segnali a livello IP/ASN
- TLS / transport fingerprint
- JS runtime / device checks lato sito
- validazione soak lunga che provi tenuta reale su molte ore

## Regola di lettura importante
Il file `risk_scoring_e_griglia_segnali_antibot.md` va usato come matrice di copertura.

Non basta chiedersi:
- se il fetch funziona

Bisogna chiedersi:
- quali famiglie di segnali stiamo gia riducendo
- quali stiamo solo osservando
- quali oggi non governiamo affatto

## Runtime disposition policy
La continuita di sessione non va difesa in modo dogmatico.

Quando un ciclo segnala degrado o stop, il ramo deve decidere tra:
- `keep`
- `recycle_site_slot`
- `recycle_runtime`
- `stop_service`

Ordine di preferenza:
- prima preservare il runtime
- poi riciclare solo lo slot del sito coinvolto
- solo dopo riciclare tutto il runtime condiviso
- fermare il servizio quando il run richiede davvero assistenza

## Confine tra `2.1_stable` e `2.2_test`

### `2.1_stable`
Percorso shipping:
- bugfix
- packaging
- validazione VM
- hardening piccolo e supportabile
- nessuna rivoluzione del motore live
- ottimizzazione di robustezza shipping pragmatica

### `2.2_test`
Percorso laboratorio:
- modello di sessione diverso
- ownership piu esplicita di browser/context/page
- policy piu prudenti su pacing e recovery
- profili persistenti per sito
- modalita browser reale assistita opzionale
- osservabilita orientata a continuita e costo interazionale
- ottimizzazione di continuita e riduzione del rumore

## Obiettivo della linea `2.2_test`
Passare da una strategia centrata su:
- fetch riuscito
- cooldown
- retry prudente
- autohealing reattivo

a una strategia centrata su:
- session continuity first
- identita stabile per sito
- navigazione parsimoniosa
- recovery assistita quando il trust scende
- arresto pulito invece di reazione impulsiva

## Principi guida

### 1. Meno rumore, non piu aggressivita
Ogni patch deve ridurre:
- cambi identita inutili
- retry nello stesso run
- aperture dettaglio ridondanti
- chiusure e riaperture troppo frequenti

### 2. La sessione e un asset
Cookie, memoria di contesto, storico di navigazione e profilo non sono dettaglio tecnico.
Sono parte della stabilita operativa.

### 3. Separazione forte per sito
Per ogni sito devono poter divergere:
- profilo
- pacing
- stato di fiducia
- recovery policy
- budget interazionale

### 4. Browser alternativo non come reflex
Cambiare browser nel mezzo dello stesso run va trattato come cambio identita.
Non come fallback standard.

### 5. Browser reale solo come modalita specialistica
Una modalita browser reale assistita puo avere senso per:
- bootstrap iniziale
- recovery dopo challenge
- sessioni gia calde

Ma non deve diventare il default del motore.

### 6. Fermarsi bene vale piu di insistere male
Quando il contesto si degrada:
- meno recovery automatica impulsiva
- piu freeze controllato
- piu log leggibili
- piu recovery assistita

## Modalita operative da esplorare

### A. `managed_stable`
Percorso standard di automazione prudente.

Caratteristiche:
- profilo persistente dedicato per sito
- niente retry cross-browser immediato di default
- pacing piu conservativo
- budget di pagine/dettagli per run
- stop pulito quando il rischio sale

### B. `real_browser_assisted`
Percorso specialistico opzionale.

Caratteristiche:
- browser reale gia aperto
- profilo dedicato
- aggancio tipo CDP
- nessuna chiusura automatica del browser fisico
- uso limitato a bootstrap o recovery assistita

Questa modalita va separata in due casi:

#### `cdp_bootstrap`
Per:
- warm session iniziale
- challenge iniziale
- allineamento manuale del profilo reale

#### `cdp_recovery`
Per:
- sessione degradata ma ancora recuperabile
- trust basso dopo challenge o interstitial
- recupero assistito senza cambiare il modello standard del ramo

## Milestone iniziali consigliate

### 1. Session Model Reset
- profili persistenti per sito
- fine del riuso implicito della stessa sessione tra siti
- ownership piu chiara di browser/context/page

### 2. Silent Risk Policy
- niente retry cross-browser immediato di default
- risk budget per run
- pacing piu prudente
- arresto pulito su contesto sospetto

### 3. Real Browser Assisted Mode
- spike CLI-only
- aggancio a browser reale gia aperto
- distinzione esplicita tra `cdp_bootstrap` e `cdp_recovery`
- uso solo manuale/assistito

### 4. Observability for Silence
- metriche nuove su continuita e costo interazionale
- log orientati a identita, budget e ragioni di stop

## Metriche da introdurre o monitorare
- `session_age`
- `same_site_profile`
- `identity_switch`
- `detail_touch_count`
- `risk_pause_reason`
- `cooldown_origin`
- `reused_cookie_context`
- `browser_mode`
- `state_transition`
- `assist_entry_mode`

## Non-obiettivi
- bypass aggressivi anti-bot
- guerra infinita contro il browser automation stack
- spoofing spinto come asse principale
- patchone unico che mischia packaging, parser e strategia live
- GUI avanzata prima di avere il modello giusto

## Regola pratica
Se una patch cambia il modello di sessione o la strategia di interazione col sito:
- va in `2.2_test`

Se una patch serve solo a rendere piu robusta la baseline attuale:
- resta in `2.1_stable`

## Output atteso di questa strategia
La preview `2.2_test` deve restare allineata a:
- charter chiaro
- milestone iniziali piccole e verificabili
- dipendenza esplicita dal file `risk_scoring_e_griglia_segnali_antibot.md`
- nessuna ambiguita sul fatto che sia un laboratorio disciplinato
