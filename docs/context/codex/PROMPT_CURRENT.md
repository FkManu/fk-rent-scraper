# PROMPT_CURRENT.md

Agisci sul progetto `affitto` nella root `2.3_test`.

## Task corrente
`2.3-patch-01` applicata — soak osservativo in corso.

## Contesto
- backend `camoufox` (Firefox-based)
- UA allineato a Firefox/135.0 (coerente con TLS fingerprint camoufox)
- `navigator.deviceMemory` non piu patchato (Firefox non lo espone)
- state machine, pacing, guard, profili: invariati rispetto alla `2.2`

## Priorita prossima
1. soak della patch su sessione reale: osservare log `navigator_user_agent` e comportamento DataDome
2. scegliere il prossimo asse tra quelli nel backlog `2.3`

## Vincoli
- niente CDP come percorso standard
- niente riapertura multi-browser
- niente bypass aggressivi
- non committare runtime, log, build o dist temporanee

## Output atteso dal prossimo step
- osservazioni dal soak (tier transitions, eventuali cambi di frequenza block)
- proposta asse successivo con ipotesi e metriche
