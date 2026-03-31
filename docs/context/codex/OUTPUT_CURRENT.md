# OUTPUT_CURRENT.md

## Patch corrente
`2.3-patch-01` - Allineamento UA/TLS Firefox/135.0 + rimozione patch `navigator.deviceMemory`.

## Stato
Patch applicata. Codice verificato. In attesa di soak su sessione reale.

Backend operativo: `camoufox`. State machine, pacing, guard, profili: invariati.

## Implementazione eseguita nella patch

### File modificati
- `src/affitto_v2/scrapers/browser/session_policy.py`
  - `_DEFAULT_USER_AGENT`: Chrome/134 -> Firefox/135.0
- `src/affitto_v2/scrapers/render_context.py`
  - `HardwareMimetics` inline (x2): UA Chrome -> Firefox/135.0
  - rimossa `defineNavigatorValue('deviceMemory', ...)` dal template JS
  - rimossa sostituzione `__DEVICE_MEMORY__` nel builder
  - rimosso campo `navigator_device_memory` dal log

### Motivazione
camoufox e Firefox-based. Il TLS fingerprint e Firefox. Dichiarare Chrome/134 come UA creava un mismatch rilevabile passivamente (JA4, DataDome, Cloudflare). `navigator.deviceMemory` e una proprieta Chrome-only: patcharla su Firefox segnalava un'ulteriore anomalia JS.

### Cosa NON e cambiato
- comportamento di rotazione profili
- state machine e guard
- pacing Gamma
- bootstrap static resources
- DataDome challenge detection
- WebGL strings e hardwareConcurrency

## Nota residua
- `requirements.txt` porta avanti `undetected-playwright==0.3.0` dalla root sorgente; incluso nel primo rilascio `2.3_test`, ma senza un nuovo path operativo dichiarato nel codice prodotto

## Prossime slice plausibili
- soak osservativo della patch UA/TLS su sessione reale
- `immobiliare adaptive prepare`
- notifica blocco lungo `>= 1h` + recovery
- `soft mode` locale post-`hard_block`
