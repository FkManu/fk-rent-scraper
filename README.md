# Affitto 2.2.1 Stable

La cartella resta `2.2_test`, ma a questo punto va trattata come root di lavoro della release `2.2.1 stable`.

Non e la baseline storica `2.1_stable`.
`2.1_stable` resta la baseline di provenienza; `2.2_test` contiene la linea che e stata promossa a `2.2.1 stable`.

Questa linea esiste per consolidare:
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
- fix del `2026-03-27` sul conteggio `detail_touch_count` di `idealista`, che evitava cooldown artificiali da errore interno
- hardening del `2026-03-27` sulla continuita di profilo:
  - `hard_block` => rotazione profilo persistente su `immobiliare` e `idealista`
  - rotazione preventiva a `24h` attiva solo su `immobiliare`
- hardening del `2026-03-27` sulla profile identity:
  - persona Camoufox persistente per `site/channel/profile_generation`
  - stessa generazione => stessi parametri di launch principali
- hardening del `2026-03-28` su osservabilita:
  - log dettagliati su render context init, pacing Gamma, bootstrap static resources e chiusura sessione
- GUI aggiornata con `Modalita debugger` per salvare artifact in `runtime/debug` o `./debug` accanto alla dist

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
Il backend live predefinito della linea `2.2.1 stable` e `camoufox`.

Note operative:
- root profili persistenti di default: `runtime/camoufox-profile`
- la CLI live accetta `--browser-channel auto|camoufox`
- il launch predefinito usa fingerprint Windows umanizzato con `locale=it-IT`, `timezone=Europe/Rome` e `screen=1920x1080`
- il backend reale del ramo resta uno solo: `camoufox`
- i profili persistenti sono ora versionati per `site/channel/profile_generation` quando il guard decide di ruotare identita
- `Milestone 3 / Real Browser Assisted` non e piu una direzione attiva del ramo
- il prossimo hardening previsto non e multi-browser ma:
  - validazione soak della nuova identity policy
  - refactor prudente di `live_fetch.py`

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

## Windows stable bundle
Build del bundle:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-packaging.txt
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_bundle.ps1
```

Il bundle stable mantiene:
- GUI -> default `camoufox`
- CLI companion -> default `camoufox`
- runtime bundle-aware -> `%LOCALAPPDATA%\AffittoV2\runtime`
- zip di release corrente -> `dist/affitto_2_2_1_stable_bundle.zip`

## Compatibilita
I comandi applicativi ereditati da `2.1_stable` restano validi.
Quello che cambia qui non e il wiring base della CLI, ma la strategia live e il lifecycle documentati in `docs/context/`.
