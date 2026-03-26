# TASK_2_2_TEST_SILENT_SESSION_STRATEGY.md

## Titolo task
2.2_test strategy / silent session architecture

## Owner
Manager + Backend / Codex

## Stato
Ready

## Priorita
Alta, ma fuori dalla baseline shipping `2.1_stable`

## Contesto
La baseline `2.1_stable` e oggi il percorso shipping del progetto.
Ha gia:
- packaging stabile
- site guard prudente
- browser routing pragmatico
- `private_only` piu parsimonioso
- validazione VM concreta

Ma il file:
- `docs/risk_scoring_e_griglia_segnali_antibot.md`

ha cambiato il quadro strategico.

La lettura corretta ora e:
- il rischio moderno nasce da session continuity, sequence awareness, device/runtime checks e scoring composito
- alcune scelte oggi pragmatiche in `2.1_stable` restano troppo rumorose per una linea piu silenziosa
- la prossima evoluzione va esplorata in una nuova linea separata, non stratificata dentro la baseline shipping

## Obiettivo
Preparare l'architettura iniziale della futura linea `2.2_test` con focus su:
- session continuity first
- identita stabile per sito
- pacing piu prudente
- recovery assistita invece di fallback impulsivo
- osservabilita orientata al costo interazionale

## Non-obiettivi
- non implementare bypass aggressivi
- non inseguire flag stealth isolate
- non spostare subito la GUI sulla nuova linea
- non aprire nuove feature prodotto non collegate al motore live
- non fare packaging/release work dentro questo task

## Risultato desiderato
Avere una base progettuale e tecnica chiara per aprire `2.2_test` come nuova directory, con:
- modalita operative definite
- confini chiari rispetto a `2.1_stable`
- primi componenti o stub architetturali, se sensati
- primo task tecnico piccolo e verificabile

## Direzioni implementative desiderate

### 1. Modello di sessione esplicito
Separare in modo piu netto:
- browser ownership
- context ownership
- page ownership
- profilo persistente per sito

### 2. Modalita operative
Preparare almeno a livello architetturale:
- `managed_stable`
- `real_browser_assisted`

### 3. Policy di rischio piu silenziosa
Sostituire la logica di recovery piu impulsiva con:
- risk budget per run
- limiti di pagine/dettagli
- stop pulito
- freeze/recovery assistita

### 4. Osservabilita nuova
Preparare telemetria orientata a:
- `identity_switch`
- `detail_touch_count`
- `session_age`
- `risk_pause_reason`
- `browser_mode`

## File/area coinvolta
Strategia/docs:
- `docs/context/STRATEGY_2_2_TEST.md`
- `docs/risk_scoring_e_griglia_segnali_antibot.md`

Possibile area tecnica futura:
- nuova directory `2.2_test/`

## Cosa implementare in questo task
### 1. Definire il perimetro di `2.2_test`
Chiarire:
- cosa ci entra
- cosa resta in `2.1_stable`
- quali patch sono ammesse

### 2. Definire i due browser mode
Specificare responsabilita e vincoli di:
- `managed_stable`
- `real_browser_assisted`

### 3. Definire la policy minima di rischio
Stabilire principi per:
- no retry cross-browser immediato di default
- profili per sito
- pacing prudente
- recovery assistita

### 4. Definire il primo passo tecnico concreto
Produrre il primo task piccolo e verificabile da svolgere davvero nella nuova linea.

## Output atteso
- strategia `2.2_test` chiara
- milestone iniziali definite
- primo task tecnico pronto
- nessuna ambiguita tra baseline shipping e laboratorio

## Criteri di accettazione
1. `2.1_stable` resta chiaramente protetta come baseline shipping.
2. `2.2_test` ha obiettivo stretto e non diventa contenitore caotico.
3. Il file `risk_scoring_e_griglia_segnali_antibot.md` e esplicitamente trattato come riferimento guida.
4. Le prime milestone sono piccole, verificabili e coerenti con il problema reale.
5. La strategia e orientata a meno rumore e piu continuita, non a piu aggressivita.

## Prompt finale per Codex
Agisci sul progetto `affitto` partendo dalla baseline `2.1_stable`.

Task: prepara la strategia operativa della futura linea `2.2_test` come laboratorio separato centrato su **silent session strategy**.

Contesto:
- `2.1_stable` e la baseline shipping viva
- il file `docs/risk_scoring_e_griglia_segnali_antibot.md` va trattato come pietra miliare della nuova direzione
- i problemi reali non sono piu solo hard block e retry, ma session continuity, sequence awareness, identita stabile e riduzione del rumore operativo

Obiettivo:
- definire confine tra `2.1_stable` e `2.2_test`
- chiarire le modalita `managed_stable` e `real_browser_assisted`
- definire milestone iniziali piccole e verificabili
- proporre il primo task tecnico concreto per la nuova linea

Vincoli:
- non introdurre bypass aggressivi
- non trasformare `2.2_test` in patchone disordinato
- non spostare subito la GUI o il packaging nel nuovo laboratorio

Alla fine restituisci:
- strategia definita
- milestone iniziali
- primo task tecnico consigliato
- rischi e limiti da tenere sotto controllo
