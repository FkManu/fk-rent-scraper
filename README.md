# Scraper Affitto 2.3_test

La cartella `2.3_test` e la nuova root di lavoro aperta come copia completa e separata di `2.2_test`.

## Punto di partenza
Al momento del taglio:
- il codice prodotto e inizialmente allineato alla baseline `2.2.2 refactorizzata`
- `2.2_test` resta la linea di riferimento appena congelata come `2.2 stable`
- `2.3_test` serve per aprire la prossima iterazione senza contaminare l'ambiente `2.2`

## Cosa cambia davvero al taglio
- ambiente locale separato
- documentazione viva riallineata alla nuova linea
- archivio interno del contesto `2.2`

## Cosa non cambia ancora
- nessuna modifica intenzionale al codice prodotto al momento della creazione della root
- backend operativo ancora `camoufox`
- tooling, packaging e test ereditati dalla baseline `2.2`

## Read this first
1. `docs/context/README.md`
2. `docs/context/HANDOFF.md`
3. `docs/context/NEXT_STEPS.md`
4. `docs/context/codex/OUTPUT_CURRENT.md`
5. `docs/repo_summary.md`
6. `docs/risk_scoring_e_griglia_segnali_antibot.md`

## Regola pratica
Questa root non nasce per rifare da zero la strategia live.

Ogni patch in `2.3_test` dovrebbe:
- preservare la baseline `2.2`
- cambiare un solo asse alla volta
- restare misurabile su run comparabili

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

I file runtime locali vengono creati sotto `runtime/` e non fanno parte del perimetro Git pulito.

## Browser default
Il backend operativo ereditato dalla baseline resta `camoufox`.

Note operative:
- root profili persistenti di default: `runtime/camoufox-profile`
- la CLI live accetta `--browser-channel auto|camoufox`
- il launch predefinito usa `locale=it-IT`, `timezone=Europe/Rome` e `screen=1920x1080`
- `Milestone 3 / Real Browser Assisted` non e una direzione attiva della linea

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

## Build bundle `2.3_test`

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-packaging.txt
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_bundle.ps1
```

Prima dist della linea `2.3_test`:
- `dist/affitto_2_3_test_bundle.zip`
