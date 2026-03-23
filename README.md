# Affitto 2.1 stable

This folder is the clean stable baseline of the rental notifier project.

Current milestone:
- core project structure
- validated app configuration
- SQLite storage layer with 15-day retention support
- live logging pipeline (console + JSON file + callback stream)
- centralized SMTP preset registry (`gmail`, `outlook`, `brevo`, `mailjet`, `smtp2go`, `resend`, `custom`)
- explicit SMTP security modes (`starttls`, `ssl_tls`, `none` for custom/advanced cases)
- backend email status/preflight layer with persisted last-test tracking
- email sender profiles with single active sender editable from GUI
- pipeline simulation tests with cascade CLI overrides
- live fetch bridge (`fetch-live-once`) for Idealista/Immobiliare
- base GUI (`python run.py gui`) for end-user configuration and runtime control

## Quick start

1. Create and activate a virtual environment.
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Generate default runtime config:

```powershell
python run.py init-config
```

4. Validate config and initialize DB:

```powershell
python run.py doctor
```

Runtime files are created under `runtime/`.

Email note:
- `validate-config` remains a local model/config check.
- real email readiness is exposed separately by `python run.py email-status`.

## Prepare test environment (Windows)

From project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_test_env.ps1
```

This will:
- create `.venv`
- install Python dependencies
- install Playwright Chromium

To skip browser install:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_test_env.ps1 -SkipPlaywright
```

## Email test flow

1. Create config if needed:

```powershell
python run.py init-config
```

2. Edit `runtime/app_config.json` and configure `email`:
- set `enabled` to `true`
- choose provider: `gmail`, `outlook`, `brevo`, `mailjet`, `smtp2go`, `resend`, or `custom`
- choose sender mode:
  - `custom`: set `provider`, `from_address`, `smtp_username`, `app_password`
    - for `custom`, also set `smtp_host`, `smtp_port`, `security_mode`
  - `profile`: set `sender_mode=profile`, `sender_profile_id`, `to_address`

Legacy note:
- old `use_starttls` values are still accepted on load and normalized into `security_mode` on next save.

3. Validate config:

```powershell
python run.py validate-config
```

4. Test SMTP connection only (no send):

```powershell
python run.py test-email --dry-run
```

This now persists the last successful/failed connection test in runtime storage and updates `email-status`.

5. Send a real test message:

```powershell
python run.py test-email --email-subject "Affitto v2 test" --email-body "Email channel is working."
```

This persists a separate `send_ok` / send-error result for the current effective configuration.

Note:
- Gmail/Outlook usually require app passwords (with 2FA enabled).

Check real configuration state:

```powershell
python run.py email-status
```

Possible backend states:
- `not_configured`
- `incomplete_placeholder`
- `profile_missing`
- `profile_unreadable`
- `configured_unverified`
- `connection_ok`
- `send_ok`
- `error`

## Default sender profile (recommended)

Initialize sender profiles file:

```powershell
python run.py init-email-profiles
```

Create or update shared sender profile:

```powershell
python run.py upsert-email-profile --profile-id default_sender --profile-provider gmail --profile-from your.sender@gmail.com --profile-user your.sender@gmail.com --profile-password "your_app_password"
```

Supported profile providers:
- `gmail`
- `outlook`
- `brevo`
- `mailjet`
- `smtp2go`
- `resend`
- `custom`

For advanced custom SMTP security mode:

```powershell
python run.py upsert-email-profile --profile-id relay_sender --profile-provider custom --profile-from no-reply@example.com --profile-user smtp_user --profile-password "smtp_secret" --profile-host smtp.example.com --profile-port 465 --profile-security-mode ssl_tls
```

Then set in `runtime/app_config.json`:
- `email.sender_mode = "profile"`
- `email.sender_profile_id = "default_sender"`
- `email.to_address = "<recipient>"`

## Pipeline test (cascade options)

Dry-run pipeline:

```powershell
python run.py test-pipeline --notify-mode both --simulate-run-id run01 --simulate-count 5 --simulate-duplicate --simulate-blocked-agency
```

Real notifications:

```powershell
python run.py test-pipeline --notify-mode both --simulate-run-id run02 --simulate-count 2 --send-real-notifications
```

Email behavior:
- if multiple new listings are found in the same cycle, email is sent as a single digest message.
- Telegram remains one message per listing.

Detailed matrix:
- `docs/cli_test_matrix.md`

## Live fetch once

Run one real extraction cycle and pass results through DB + notifications pipeline:

```powershell
python run.py fetch-live-once --notify-mode config
```

Visible browser (debug):

```powershell
python run.py fetch-live-once --headed --max-per-site 20 --notify-mode config
```

Persistent profile (recommended, keeps cookies/session across runs):

```powershell
python run.py fetch-live-once --headed --notify-mode config --profile-dir .\runtime\playwright-profile
```

Browser channel override (to test local Chrome/Edge engine instead of bundled Chromium):

```powershell
python run.py fetch-live-once --headed --notify-mode config --browser-channel msedge
```

Site guard (recommended to reduce block probability):
- random jitter before each site request
- per-site outcome classification:
  - `healthy`
  - `suspect`
  - `degraded`
  - `blocked`
  - `cooling`
- per-site cooldown with exponential backoff only on real block/signals or repeated suspicious outcomes
- network timeout / parse drift are tracked separately from hard block
- optional browser-channel round-robin across runs
- persistent profile is isolated per channel (`playwright-profile/msedge`, `.../chrome`, `.../chromium`)

Example:

```powershell
python run.py fetch-live-once --headed --notify-mode both --send-real-notifications --browser-channel auto --channel-rotation-mode round_robin --guard-jitter-min-sec 2 --guard-jitter-max-sec 6 --guard-base-cooldown-min 30 --guard-max-cooldown-min 360
```

Guard state is stored in `runtime/site_guard_state.json` by default.

Guard state now keeps a few extra signals per site:
- last outcome tier / code / detail
- consecutive successes / failures / suspect / block streak
- last success and last recovery timestamps
- last valid channel used successfully
- last extraction quality snapshot:
  - cards count
  - fallback used
  - missing title / price / location / agency percentages

Useful recovery flags:

```powershell
python run.py fetch-live-once --guard-reset-state
python run.py fetch-live-once --guard-ignore-cooldown
```

With real notifications:

```powershell
python run.py fetch-live-once --notify-mode both --send-real-notifications
```

Captcha handling:
- uses `runtime.captcha_mode` from config (`skip_and_notify`, `pause_and_notify`, `stop_and_notify`)
- in headed mode + `pause_and_notify`, set manual wait with:

```powershell
python run.py fetch-live-once --headed --notify-mode config --captcha-wait-sec 180
```

Override captcha mode directly from CLI (without editing config):

```powershell
python run.py fetch-live-once --headed --notify-mode config --override-captcha-mode pause_and_notify --captcha-wait-sec 300
```

Debug artifacts on suspect/degraded/blocked transitions (HTML + screenshot + guard event JSON in `runtime/live_debug`):

```powershell
python run.py fetch-live-once --notify-mode none --max-per-site 1 --save-live-debug
```

Note:
- if a non-interactive hard block page is detected (for example "accesso bloccato"), manual wait is skipped automatically even with `pause_and_notify`.
- false positives on normal listing pages with hidden anti-bot scripts are filtered out; captcha flow now starts only with strong challenge signals.
- a `200 OK` with suspicious empty/shell content is no longer treated as a real success.
- empty legitimate result pages stay `healthy`; suspicious empties can trigger one conservative retry and, if repeated, a short cooldown.
- parse/schema failures are tracked as `degraded` and do not trigger hard anti-block cooldown on their own.
- successful fetches are now split more clearly:
  - `ok` for healthy extraction
  - `fallback_dominant` when cards are found only via HTML fallback
  - `partial_success_degraded` when cards exist but key fields are heavily missing
  - `parser_drift` when current output is technically reachable but clearly worse than the recent site snapshot
- parser drift diagnostics now track:
  - cards count
  - missing field percentages
  - fallback dominance
  - abrupt `0 card` after previously healthy runs
- parser-oriented JSON artifacts are saved in `runtime/live_debug` when drift is relevant enough to review.

## GUI base

Launch:

```powershell
python run.py gui
```

Included in base GUI:
- tabs:
  - `Configurazione`
  - `Runtime`
  - `Log`
  - `Aiuto`
- `Configurazione`:
  - search URLs input (Idealista + Immobiliare)
  - notify mode selection (`telegram` / `email` / `both`)
  - telegram token/chat_id
  - email setup:
    - provider preset (`gmail`, `outlook`, `brevo`, `mailjet`, `smtp2go`, `resend`, `custom`)
    - sender address
    - username / API key
    - password / secret
    - recipient
    - `custom` advanced fields when selected:
      - SMTP host
      - SMTP port
      - security mode (`STARTTLS` / `SSL/TLS (implicito)` / `Nessuna sicurezza`)
    - live backend email status
    - `Test connessione`, `Test invio`
  - single `Salva Configurazione`
  - runtime controls: `Run once`, `Start cycle`, `Stop`, `Reset site guard`, `Reset DB annunci`
  - optional Windows autostart toggle
- `Runtime`:
  - cycle minutes, max listings per site (capped at 50), retention days
  - extraction fields toggles (price / zone / agency)
  - agency blacklist by name (auto-converted to regex), in forma piu compatta
- `Log`:
  - live logs with level filter (`INFO` / `WARNING` / `ERROR`) + `Pulisci Log`
- `Aiuto`:
  - quick guide with ordered flow:
    - configura
    - salva
    - testa
    - `Run once`
    - controlla i log
    - poi attiva il ciclo automatico

Security:
- email profile secrets (`smtp_username`, `app_password`) are saved encrypted locally via Windows DPAPI when profiles are written.
- config/profile legacy field `use_starttls` is still read, but new saves use `security_mode`.
- DPAPI/profile decryption failures are surfaced as profile-readability issues before SMTP tests, not as generic SMTP login errors.
- GUI edits the active sender profile and keeps secrets out of `runtime/app_config.json`.
- when `custom` is selected, advanced fields are shown only in that context; preset providers keep host/port/security hidden.
- if a secret already exists and the password field is left unchanged/blank, GUI save preserves the stored secret.

Current GUI limits:
- email tests from GUI require `notify mode = email` or `both`.
- with `notify mode = telegram`, the email section stays visible but is locked/read-only.

Runtime hardening:
- notifier bootstrap is isolated per channel during `test-pipeline` / `fetch-live-once`.
- if email bootstrap or send fails, scraping/dedup/telegram continue when possible.
- if telegram bootstrap or send fails, scraping/dedup/email continue when possible.
- live pipeline logs now distinguish degraded bootstrap vs per-channel send failure.
- `fetch-live-once` keeps one-shot behavior and logs a clean stop if fetch fails before pipeline.

## Windows packaging

First stable bundle strategy:
- PyInstaller
- GUI bundle: `dist\\affitto_gui\\affitto_gui.exe`
- companion CLI: `dist\\affitto_gui\\affitto_cli.exe`
- build script: `scripts\\build_windows_bundle.ps1`

Bundle runtime paths:
- source mode keeps using `runtime`
- bundled exe uses `%LOCALAPPDATA%\\AffittoV2\\runtime` by default
- optional override: env `AFFITTO_V2_RUNTIME_DIR`

Primo avvio bundle:
1. avvia `dist\\affitto_gui\\affitto_gui.exe`
2. controlla che vengano creati:
   - `app_config.json`
   - `logs\\app.log`
3. configura canali e URL
4. salva
5. usa `Run Once`
6. se qualcosa fallisce, guarda prima `app.log`

Verifica reale eseguita in questa fase:
- GUI bundle avviabile
- creazione runtime/config/log su path bundle-aware
- `affitto_cli.exe validate-config` riuscito su runtime bundle
- `affitto_cli.exe test-email --dry-run` riuscito su copia del runtime corrente
- `fetch-live-once` bundle verificato su companion CLI con gli stessi flag principali del `Run Once` GUI:
  - start reale confermato
  - uso `msedge` confermato in `auto + round_robin`
  - terminazione one-shot pulita confermata in caso di challenge/captcha

Verifica solo parziale:
- salvataggio interattivo completo dalla GUI bundle:
  - la finestra si apre correttamente
  - l'automazione nativa dei click su Tkinter nel setup corrente e risultata instabile
  - il wiring e i path sottostanti sono comunque stati verificati via companion CLI bundle

Build:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-packaging.txt
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_bundle.ps1
```

More details:
- `docs/windows_packaging.md`

Troubleshooting rapido:
- bundle aperto ma non trovi config/log:
  - controlla `%LOCALAPPDATA%\\AffittoV2\\runtime`
  - oppure usa `AFFITTO_V2_RUNTIME_DIR` per forzare un runtime isolato
- `Run Once` da bundle fallisce subito:
  - controlla `app.log`
  - verifica browser disponibili (`msedge` / `chrome`) e stato del site guard
  - se vedi challenge/captcha, il comportamento atteso e` stop prudente con log chiaro, non retry aggressivo
- email da bundle:
  - prima verifica `email-status`
  - poi usa `test-email --dry-run`
  - solo dopo `Test invio` o run reali

## Recent updates (2026-03-11)

- URL sanitation:
  - GUI normalizes URL input (adds `https://` when missing).
  - removes tracking params (`utm_*`, `gclid`, `fbclid`, `msclkid`, `dtcookie`) before save.
- Notification mode UX:
  - GUI now locks channels coherently:
    - `telegram` -> email section locked, tests disabled
    - `email` -> telegram section locked
    - `both` -> both sections active
- Layout cleanup:
  - removed the duplicate `Salva` button from the email section
  - kept a single `Salva Configurazione`
  - split the GUI into tabs for configuration, runtime, logs, help
  - moved run/save/autostart actions back into `Configurazione`
  - reduced vertical footprint of the blacklist and compacted `Runtime`
- Guard behavior:
  - `Run once` from GUI now ignores cooldown only for that run (`--guard-ignore-cooldown`).
  - automatic cycle still respects cooldown.
  - channel rotation now prefers `msedge/chrome`, `chromium` fallback.
  - in headed + `skip_and_notify`, verification/captcha gets a short auto-wait before declaring blocked.
- Scraping quality:
  - Immobiliare scroll avoids raw mouse wheel on page (prevents accidental map zoom interactions).
  - Idealista selectors refined (title/agency/location extraction) with location fallback from title.
- Email digest format:
  - no placeholder `-` lines for missing fields.
  - includes `Sito` line per item.
  - `Zona` shown only if not already in title.
  - adds digest timestamp + per-site summary.
- Config secrecy hardening:
  - with `email.sender_mode = profile`, custom SMTP fields in `app_config.json` are cleared on validate/save.

## Recent updates (2026-03-21)

- SMTP preset/model patch:
  - added centralized preset registry for `gmail`, `outlook`, `brevo`, `mailjet`, `smtp2go`, `resend`, `custom`
  - replaced implicit transport handling with explicit `security_mode`
  - supported modes:
    - `starttls`
    - `ssl_tls`
    - `none` (custom only)
  - kept backward compatibility with legacy `use_starttls` config/profile files
- Email status/preflight patch:
  - added `email_setup.py`
  - added `email-status` CLI command
  - persisted last email test result in runtime DB (`app_kv`)
  - distinguished:
    - not configured
    - placeholder/incomplete
    - missing profile
    - unreadable profile / DPAPI decrypt failure
    - configured but not verified
    - connection OK
    - send OK
    - error
- Simple GUI email patch:
  - GUI now edits the active sender profile instead of recipient-only mode
  - provider preset, sender, username/API key, password/secret, recipient
  - status is read from backend preflight layer
  - `Test connessione` / `Test invio` reuse existing `test-email`
- Advanced/custom SMTP patch:
  - `custom` now exposes host, port and security mode directly in GUI
  - advanced fields are shown only for `custom`
  - stored custom setup is reloaded coherently after save/reopen
  - blank password field preserves the existing stored secret
  - GUI error messages are more explicit for auth / TLS / timeout failures
- Runtime hardening patch:
  - notifier bootstrap degraded per channel no longer aborts the whole pipeline
  - email/telegram send failures are logged and isolated, pipeline continues
  - pipeline summary now reports notification failures and degraded channels
  - `fetch-live-once` logs one-shot start/fetch/pipeline/finish more clearly
  - `Aiuto` tab rewritten with a compact operational flow for first setup
- First Windows packaging patch:
  - added bundle-aware runtime path handling (`source` vs `bundle`)
  - GUI bundle now uses companion `affitto_cli.exe` for internal CLI subprocesses
  - added PyInstaller entrypoints/spec files and repeatable build script
  - verified bundle bootstrap + runtime/config/log creation on Windows

## Recent updates (2026-03-22)

- Anti-block adaptation / pragmatic autohealing:
  - live fetch now distinguishes `healthy`, `suspect`, `degraded`, `blocked`, `cooling`
  - concrete outcomes now separate:
    - `ok`
    - `empty_legit`
    - `empty_suspicious`
    - `challenge_visible`
    - `hard_block`
    - `timeout_network`
    - `network_issue`
    - `parse_issue`
    - `cooldown_active`
  - first retry is now limited to explicitly retryable transient outcomes, not every generic empty page
  - `200 OK` pages with suspicious shell/challenge content are no longer counted as success
  - site guard state now stores streaks, last outcome, last success/recovery and last valid channel
  - `runtime/live_debug` can now contain guard event JSON artifacts on degrade/block/recovery transitions
  - `fetch-live-once` remains one-shot: no extra loops, no aggressive channel hopping inside the same run
- Drift detection minima + parser diagnostics:
  - each live fetch now measures extraction quality:
    - cards count
    - missing title / price / location / agency percentages
    - fallback used or not
  - conservative drift detection now flags:
    - zero cards after previously healthy runs
    - fallback becoming dominant
    - strong spikes in missing key fields
    - partial success with poor extraction quality
  - parser degradation is kept distinct from anti-bot:
    - parser drift does not become `blocked` by itself
    - no extra retries were added
  - `runtime/live_debug` now also stores parser diagnostic JSON artifacts for faster review
- Consolidamento finale bundle/docs:
  - bundle rigenerato dopo il ritocco finale della tab `Aiuto`
  - verificati realmente:
    - bootstrap GUI bundle
    - runtime/config/log bundle-aware
    - `validate-config` bundle
    - `test-email --dry-run` bundle
    - `fetch-live-once` bundle con i flag principali del `Run Once` GUI
  - salvataggio interattivo completo dalla GUI bundle: verificato solo parzialmente nel setup corrente
  - README / packaging / troubleshooting riallineati allo stato reale della fase
