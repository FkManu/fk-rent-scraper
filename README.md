# Affitto 2.2 Preview

La cartella resta `2.2_test`, ma ormai va trattata come preview branch della prossima linea live.

Non e la baseline shipping.
La baseline shipping resta `2.1_stable`.

Questa preview esiste per validare:
- `camoufox` come backend operativo del ramo
- continuita di sessione per sito
- servizio continuo `fetch-live-service`
- riduzione del rumore interazionale
- precisione crescente del filtro `private_only`

## Stato attuale
- backend predefinito: `camoufox`
- GUI e CLI allineate allo stesso backend
- servizio continuo reale sopra il one-shot
- soak VM del `2026-03-26` stabile
- fix recente sulla memoria negativa `private_only` per i professionali scoperti da detail-check

## Read this first
1. `docs/context/README.md`
2. `docs/context/HANDOFF.md`
3. `docs/context/NEXT_STEPS.md`
4. `docs/context/codex/OUTPUT_CURRENT.md`
5. `docs/risk_scoring_e_griglia_segnali_antibot.md`

## Regola pratica
Non usare questa root come sandbox generico.

Ogni patch qui dovrebbe fare almeno una di queste cose:
- ridurre rumore
- aumentare continuita
- migliorare in modo misurabile `private_only`

## Quick start
1. Crea e attiva una virtualenv.
2. Installa le dipendenze:

```powershell
pip install -r requirements.txt
```

3. Genera la config di runtime:

```powershell
python run.py init-config
```

4. Valida config e DB:

```powershell
python run.py doctor
```

I file runtime locali vengono creati sotto `runtime/` e non fanno parte della repo.

## Browser default
Il backend live predefinito della preview e `camoufox`.

Note operative:
- root profili persistenti di default: `runtime/camoufox-profile`
- gli alias `auto|firefox|chromium|chrome|msedge` restano accettati solo per compatibilita CLI
- il launch predefinito usa fingerprint Windows umanizzato con `locale=it-IT`, `timezone=Europe/Rome` e `screen=1920x1080`

## Continuous live mode
Comando principale di soak:

```powershell
python run.py fetch-live-service
```

Note operative:
- la cadenza viene da `runtime.cycle_minutes`
- la soglia hard di overrun per ciclo e `10` minuti di default
- non e consentito overlap tra cicli
- `--max-cycles N` e utile per soak bounded

## Windows setup
Da root progetto:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_test_env.ps1
```

Per saltare il fetch browser:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_test_env.ps1 -SkipCamoufoxFetch
```

Lo script standard esegue `python -m camoufox fetch`.

## Windows preview bundle
Build del bundle:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-packaging.txt
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_bundle.ps1
```

Il bundle preview mantiene:
- GUI -> default `camoufox`
- CLI companion -> default `camoufox`
- runtime bundle-aware -> `%LOCALAPPDATA%\AffittoV2\runtime`

## Compatibilita
I comandi applicativi ereditati da `2.1_stable` restano validi.
Quello che cambia qui non e il wiring base della CLI, ma la strategia live e il lifecycle documentati in `docs/context/`.
