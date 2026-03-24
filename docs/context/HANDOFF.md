# HANDOFF.md

## Stato attuale
- `2.1_stable` e la nuova baseline privata viva del progetto.
- questa root contiene solo codice prodotto, packaging/script ripetibili, docs utili e contesto essenziale
- runtime, build, dist, cache, transcript grezzi e stato Codex transitorio sono stati esclusi dal taglio
- la patch `Observable autohealing / browser affinity per sito` e stata verificata in pratica su VM Windows con log di alcune ore:
  - nessun `hard_block` osservato
  - `idealista` tende a stabilizzarsi su `msedge`
  - `immobiliare` tende a stabilizzarsi su `chrome`
- il problema dominante non e piu il blocco browser/siteguard ma la precisione del fetch:
  - `idealista` resta spesso `partial_success_degraded`
  - i filtri URL "solo privati" possono comunque far emergere annunci agenzia nei risultati suggeriti dal sito
- follow-up ormai gia integrati nella baseline locale:
  - modalita `annunci privati` in GUI/runtime con filtro locale sugli annunci con agenzia rilevata
  - hardening della log rotation Windows per evitare rumore e contention su `app.log`
  - review Idealista del 2026-03-24 con due fix aggiuntivi:
    - auto-wait anche sul ramo `interstitial_datadome` quando la verifica si auto-risolve in headed mode
    - lettura del nome agenzia dal logo `img[alt]` dentro i link `/pro/`
  - refinement Idealista del 2026-03-24 sera:
    - secondo controllo pagina dettaglio in `private_only` per gli annunci ancora senza segnale agenzia
    - classificazione `Privato` / `Professionista` letta dal blocco "Persona che pubblica l'annuncio"
    - stop prudente del secondo controllo se durante i detail-check emerge una challenge
  - refinement successivo sui detail-check Idealista:
    - i professionali vengono riconosciuti anche dal link profilo `/pro/` nel sidebar/nav della pagina dettaglio
    - il pacing del secondo controllo e piu conservativo, con delay piu umano e pause ogni pochi annunci
    - gli `unresolved` vengono loggati con `ad_id` e `url` per review piu rapida

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
- repo GitHub privata gia creata e pushata da questa root (`FkManu/fk-rent-scraper`)
- baseline VM attuale confermata come praticabile con Edge+Chrome installati
- review log/DOM Idealista 2026-03-24:
  - nei log si vedono run `blocked/interstitial_datadome` che poi, pochi secondi dopo, diventano `partial_success_degraded` sulla stessa ricerca
  - il falso skip nasceva dal fatto che il ramo `interstitial_datadome` veniva chiuso subito senza finestra di assestamento
  - sul DOM live Idealista molte card agenzia espongono il brand solo come `img[alt]` dentro `a[href*="/pro/"]`, quindi i vecchi selettori intercettavano quasi solo i casi con alt contenente `Agenzia` o `Immobiliare`
  - dai log piu recenti il ramo anti-bot appare stabile (`idealista` torna `healthy`), ma restano molti annunci `private_only_unknown`
  - ispezionando il DOM live delle pagine dettaglio Idealista, il publisher type e esposto chiaramente come `Privato` o `Professionista`
  - due annunci sfuggiti (`35159080`, `35009314`) risultano `Professionista` gia dal DOM dettaglio e hanno anche link `/pro/`, quindi il problema non era il sito ma il nostro segnale detail ancora troppo debole
- prossima chiusura operativa:
  - validare su VM anche il nuovo secondo controllo dettaglio Idealista con nuovi log reali
  - misurare se `idealista` aumenta gli skip agenzia, riduce `allowed_without_agency_signal` e non peggiora il profilo anti-bot durante le aperture dettaglio
  - fare pulizia finale pre-push della root `2.1_stable` ed eseguire l'update sulla repo GitHub privata
