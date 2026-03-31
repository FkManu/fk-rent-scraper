# REVIEW_CURRENT.md

## Patch corrente
`2.3-patch-01` - Allineamento UA/TLS Firefox/135.0 + rimozione patch `navigator.deviceMemory`

## Stato review
Patch applicata. Verifica statica completata. Soak su sessione reale non ancora eseguito.

## Focus della review
- coerenza UA tra `session_policy.py`, `render_context.py` e UA interno camoufox
- assenza di `navigator.deviceMemory` nel template JS generato
- assenza di riferimenti Chrome/134 nel codice prodotto
- invarianza comportamentale su tutto il resto (guard, pacing, profili)

## Esito sintetico
- UA Firefox/135.0 coerente in tutti e tre i punti: HTTP header, TLS fingerprint, navigator.userAgent JS
- `navigator.deviceMemory` rimosso dal template JS (Firefox non lo espone)
- log `install_render_context_init_script` aggiornato di conseguenza
- nessun altro file di codice prodotto modificato
- verifica programmatica eseguita: policy.user_agent Firefox su entrambi i siti, deviceMemory=False nel script

## Rischi residui
- soak non ancora eseguito: non e noto se il cambio UA modifica il comportamento di DataDome o dei siti
- WebGL strings (Intel Iris Xe) e hardwareConcurrency (8) restano fissi su tutti i profili - non affrontati in questa patch
- `requirements.txt` porta avanti `undetected-playwright==0.3.0` dalla root sorgente; incluso nel primo rilascio `2.3_test` senza nuovi hook di codice dedicati
