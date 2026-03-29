# HANDOFF.md

## Stato attuale
- la cartella resta `2.2_test`, ma oggi rappresenta la linea `2.2 stable`.
- `2.1_stable` resta la baseline storica di provenienza.
- il ramo non e piu solo una copia con docs nuove:
  - il motore live predefinito e ora `camoufox`
  - GUI e CLI sono riallineate al default `camoufox`
  - il servizio continuo `fetch-live-service` e il percorso operativo reale del ramo
- la differenza rispetto alla baseline shipping e ora concreta:
  - continuita di sessione per sito
  - profili persistenti isolati per sito
  - risk budget e stato di run
  - orchestrazione 24/7 con runtime condiviso

## Decisione di progetto
- `2.2.2 refactorizzata` e la release corrente della nuova linea
- `2.1_stable` resta il riferimento storico e comparativo
- `2.2_test` resta la root tecnica in cui vivono sessione lunga, lifecycle continuo e precisione live
- il file `docs/risk_scoring_e_griglia_segnali_antibot.md` resta la pietra miliare interna della nuova linea
- `Milestone 3 / Real Browser Assisted` va considerata dismessa:
  - era un'ipotesi di workaround
  - non fa piu parte della strategia reale del ramo

## Cosa e gia consolidato
- telemetria minima, `RiskBudget`, `RunRiskState` e stop trigger leggibili nel fetch live
- profili persistenti isolati per `site/channel`
- ownership esplicita della sessione con chiave `site|channel|profile`
- generation esplicita del profilo persistente quando il guard decide di cambiare identita
- pool di sessioni isolate per owner con riuso same-site e pruning dello churn same-site
- servizio continuo sopra il one-shot:
  - cadenza da `runtime.cycle_minutes`
  - no overlap
  - `LiveServiceState`
  - runtime disposition minima `keep / recycle_site_slot / recycle_runtime / stop_service`
- GUI allineata al servizio reale:
  - `Run Once` -> `fetch-live-once`
  - periodico -> `fetch-live-service`
- render context globale deterministico:
  - `navigator.deviceMemory=16`
  - `navigator.hardwareConcurrency=8`
  - WebGL vendor/renderer stabilizzati
  - `Canvas.toDataURL()` con `static noise` deterministico
- pacing adattivo sulle interazioni chiave:
  - distribuzione Gamma
  - applicazione prima di `goto`, `click` e chiusura sessione
- bootstrap tecnico delle risorse statiche comuni:
  - warm-up del `BrowserContext` su endpoint infrastrutturali `gstatic/google/cloudflare`
  - pagina temporanea dedicata chiusa prima dell'uso operativo della sessione
- refactor strutturale completato su `live_fetch.py`:
  - `browser/session_policy.py` governa user-agent, hardware mimetics, pacing e bootstrap
  - `browser/bootstrap.py` concentra pacing Gamma e warm-up tecnico
  - `browser/factory.py` concentra close/prune/destroy dei profili persistenti
  - `guard/state_machine.py` traduce in codice la state machine tabellare del run
  - `sites/idealista.py` e `sites/immobiliare.py` concentrano selettori e costanti per-sito
  - `live_fetch.py` resta l'orchestratore del ciclo, non piu il contenitore di tutte le responsabilita

## Pivot backend
- backend browser operativo del ramo: `camoufox`
- root profili persistenti predefinita: `runtime/camoufox-profile`
- CLI live ridotta a `--browser-channel auto|camoufox`
- launch predefinito Camoufox:
  - `humanize=True`
  - `locale=it-IT`
  - `timezone=Europe/Rome`
  - `screen=1920x1080`
- setup Windows aggiornato per eseguire `python -m camoufox fetch`
- launch path ora osservabile a `INFO`:
  - `Launch path acquired fresh identity`
  - `Launch path prepared page`
  - `Launch path reused mature identity`

## Stato operativo visto in VM il 2026-03-26
- file di riferimento: `docs/tmp_logs.md`
- soak test lungo del servizio continuo osservato da `11:59:51` a `16:55:19`
- cicli completati: `60`
- esiti osservati:
  - `healthy`: `240`
  - `degraded`: `0`
  - `blocked`: `0`
  - `cooling`: `0`
  - `assist_required`: `0`
  - `ERROR`: `0`
  - `Traceback`: `0`
- il servizio resta `stable` per tutta la finestra osservata
- `runtime disposition`:
  - `keep`: `56`
  - `recycle_site_slot`: `4`
  - nessun `recycle_runtime`
  - nessun `stop_service`

## Fix recenti gia chiusi
- il collo di bottiglia piu evidente emerso dai log era il riuso nullo della memoria `private_only` per gli annunci professionali Idealista trovati dal detail-check
- il ramo salva ora questa evidenza in una cache negativa dedicata nel DB
- nel review passata sulle ultime ore e emerso anche un bug interno, non un crash motore:
  - `_verify_idealista_private_only_candidates()` poteva restituire `None`
  - il chiamante aggregava `detail_touch_count` come intero
  - il risultato era `unexpected_error` con cooldown artificiale su `idealista`
- il fix del `2026-03-27` chiude questo punto:
  - early return a `0`
  - coercizione osservabile del `detail_touch_count` nel chiamante
  - test mirati aggiunti
- review log successiva del `2026-03-27` su `immobiliare`:
  - il block osservato non era un falso positivo del guard
  - challenge reale subito dopo `goto`
  - `session_age_sec` oltre `44-45h` al momento del block
  - il recycle del solo slot browser non bastava, perche la identity persistente restava la stessa
- fix successivo del `2026-03-27` sulla profile identity:
- `hard_block` => rotazione profilo persistente per `immobiliare`
- `hard_block` => rotazione profilo persistente anche per `idealista`, ma solo in modo reattivo
- il cooldown di un `hard_block` resta associato alla generazione che ha preso il block e non deve congelare la generazione appena ruotata
- rotazione preventiva a `24h` attiva solo per `immobiliare`
  - guard state esteso con `profile_generation`, `profile_created_utc`, `profile_rotated_utc`, `profile_quarantine_reason`
  - root profilo effettiva derivata ora da `site/channel/profile_generation`
  - test aggiornati e suite locale `66` test `OK`
- fix successivo del `2026-03-27` su Camoufox profile realism:
  - persona persistente per `site/channel/profile_generation`
  - stessa generazione => stessa faccia di launch
  - variazioni solo tra generazioni profilo diverse
  - suite locale aggiornata a `69` test `OK`
- fix successivo del `2026-03-27` su GUI debugger mode:
  - checkbox `Modalita debugger`
  - artifact debug salvati in `runtime/debug` da sorgente o `./debug` accanto alla dist
  - bundle Windows stable ricostruito per soak VM
- cleanup successivo del `2026-03-27` su strategia `camoufox-only`:
  - rimosso `--channel-rotation-mode` dal percorso operativo
  - CLI live ristretta a `auto|camoufox`
  - rimosso dal core il ramo di alternate-browser retry non piu strategico
- hardening successivo del `2026-03-28` su render consistency / pacing:
  - aggiunto `render_context.py` con `init_script` globale sul `BrowserContext`
  - descrittori `navigator` e WebGL stabilizzati per coerenza cross-host
  - `toDataURL()` del Canvas riallineato con rumore statico deterministico
  - introdotto `apply_interaction_pacing()` con distribuzione `Gamma(2.0, 1.5)`
  - pacing applicato prima di `page.goto`, `click` e chiusura `context/browser`
  - test mirati aggiunti; suite locale salita a `80` test `OK`
- hardening successivo del `2026-03-28` su setup rete/static assets:
  - aggiunto `bootstrap_static_resources_cache()` nel launch della sessione browser
  - warm-up tecnico su endpoint `gstatic`, `google.it` e `cloudflare`
  - nessuna navigazione del workflow principale sporcata: bootstrap su pagina temporanea e chiusura immediata
  - review locale conferma che la policy `interstitial_datadome != hard_block` resta invariata
  - suite locale salita a `81` test `OK`
- hardening successivo del `2026-03-28` su osservabilita e packaging:
  - log dettagliati aggiunti su render context, pacing Gamma, bootstrap static resources e chiusura sessione
  - bundle Windows riallineato all'artefatto `dist/affitto_2_2_1_stable_bundle.zip`
  - target di consegna aggiornato a release `2.2.1 stable`
- refactor strutturale del `2026-03-30`:
  - `live_fetch.py` diviso in moduli `browser/guard/sites`
  - `render_context.py` reso policy-driven tramite hardware signature
  - `hard_block` con disposition esplicita del vecchio profilo persistente
  - suite locale aggiornata a `84` test `OK`
- fix successivo del `2026-03-30` sui drift post-refactor:
  - `accept_cookies` policy-aware per sito
  - `guard_jitter_*` reintegrati come clipping del Gamma pacing
  - suite locale aggiornata a `85` test `OK`
- release successiva del `2026-03-30`:
  - bundle Windows riallineato all'artefatto `dist/affitto_2_2_2_refactorizzata_bundle.zip`
  - target di consegna aggiornato a release `2.2.2 refactorizzata`

## Lettura tecnica del soak
- `idealista` mostra continuita forte:
  - un solo profilo persistente iniziale
  - riuso same-site fino a `max_reuse_count=59`
  - nessun segnale di degrado o cooldown nei log osservati
- `immobiliare` lavora bene su `camoufox`, ma il ramo applica un recycle preventivo dello slot:
  - trigger osservato: `slot_reuse_cap`
  - soglia attuale in codice: `max_reuse_count=12`
  - il recycle e locale al sito e non degrada il servizio
- la distinzione locale vs globale del runtime sta quindi lavorando come previsto:
  - il runtime condiviso viene preservato
  - solo lo slot del sito caldo viene ricreato quando serve

## Limite aperto piu concreto
Il tema aperto non e oggi la tenuta base di `camoufox`, ma la qualita dell'identita persistente che presentiamo ai siti, la precisione residua di `private_only` e la semplificazione del core legacy che non riflette piu la strategia reale.

Nei log osservati:
- `idealista` regge bene con continuita lunga e oggi non giustifica rotazione preventiva
- `immobiliare` ha mostrato un vero `hard_block` compatibile con identity persistente "stanca"
- il ramo ha quindi chiuso la prima difesa strutturale sul profilo
- il passo successivo sensato e rendere la creazione dei profili Camoufox piu umanizzata e coerente con ambienti reali

Tradotto:
- la tenuta del motore e buona
- la continuita profilo va trattata come superficie anti-block a parte
- la garanzia "solo privati" resta importante, ma non e piu l'unico fronte vivo
- il guard va reso piu leggibile quando il degrado nasce dal codice o dalla reputazione profilo
- la parte piu debole del ramo non e piu il monolite puro di `live_fetch.py`, ma il completamento del riallineamento dei contratti attorno ai moduli nuovi

## Review soak VM del 2026-03-27
- file di riferimento:
  - `docs/tmp_logs.md`
  - `dist/affitto_gui/debug/*idealista*`
  - `dist/affitto_gui/debug/*immobiliare*`
- finestra osservata:
  - `22:00:17 -> 23:30:29`
- risultato sintetico:
  - `19` cicli osservati
  - `17` cicli full `healthy`
  - `2` cicli con `blocked=1`
  - `2` rotate profilo esplicite
  - `2` recovery complete
- lettura corretta:
  - il fix sul cooldown associato alla generazione bloccata si comporta bene
  - il servizio non freeze dopo il `hard_block`
  - il nuovo profilo rilancia senza aspettare la fine del cooldown vecchio
  - in questa finestra `immobiliare` non e sensibilmente peggiore di `idealista`

## Differenza concreta tra `idealista` e `immobiliare`
- `idealista` oggi fa il lavoro piu costoso lato `private_only`:
  - detail-check
  - cache reuse professionali
  - batch pause
- `immobiliare` non e piu pesante sul piano retry/touch; la differenza di flow piu visibile e nella `prepare phase`:
  - `immobiliare`:
    - eventuale click `switch-to-list`
    - scroll sul container risultati
  - `idealista`:
    - attesa risultati
    - scroll pagina piu semplice
- i `hard_block` del soak comunque arrivano gia in `after_goto` tramite DataDome, quindi non vanno imputati in modo meccanico al solo scroll

## Direzione scelta per le prossime patch
- si lavora su stabilita e osservabilita; il ramo ora include anche un render context deterministico e un pacing interazionale esplicito
- le prossime slice sensate sono:
  - `immobiliare adaptive prepare`
  - notifica blocco lungo `>= 1h` + recovery
  - eventuale `soft mode` locale per `1-2` cicli dopo `hard_block`
- fuori scope:
  - spoofing avanzato hardware/GPU oltre il profilo statico gia codificato per coerenza cross-host
  - jitter artificiale di rete/request oltre il pacing applicato alle interazioni Playwright
  - pre-heating su domini esterni
  - patch orientate a bypass aggressivo

## File da leggere per ripartire
- `README.md`
- `docs/risk_scoring_e_griglia_segnali_antibot.md`
- `docs/context/STRATEGY_2_2_TEST.md`
- `docs/context/STATE_MACHINE_2_2_TEST.md`
- `docs/context/EXPERIMENT_PLAN_2_2_TEST.md`
- `docs/context/STOP_TRIGGERS_2_2_TEST.md`
- `docs/context/PROMOTION_GATE_2_2_TEST.md`
- `docs/context/codex/ACTIVE_PATCH.md`
- `docs/tmp_logs.md`

## Prossimo passo sensato
- mantenere la modalita GUI `debugger` come percorso standard di osservabilita nei soak
- eseguire il soak VM della release `2.2.2 refactorizzata`
- aprire poi la slice `immobiliare adaptive prepare`
- aggiungere la notifica blocco lungo + recovery
- valutare solo dopo un `soft mode` locale post-block
