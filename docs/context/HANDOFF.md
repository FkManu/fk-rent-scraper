# HANDOFF.md

## Stato attuale
- `2.1_stable` e la baseline privata viva del progetto.
- questa root contiene solo codice prodotto, packaging/script ripetibili, docs utili e contesto essenziale
- runtime, build, dist, cache, transcript grezzi e stato Codex transitorio sono stati esclusi dal taglio
- dopo i test VM del 2026-03-25 sono stati assorbiti tre intoppi prioritari:
  - la dist Windows non partiva in GUI per assenza dei runtime Tcl/Tk nel bundle; packaging corretto e nuova dist ricompilata
  - il site guard poteva entrare in cooldown troppo cieco dopo `interstitial_datadome`; ora il clear della challenge e piu severo e durante il cooldown e prevista una probe controllata
  - su bundle Windows `idealista` poteva cadere da `msedge` a `chrome` e peggiorare il profilo DataDome; ora vengono preferiti i browser reali installati e il bundle auto-mode non forza piu `chromium`
- lo stato live attuale e questo:
  - `immobiliare` resta il sito piu stabile e continua a lavorare su `chrome`
  - `idealista` preferisce `msedge` installato e dopo reset del site guard ha ripreso il ciclo corretto sulla VM
  - sui blocked outcome piu sospetti e stato aggiunto un retry immediato con browser alternativo, senza trasformarlo in loop aggressivo
  - la modalita `annunci privati` resta attiva e ora riapre meno dettagli grazie al riuso del DB locale
- il problema dominante non e un hard block generalizzato, ma la tenuta di `idealista` nei run lunghi e la riduzione delle interazioni sospette:
  - `idealista` puo ancora arrivare a `interstitial_datadome` o `partial_success_degraded`
  - Playwright con browser reale installato migliora il comportamento, ma il browser puo risultare comunque "gestito" lato sito
  - il secondo controllo `private_only` va tenuto il piu parsimonioso possibile
- follow-up ormai gia integrati nella baseline locale:
  - modalita `annunci privati` in GUI/runtime con filtro locale sugli annunci con agenzia rilevata
  - hardening della log rotation Windows per evitare rumore e contention su `app.log`
  - attesa piu prudente sul ramo `interstitial_datadome` quando la verifica si auto-risolve in headed mode
  - lettura del nome agenzia dal logo `img[alt]` dentro i link `/pro/`
  - secondo controllo pagina dettaglio in `private_only` solo per gli annunci Idealista senza segnale agenzia in card
  - classificazione `Privato` / `Professionista` letta dal blocco "Persona che pubblica l'annuncio" e dal link profilo `/pro/`
  - pacing del secondo controllo reso piu conservativo, con log dedicato agli `unresolved`
  - riuso del DB per evitare di riaprire annunci gia noti durante il filtro `private_only`

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
- review log/DOM aggiornata al 2026-03-25:
  - il loop percepito del site guard era in realta un cooldown ripetuto dopo `interstitial_datadome`, non un loop del fetcher
  - il reset manuale sbloccava il ciclo perche puliva strikes/cooldown e permetteva a `idealista` di tornare su `msedge`
  - i log piu recenti mostrano che `immobiliare` continua a girare anche quando `idealista` si degrada
  - la strategia `private_only` e stata resa piu prudente: se l'annuncio e gia nel DB non viene riaperto solo per riclassificarlo
- prossima chiusura operativa:
  - validare su VM la nuova dist per alcune ore, controllando che non ricompaiano lunghe sequenze di solo `cooldown_active`
  - misurare se dal secondo ciclo in poi calano davvero i `detail verification start` su `idealista` grazie alla cache DB
  - decidere se il tema browser "gestito" va affrontato come patch a parte o accettato come limite pratico dell'automazione corrente
  - fare pulizia finale pre-push della root `2.1_stable` ed eseguire l'update sulla repo GitHub privata
