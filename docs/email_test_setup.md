# Email test setup (Preset SMTP / Custom SMTP)

## 1) Prepare runtime

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_test_env.ps1
python run.py init-config
```

## 2) Update config

Edit `runtime/app_config.json`:

```json
"email": {
  "enabled": true,
  "sender_mode": "custom",
  "sender_profile_id": "default_sender",
  "provider": "gmail",
  "from_address": "your.address@gmail.com",
  "to_address": "your.address@gmail.com",
  "smtp_username": "your.address@gmail.com",
  "app_password": "your_app_password",
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "security_mode": "starttls"
}
```

Preset providers supported in Patch 1:
- `gmail`
- `outlook`
- `brevo`
- `mailjet`
- `smtp2go`
- `resend`
- `custom`

Notes:
- for preset providers, host/port/security mode are auto-filled if omitted
- legacy `use_starttls` is still accepted on load and migrated logically to `security_mode` on next save
- `security_mode = none` is allowed only for `provider = custom`

Alternative recommended mode (shared sender profile):

1) Create profile file:

```powershell
python run.py init-email-profiles
```

2) Upsert shared sender:

```powershell
python run.py upsert-email-profile --profile-id default_sender --profile-provider gmail --profile-from your.sender@gmail.com --profile-user your.sender@gmail.com --profile-password "your_app_password"
```

3) In `app_config.json` set:

```json
"email": {
  "enabled": true,
  "sender_mode": "profile",
  "sender_profile_id": "default_sender",
  "to_address": "destinatario@example.com"
}
```

Note importanti su sicurezza/config:
- I segreti del profilo mittente (`smtp_username`, `app_password`) sono salvati cifrati in `runtime/email_profiles.json` (Windows DPAPI).
- Con `sender_mode = "profile"`, i campi SMTP custom in `runtime/app_config.json` vengono puliti automaticamente (resta visibile solo `to_address` + `sender_profile_id`).
- Nuovi file salvati usano `security_mode`; i file legacy con `use_starttls` restano leggibili.
- In bundle `.exe`, il runtime non vive dentro la cartella temporanea del bundle:
  - default `%LOCALAPPDATA%\AffittoV2\runtime`
  - override possibile con `AFFITTO_V2_RUNTIME_DIR`

## 2-ter) GUI email (Patch 3 + Patch 4)

La GUI base ora permette sia il setup semplice con preset, sia il setup completo `Custom SMTP`, senza modificare JSON a mano:

```powershell
python run.py gui
```

Flusso consigliato:
1. scegli `notify mode = email` oppure `both`
2. seleziona un provider preset
3. inserisci mittente, username/API key, password/secret e destinatario
4. nella stessa tab `Configurazione` premi `Salva Configurazione`
5. verifica lo stato email mostrato in GUI
6. usa `Test connessione`
7. usa `Test invio`

Note GUI:
- la GUI salva il setup nel profilo mittente attivo cifrato DPAPI
- lo stato mostrato in GUI arriva dal backend `email_setup.py`
- i pulsanti GUI `Test connessione` / `Test invio` riusano il comando/backend `test-email`
- con `notify mode = telegram` la sezione email resta visibile ma bloccata
- con `notify mode = email` la sezione telegram resta bloccata
- con provider preset la GUI resta nel percorso semplice e non mostra host/porta/security
- con `custom` la GUI mostra anche:
  - host SMTP
  - porta
  - sicurezza (`STARTTLS`, `SSL/TLS (implicito)`, `Nessuna sicurezza`)
- se esiste gia un setup custom valido, la GUI lo rilegge e lo salva senza perdita
- se il secret esiste gia e il campo password resta vuoto, il salvataggio lo preserva
- la tab `Aiuto` ora spiega il flusso operativo corretto:
  - configura
  - salva
  - testa
  - `Run Once`
  - controlla i log
  - solo dopo attiva il ciclo automatico

## 2-bis) Usare un provider SMTP relay (non Gmail)

Il progetto supporta provider SMTP esterni in due modi:

1) `sender_mode = "custom"` direttamente in `app_config.json` (provider `custom` + host/porta/credenziali SMTP).
2) profilo mittente (`upsert-email-profile`) con `--profile-provider custom`.

Esempio profilo custom:

```powershell
python run.py upsert-email-profile `
  --profile-id relay_sender `
  --profile-provider custom `
  --profile-from no-reply@yourdomain.tld `
  --profile-user smtp_user `
  --profile-password "smtp_password_or_api_key" `
  --profile-host smtp.your-provider.tld `
  --profile-port 587 `
  --profile-security-mode starttls
```

Per SSL/TLS implicito:

```powershell
python run.py upsert-email-profile `
  --profile-id relay_sender_ssl `
  --profile-provider custom `
  --profile-from no-reply@yourdomain.tld `
  --profile-user smtp_user `
  --profile-password "smtp_password_or_api_key" `
  --profile-host smtp.your-provider.tld `
  --profile-port 465 `
  --profile-security-mode ssl_tls
```

Per compat legacy resta disponibile anche:

```powershell
python run.py upsert-email-profile --profile-starttls true
```

Poi in `runtime/app_config.json`:

```json
"email": {
  "enabled": true,
  "sender_mode": "profile",
  "sender_profile_id": "relay_sender",
  "to_address": "destinatario@example.com"
}
```

## 3) Validate and test

Validate config:

```powershell
python run.py validate-config
```

Important:
- `validate-config` validates the local config model.
- it does **not** mean the email setup is already verified.
- un errore email/Telegram durante `test-pipeline` o `fetch-live-once` non deve piu abbattere l'intera pipeline se gli altri moduli possono continuare.

Check the real backend email status:

```powershell
python run.py email-status
```

Check SMTP auth only:

```powershell
python run.py test-email --dry-run
```

This updates the persisted email state for the current effective configuration.

Send real test email:

```powershell
python run.py test-email --email-subject "Affitto v2 test" --email-body "SMTP is OK."
```

This stores a distinct "send test" result, stronger than a connection-only result.

## 4) Common errors

- `Email notifications are disabled in config`:
  set `email.enabled` to `true`.
- `Configurazione email incompleta o con placeholder...`:
  config/profile looks syntactically valid but still contains template values like `sender@example.com` or `REPLACE_*`.
- `Email sender profile '...' not found ...`:
  profile missing; this is a profile-resolution problem, not SMTP.
- `Unable to decrypt email profile secret(s)...`:
  DPAPI/profile decryption issue; this is surfaced before SMTP and treated as profile unreadable.
- `SMTP connection/login failed`:
  check provider settings, app password, firewall.
- `security_mode='none' is allowed only for provider='custom'`:
  plain SMTP senza TLS e consentito solo per custom SMTP.

## 4-bis) Stati backend email introdotti in Patch 2

`python run.py email-status` puo riportare almeno:

- `not_configured`
- `incomplete_placeholder`
- `profile_missing`
- `profile_unreadable`
- `configured_unverified`
- `connection_ok`
- `send_ok`
- `error`

Logica pratica:
- `validate-config` -> modello/config locale
- `configured_unverified` -> config risolta e coerente, ma non ancora testata su questa fingerprint
- `connection_ok` -> connessione SMTP verificata
- `send_ok` -> invio email verificato
- nei runner reali (`test-pipeline`, `fetch-live-once`) il bootstrap notifier e l'invio sono ora isolati per canale: un canale guasto viene loggato e saltato, gli altri continuano quando possibile
- `Config validation failed`:
  verify required fields:
  - custom mode: `from_address`, `to_address`, `smtp_username`, `app_password`
  - profile mode: `sender_profile_id`, `to_address`

## 5) Relay SMTP gratuiti (riferimento operativo)

Per evitare dipendenza da Gmail personale, puoi usare un relay SMTP dedicato.
Indicazioni pratiche (verifica sempre limiti aggiornati sul sito ufficiale del provider):

- Brevo Free: 300 email/giorno, piano free senza scadenza.
- Mailjet Free: 200 email/giorno (fino a 6.000/mese).
- SMTP2GO Free: 1.000 email/mese, 200/giorno.
- Resend Free: 3.000 email/mese, 100/giorno.

Pattern consigliato per questo progetto:
1) crea account dedicato relay,
2) verifica dominio/sender,
3) genera credenziale SMTP/API key,
4) salva nel profilo mittente `sender_mode=profile`,
5) lascia all'utente finale solo `to_address`.

Esempi preset relay supportati senza host/porta manuali:
- `--profile-provider brevo`
- `--profile-provider mailjet`
- `--profile-provider smtp2go`
- `--profile-provider resend`
