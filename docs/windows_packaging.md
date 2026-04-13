# Windows packaging - `2.3_stable`

## Strategia scelta

Packaging conservativo con **PyInstaller** e output in `onedir`:

- `affitto_gui.exe`
  - entrypoint GUI
  - build `windowed`
- `affitto_cli.exe`
  - companion console exe
  - usato dalla GUI bundle per:
    - `test-email`
    - `fetch-live-once`
    - altri comandi CLI interni

Motivo della scelta:
- in bundle GUI non conviene affidarsi a `python run.py ...`
- separare GUI e CLI evita problemi con stdout/stderr e subprocess in modalita `windowed`
- il bundle resta leggibile e debuggabile

## Path runtime

### Da sorgente

Percorso invariato:

- `runtime/app_config.json`
- `runtime/email_profiles.json`
- `runtime/data.db`
- `runtime/logs/app.log`

### Da bundle `.exe`

Di default:

- `%LOCALAPPDATA%\\AffittoV2\\runtime\\`

Override opzionale:

- env `AFFITTO_V2_RUNTIME_DIR`

Questo vale per:
- `app_config.json`
- `email_profiles.json`
- DB SQLite
- log
- `camoufox-profile`
- `live_debug`
- `site_guard_state.json`

## Build

Prerequisiti:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-packaging.txt
```

Build bundle:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_bundle.ps1
```

Output atteso:

- `dist\affitto_gui\affitto_gui.exe`
- `dist\affitto_gui\affitto_cli.exe`
- `dist\affitto_2_3_stable_bundle.zip`

Nota stable:
- la dist resta un artefatto locale di build e non va committata in repo
- lo zip stable serve come consegna locale o asset release, non come contenuto Git

I file PyInstaller usati sono:

- `packaging\affitto_gui.spec`
- `packaging\affitto_cli.spec`

## Smoke test minimo

### Da sorgente

```powershell
python run.py gui
```

### Da bundle

1. Avvia `dist\affitto_gui\affitto_gui.exe`
2. Verifica che la GUI si apra senza crash immediato
3. Verifica che vengano creati config/log/runtime
4. Verifica che `affitto_cli.exe validate-config` funzioni sul config creato

Esempio con runtime isolato:

```powershell
$env:AFFITTO_V2_RUNTIME_DIR = "$env:TEMP\\affitto-bundle-runtime"
.\dist\affitto_gui\affitto_gui.exe
.\dist\affitto_gui\affitto_cli.exe validate-config --config "$env:AFFITTO_V2_RUNTIME_DIR\\app_config.json"
```

Per distribuire la prima build `2.3_stable`:

```powershell
Expand-Archive -Path .\dist\affitto_2_3_stable_bundle.zip -DestinationPath "$env:TEMP\\affitto-2.3-stable"
```

## Stato verificato nella fase corrente

Verificato realmente:
- bootstrap GUI bundle
- creazione runtime bundle-aware
- creazione `app_config.json`
- creazione `logs\\app.log`
- `affitto_cli.exe validate-config`
- `affitto_cli.exe test-email --dry-run` su copia del runtime corrente
- `affitto_cli.exe fetch-live-once` con i flag principali del `Run Once` GUI:
  - start reale confermato
  - uso backend `camoufox` confermato
  - stop one-shot pulito confermato in caso di challenge

Verificato solo parzialmente:
- salvataggio interattivo completo dalla GUI bundle
- click end-to-end su `Run Once` e `Test connessione` dalla GUI bundle

Motivo del limite:
- nel setup corrente non c'e` una libreria di automazione robusta per controlli nativi Tkinter
- l'automazione tastiera/mouse grezza e` risultata instabile
- il wiring bundle->CLI e i path reali sono comunque stati verificati con il companion CLI

## Troubleshooting rapido

- Non trovi runtime/config/log del bundle:
  - controlla `%LOCALAPPDATA%\\AffittoV2\\runtime`
  - oppure forza un path con `AFFITTO_V2_RUNTIME_DIR`

- `Run Once` da bundle fallisce subito:
  - apri `app.log`
  - controlla se il problema e` fetch Camoufox, challenge/captcha o cooldown guard
  - il comportamento atteso e` stop prudente con log chiaro, non retry aggressivo

- `test-email --dry-run` fallisce:
  - verifica prima `email-status`
  - ricontrolla provider / sender profile / credenziali
  - poi prova di nuovo dal bundle CLI o dalla GUI

## Limiti attuali del primo rilascio

- nessun installer Windows
- nessuna icona/branding finale
- companion `affitto_cli.exe` richiesto accanto alla GUI bundle
- il browser Camoufox non viene impacchettato dentro la dist come binario dedicato:
  - va reso disponibile con `python -m camoufox fetch` nel setup sorgente o nel provisioning della macchina
  - la GUI bundle e il companion CLI usano `camoufox` come backend predefinito
- smoke test GUI verificato bene su bootstrap/path/runtime; il click interattivo end-to-end del flusso utente dal bundle resta solo parzialmente verificato nel setup corrente
