# ROADMAP_NEXT_MILESTONES.md

## Scopo
Definire la roadmap operativa iniziale della root `2.3_test`.

## Funzione della root
`2.3_test` non nasce per sostituire subito la `2.2`.

Serve a:
- congelare una baseline `2.2 stable` leggibile
- aprire la prossima iterazione in ambiente separato
- lavorare per patch piccole sopra una base gia consolidata

## Fase corrente
La fase corrente e `line opening / parity freeze`:
- copia completa della root precedente
- riallineamento documentale
- archivio `2.2` separato
- zero cambi intenzionali di comportamento al taglio

## Milestone 0 - Cutover Freeze

### Obiettivo
Aprire `2.3_test` senza perdere il contesto storico e senza introdurre drift involontari.

### Deliverable
- nuova root separata
- documentazione viva `2.3_*`
- archivio interno `2.2`
- manifest storico `2_2_STABLE_MANIFEST.md`

### Stato
Chiusa.

## Milestone 1 - Parity Validation

### Obiettivo
Confermare che `2.3_test` parta osservabilmente allineata alla baseline `2.2`.

### Deliverable
- verifica del working tree ereditato
- confronto di run comparabili `2.2` vs `2.3`
- chiarimento dei delta locali gia presenti al taglio

### KPI minimi
- `outcome_tier`
- `state_transition`
- `runtime_disposition`
- `service_state`

### Stato
Da chiudere prima della prima patch di prodotto.

## Milestone 2 - Site-local Refinement

### Obiettivo
Aprire il primo affinamento locale senza toccare l'intera strategia di linea.

### Candidate attuali
- `immobiliare adaptive prepare`
- `long block notification`
- `site-local soft mode`

### Regola pratica
Sceglierne uno solo per volta.

### Stato
Ancora da aprire.

## Milestone 3 - Orchestrator Readability

### Obiettivo
Proseguire la scomposizione di `live_fetch.py` solo se aiuta review, test e diagnostica.

### Deliverable
- step piu leggibili nel run loop
- responsabilita piu strette per modulo
- nessun drift comportamentale

### Stato
Secondaria rispetto a parity e primo refinement operativo.

## Milestone 4 - Promotion Gate

### Obiettivo
Promuovere solo cio che migliora davvero la baseline `2.2`.

### Deliverable
- confronto prima/dopo
- nota rischi residui
- rollback

### Stato
Futura.
