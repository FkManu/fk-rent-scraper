# CLI test matrix (cascade options)

Questa guida permette di testare il comportamento che poi verra esposto nella GUI `.exe`.

## Comandi disponibili

- `init-config`
- `validate-config`
- `init-db`
- `doctor`
- `init-email-profiles`
- `list-email-profiles`
- `upsert-email-profile`
- `email-status`
- `test-email`
- `test-pipeline`
- `fetch-live-once`
- `gui`

## 0) GUI base (preset + custom advanced)

Avvio:

```powershell
python run.py gui
```

Azioni GUI aggiunte:
- `Reset Site Guard`
- `Reset DB Annunci` (cancella solo tabella `listings`, mantiene blacklist/pattern)
- `Run Once` usa il percorso operativo reale del ramo, senza bypass automatici del cooldown
- setup email semplice:
  - provider preset
  - mittente
  - username / API key
  - password / secret
  - destinatario
  - stato email
  - `Test connessione`
  - `Test invio`
  - `custom` advanced:
    - host SMTP
    - porta
    - sicurezza (`STARTTLS` / `SSL/TLS (implicito)` / `Nessuna sicurezza`)
- un solo `Salva Configurazione`
- GUI divisa in tab:
  - `Configurazione`
  - `Runtime`
  - `Log`
  - `Aiuto`
- azioni operative dentro `Configurazione`:
  - `Salva Configurazione`
  - `Run Once`
  - `Start Ciclo Automatico`
  - `Stop`
  - `Reset Site Guard`
  - `Reset DB Annunci`
  - `Avvio automatico GUI`
  - `Applica Avvio Automatico`
- lock canali coerente:
  - `telegram` -> email bloccata
  - `email` -> telegram bloccato
  - `both` -> entrambi attivi

La GUI semplice usa il backend reale:
- stato da `email-status` / `email_setup.py`
- test da `test-email`
- segreti nel profilo attivo DPAPI
- `custom` ora usa lo stesso backend ma con campi advanced mostrati solo quando il provider selezionato e `custom`
- secret gia presente mantenuto se il campo password viene lasciato invariato / vuoto
- tab `Aiuto` ora espone il flusso consigliato:
  - configura
  - salva
  - testa
  - `Run Once`
  - controlla i log
  - poi ciclo automatico

## 0-bis) Primo `.exe` stabile (Windows)

Build:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-packaging.txt
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_bundle.ps1
```

Output atteso:
- `dist\affitto_gui\affitto_gui.exe`
- `dist\affitto_gui\affitto_cli.exe`

Prerequisito browser consigliato per Windows/VM:
- backend `Camoufox` gia fetchato sulla macchina
- comando standard:

```powershell
.\.venv\Scripts\python.exe -m camoufox fetch
```

- note:
  - la GUI e il companion CLI ora usano `camoufox` come default
  - gli alias legacy del vecchio routing browser restano accettati solo per compatibilita CLI

Smoke test bundle:
1. imposta un runtime isolato con `AFFITTO_V2_RUNTIME_DIR`
2. avvia `affitto_gui.exe`
3. verifica creazione di:
   - `app_config.json`
   - `logs\app.log`
4. esegui:

```powershell
.\dist\affitto_gui\affitto_cli.exe validate-config --config "$env:AFFITTO_V2_RUNTIME_DIR\app_config.json"
```

Artefatto stable utile per consegna locale o release:
- `dist\affitto_2_2_1_stable_bundle.zip`

Note runtime bundle:
- da sorgente resta `runtime`
- da bundle il default e `%LOCALAPPDATA%\AffittoV2\runtime`

## 1) Default sender profile (setup una volta)

Inizializza file profili:

```powershell
python run.py init-email-profiles
```

Crea/aggiorna profilo mittente (default consigliato):

```powershell
python run.py upsert-email-profile `
  --profile-id default_sender `
  --profile-provider gmail `
  --profile-from your.sender@gmail.com `
  --profile-user your.sender@gmail.com `
  --profile-password "your_app_password"
```

Provider supportati in Patch 1:
- `gmail`
- `outlook`
- `brevo`
- `mailjet`
- `smtp2go`
- `resend`
- `custom`

Per custom advanced:

```powershell
python run.py upsert-email-profile `
  --profile-id relay_sender `
  --profile-provider custom `
  --profile-from no-reply@example.com `
  --profile-user smtp_user `
  --profile-password "smtp_secret" `
  --profile-host smtp.example.com `
  --profile-port 465 `
  --profile-security-mode ssl_tls
```

Compat legacy:
- `--profile-starttls true|false` resta disponibile, ma il campo nuovo da preferire e `--profile-security-mode`.

Visualizza profili:

```powershell
python run.py list-email-profiles
```

## 2) Modalita semplificata utente finale (profilo attivo)

In `runtime/app_config.json`:

```json
"email": {
  "enabled": true,
  "sender_mode": "profile",
  "sender_profile_id": "default_sender",
  "to_address": "destinatario@example.com"
}
```

Test connessione SMTP:

```powershell
python run.py test-email --dry-run
```

Leggi stato backend email:

```powershell
python run.py email-status
```

Invio reale:

```powershell
python run.py test-email --email-subject "Test" --email-body "OK"
```

Stati backend email introdotti:
- `not_configured`
- `incomplete_placeholder`
- `profile_missing`
- `profile_unreadable`
- `configured_unverified`
- `connection_ok`
- `send_ok`
- `error`

## 3) Test pipeline (dry-run, no invio reale)

```powershell
python run.py test-pipeline `
  --notify-mode both `
  --simulate-run-id run01 `
  --simulate-count 5 `
  --simulate-site idealista `
  --simulate-duplicate `
  --simulate-blocked-agency `
  --blocked-pattern ".*testspam.*"
```

Nota:
- `--notify-mode` forza i canali solo per il test corrente (a meno che non usi `--save-overrides`).

## 4) Test pipeline con invio reale notifiche

```powershell
python run.py test-pipeline `
  --notify-mode both `
  --simulate-run-id run02 `
  --simulate-count 2 `
  --send-real-notifications
```

Comportamento notifiche:
- Email: 1 sola mail digest per ciclo (contiene tutti i nuovi annunci del ciclo).
- Telegram: 1 messaggio per annuncio.
- Digest email (fine tuning):
  - mostra solo campi valorizzati (niente placeholder `-`)
  - include `Sito` per annuncio
  - `Zona` solo se non gia implicita nel titolo
  - aggiunge timestamp digest + riepilogo per sito

Nota modello email:
- i file nuovi usano `security_mode`
- i file legacy con `use_starttls` continuano a essere caricati

Hardening runtime Patch 5:
- bootstrap notifier isolato per canale
- failure email/Telegram loggati senza crash globale della pipeline
- summary finale con `email_failures` / `telegram_failures`
- `fetch-live-once` mantiene semantica one-shot e logga stop pulito se il fetch fallisce prima della pipeline

## 5) Override a cascata (come futura GUI)

Override runtime/extraction/email senza modificare file:

```powershell
python run.py test-pipeline `
  --override-cycle-minutes 5 `
  --override-max-listings-per-page 40 `
  --override-captcha-mode skip_and_notify `
  --override-extract-fields price,zone,agency `
  --email-to destinatario@example.com
```

Per salvare gli override in `app_config.json`:

```powershell
python run.py test-pipeline --override-cycle-minutes 10 --save-overrides
```

## 6) Live fetch (siti reali) + pipeline

Ciclo reale singolo (no invio reale):

```powershell
python run.py fetch-live-once --notify-mode config
```

Debug in browser visibile:

```powershell
python run.py fetch-live-once --headed --max-per-site 20 --notify-mode config
```

Profilo persistente (consigliato):

```powershell
python run.py fetch-live-once --headed --notify-mode config --profile-dir .\runtime\camoufox-profile
```

Backend esplicito Camoufox:

```powershell
python run.py fetch-live-once --headed --notify-mode config --browser-channel camoufox
```

Site guard completo (jitter + classificazione outcome + cooldown):

```powershell
python run.py fetch-live-once --headed --notify-mode both --send-real-notifications --browser-channel camoufox --guard-jitter-min-sec 2 --guard-jitter-max-sec 6 --guard-base-cooldown-min 30 --guard-max-cooldown-min 360
```

Nota backend:
- `camoufox` e il backend operativo predefinito.
- l'unico contratto supportato lato CLI e `auto|camoufox`.
- il launch predefinito usa fingerprint Windows con `locale=it-IT`, `timezone=Europe/Rome`, `humanize=True` e `screen` Camoufox vincolato a `1920x1080`, senza piu forzare una `window` fissa.
- il contesto pagina registra anche un `init_script` globale per coerenza cross-host:
  - `navigator.deviceMemory=16`
  - `navigator.hardwareConcurrency=8`
  - WebGL vendor/renderer stabili
  - `Canvas.toDataURL()` con rumore statico deterministico
- le interazioni chiave (`goto`, `click`, `close`) passano ora da un pacing asincrono adattivo basato su distribuzione Gamma.
- prima della `page` operativa il setup browser esegue anche un bootstrap tecnico delle static resources comuni su:
  - `https://www.gstatic.com/generate_204`
  - `https://www.google.it/generate_204`
  - `https://www.cloudflare.com/cdn-cgi/trace`
  - navigazione su pagina temporanea con `wait_until="commit"` e chiusura immediata

Nota outcome:
- il fetch live distingue ora `healthy`, `suspect`, `degraded`, `blocked`, `cooling`
- esempi concreti:
  - `empty_legit`
  - `empty_suspicious`
  - `challenge_visible`
  - `hard_block`
  - `hard_block_http_status`
  - `interstitial_datadome`
  - `timeout_network`
  - `parse_issue`
  - `fallback_dominant`
  - `partial_success_degraded`
  - `parser_drift`

Reset stato guard (pulisce cooldown/strikes prima della run):

```powershell
python run.py fetch-live-once --guard-reset-state
```

Ignora cooldown attivo solo per questa run:

```powershell
python run.py fetch-live-once --guard-ignore-cooldown
```

Disattivare guardrail (solo debug avanzato):

```powershell
python run.py fetch-live-once --disable-site-guard
```

Con pausa captcha manuale (se `runtime.captcha_mode = pause_and_notify`):

```powershell
python run.py fetch-live-once --headed --notify-mode config --captcha-wait-sec 180
```

Forza pausa captcha da CLI (senza modificare il config):

```powershell
python run.py fetch-live-once --headed --notify-mode config --override-captcha-mode pause_and_notify --captcha-wait-sec 300
```

Salva artifact di debug live (html+screenshot + guard event json) quando entra in stato sospetto/degradato/bloccato:

```powershell
python run.py fetch-live-once --notify-mode none --max-per-site 1 --save-live-debug
```

Nota:
- se la pagina e un blocco statico non interattivo (non captcha risolvibile), `pause_and_notify` non attende il timeout completo.
- su pagine normali con script anti-bot nascosti non viene piu attivato il captcha solver (ridotti falsi positivi).
- in `skip_and_notify` + `--headed`, se viene rilevata challenge verifica dispositivo/captcha, viene fatta una breve auto-attesa prima di classificare `blocked`.
- un `200` con contenuto sospetto/vuoto non viene piu trattato automaticamente come successo.
- retry automatico: massimo uno, solo su outcome transienti/sospetti marcati come retryable.
- la patch non introduce retry aggressivi cross-browser sullo stesso URL.
- parse fail / drift non vengono scambiati automaticamente per hard block.
- su fetch riuscite vengono ora loggate metriche minime di qualità:
  - cards
  - percentuale campi mancanti
  - fallback si/no
- quando il parser degrada, `runtime/live_debug` puo contenere anche JSON diagnostici dedicati al drift.

Invio reale notifiche:

```powershell
python run.py fetch-live-once --notify-mode both --send-real-notifications
```

## 6-bis) Matrix pratica Camoufox su VM

Caso operativo attuale:
- `Camoufox` e l'unico backend raccomandato nel ramo `2.2_test`
- il focus della VM non e piu scegliere tra browser diversi, ma verificare continuita di sessione e profilo persistente

Passi suggeriti:
1. eseguire il fetch di Camoufox sulla VM
2. eseguire:

```powershell
python run.py fetch-live-once --headed --notify-mode none --browser-channel camoufox --channel-rotation-mode off --max-per-site 5 --save-live-debug
```

3. verificare nei log:
- `Using persistent Camoufox profile. site=...`
- `Fetch URL result. site=... channel=camoufox`
- eventuali `interstitial_datadome` o `hard_block_http_status`

Esito atteso:
- il supporto riesce a vedere che il backend attivo e `camoufox`
- il guard state conserva ultimo backend valido e ultima famiglia di blocco rilevata
