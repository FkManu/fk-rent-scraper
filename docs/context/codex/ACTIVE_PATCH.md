# ACTIVE_PATCH.md

## Patch corrente
`2.3-patch-01` — Allineamento UA/TLS: Chrome UA → Firefox/135.0 + rimozione patch `navigator.deviceMemory`

## Obiettivo
Eliminare l'inconsistenza TLS/UA ereditata dalla `2.2`:
- camoufox e Firefox-based, il TLS fingerprint e Firefox
- il UA dichiarato era Chrome/134 → mismatch rilevabile passivamente (JA4, DataDome, Cloudflare)
- `navigator.deviceMemory` veniva patchato a `16` ma Firefox non espone questa proprieta → anomalia JS

## Scope
- `src/affitto_v2/scrapers/browser/session_policy.py` — UA Chrome → Firefox/135.0
- `src/affitto_v2/scrapers/render_context.py`:
  - UA nei HardwareMimetics inline aggiornato a Firefox/135.0
  - rimossa riga `defineNavigatorValue('deviceMemory', ...)` dal template JS
  - rimossa sostituzione `__DEVICE_MEMORY__` nel builder
  - aggiornato log `install_render_context_init_script` (rimosso campo `navigator_device_memory`)

## Non-scope
- nessuna variazione a state machine, pacing, guard, profili
- nessun cambio a `live_fetch.py` (policy.user_agent viene letto automaticamente)
- nessuna variazione a WebGL strings o hardwareConcurrency
- nessuna variazione al canvas noise

## Invarianti preservati
- comportamento di rotazione profili invariato
- pacing Gamma invariato
- bootstrap static resources invariato
- DataDome detection invariata
- session continuity invariata

## Done quando
- `session_policy.py` usa Firefox/135.0 su entrambi i siti
- `render_context.py` non patcha piu `navigator.deviceMemory`
- UA coerente tra TLS handshake, HTTP header e `navigator.userAgent` JS
- nessun riferimento a Chrome/134 nel codice prodotto

## Stato
COMPLETO — in attesa di soak su sessione reale
