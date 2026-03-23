# HANDOFF.md

## Stato attuale
- `2.1_stable` e la nuova baseline privata viva del progetto.
- questa root contiene solo codice prodotto, packaging/script ripetibili, docs utili e contesto essenziale
- runtime, build, dist, cache, transcript grezzi e stato Codex transitorio sono stati esclusi dal taglio

## Cosa c'e dentro
- scraping live `fetch-live-once` per Idealista e Immobiliare
- SQLite con deduplica e retention
- notifiche Telegram ed Email
- sender profile cifrati con DPAPI
- GUI con setup email preset/custom, test connessione/invio, runtime controls e help
- packaging Windows con `affitto_gui.exe` + `affitto_cli.exe`
- hardening runtime per fault isolation notifiche
- anti-block pragmatico e drift detection minima con artifact diagnostici

## Decisioni confermate
- `v1_stable` resta archivio storico, non base attiva
- il workflow quotidiano riparte da questa root, non da `v2_test`
- i file Codex da tenere qui sono solo quelli utili in forma slim
- `chat_openclaw.md` e `chat_codex.md` non sono stati portati nella nuova base

## Percorsi utili
- da sorgente:
  - config, DB e log stanno in `runtime/`
- da bundle:
  - default `%LOCALAPPDATA%\\AffittoV2\\runtime`
  - override `AFFITTO_V2_RUNTIME_DIR`

## File da leggere per ripartire
- `README.md`
- `docs/context/NEXT_STEPS.md`
- `docs/context/2_1_STABLE_MANIFEST.md`
- `docs/context/codex/REVIEW_2_1_STABLE.md`

## Prossimo passo sensato
- usare questa root come nuovo punto di partenza reale
- ricreare ambiente virtuale, runtime e bundle localmente quando servono
- aprire nuove patch solo dentro `2.1_stable`
- preparare una repo GitHub privata partendo da questa root pulita
- fare un primo deploy del bundle `.exe` in una VM Windows per simulare il comportamento su un PC nuovo
