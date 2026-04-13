# STRATEGY_2_3_STABLE.md

## Scopo
Definire la strategia della linea `2.3_stable` come evoluzione separata della linea `2.2 stable`.

## Punto di partenza
`2.3_stable` non parte da una foundation grezza.

Parte da una base gia consolidata:
- backend operativo `camoufox`
- servizio continuo `fetch-live-service`
- profili persistenti per sito
- state machine e stop trigger gia leggibili
- refactor strutturale gia avviato del motore live

Il file guida di riferimento resta:
- `docs/risk_scoring_e_griglia_segnali_antibot.md`

## Decisione di progetto
La linea `2.3_stable` non deve riaprire in modo casuale la strategia `2.2`.

Deve invece lavorare sopra la baseline gia stabilizzata per:
- ridurre ancora il rumore locale dove i log lo giustificano
- aumentare osservabilita e recupero operativo
- completare le slice piccole rimaste aperte
- mantenere la separazione netta con la linea `2.2` considerata stable

## Confine tra `2.2 stable` e `2.3_stable`

### `2.2 stable`
Percorso shipping:
- mantenimento della linea gia consolidata
- fix prudenziali e supportabili
- packaging e validazione distribuzione
- nessun salto di strategia senza nuova evidenza

### `2.3_stable`
Percorso laboratorio disciplinato:
- refinements per-sito
- osservabilita operativa nuova
- alleggerimenti locali del costo interazionale
- ulteriori slice strutturali solo se aiutano leggibilita e sicurezza della linea

## Assi di lavoro plausibili per `2.3_stable`

### 1. `immobiliare adaptive prepare`
Obiettivo:
- eliminare passaggi meccanici inutili nella prepare phase di `immobiliare`

Vincoli:
- nessuna patch larga
- nessuna attribuzione automatica dei block al solo scroll
- confronto sempre contro la baseline `2.2`

### 2. `long block observability`
Obiettivo:
- notificare in modo leggibile quando un sito resta in blocco lungo
- notificare anche la recovery

Vincoli:
- una sola notifica di ingresso
- una sola notifica di recovery
- niente rumore di alert ad ogni ciclo

### 3. `site-local soft mode`
Obiettivo:
- ridurre la pressione per `1-2` cicli solo sul sito che ha appena preso `hard_block`

Vincoli:
- non toccare la cadence globale del servizio
- non degradare l'altro sito

### 4. `orchestrator readability`
Obiettivo:
- continuare la scomposizione di `live_fetch.py` solo se migliora leggibilita e reviewability

Vincoli:
- nessun refactor comportamentale mascherato
- test e log invariati come contratto osservabile

## Principi guida

### 1. Preservare prima di cambiare
La linea `2.2.2 refactorizzata` e la baseline pratica di partenza.

Ogni patch `2.3_stable` deve dire esplicitamente:
- cosa preserva
- cosa cambia
- come si confronta con `2.2`

### 2. Un asse sperimentale per volta
Non aprire patch che mischiano:
- prepare phase
- notifiche
- lifecycle del servizio
- parser quality
- packaging

### 3. Misurare prima di promuovere
Le patch della `2.3_stable` devono essere confrontabili su soak, log e costo operativo.

### 4. Nessun ritorno a scorciatoie dismesse
Restano fuori scope:
- multi-browser comeback
- CDP come percorso standard
- spoofing aggressivo
- pre-heating esterni
- patch speculative fuori dai sintomi reali

## Output atteso della linea
La `2.3_stable` deve diventare:
- una linea di evoluzione pulita della `2.2`
- con backlog piu stretto
- con contesto storico chiaro
- con meno ambiguita tra stato vivo e archivio
