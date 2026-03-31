       RESOCONTO COMPLETO E APPROFONDITO - REPOSITORY AFFITTO

       1. STRUTTURA DELLA REPOSITORY E VERSIONI

       Versioni principali presenti:
       - v1_stable: versione legacy storica
       - 2.1_stable: baseline storicamente importante, congelata come release stabile
       - 2.2_stable: versione precedente di questo taglio (ora congelata)
       - 2.2_test: evoluzione della 2.2, usata come laboratorio prima di diventare stable
       - 2.3_test: VERSIONE CORRENTE - creata il 2026-03-30 come copia completa di 2.2_test per aprire il
       prossimo ciclo di lavoro in ambiente separato

       Organizzazione del perimetro Git pulito (escludendo .venv, node_modules, pycache, build, dist,
       runtime):
       2.3_test/
       ├── src/affitto_v2/          # codice sorgente principale
       ├── tests/                   # suite di test (85 test OK alla patch 2.2.2)
       ├── scripts/                 # script di setup e build (PowerShell per Windows)
       ├── packaging/               # config packaging per Windows bundle
       ├── docs/                    # documentazione operativa
       │   ├── context/             # contesto vivo della linea
       │   │   ├── docs/            # archive 2.2 storico archiviato
       │   │   ├── codex/           # workflow Codex vivo per agenti
       │   │   └── archive/         # snapshot 2.2 per recovery storico
       │   ├── risk_scoring_e_griglia_segnali_antibot.md  # fondamentale
       │   └── [altri doc]          # email setup, packaging, audit v1
       ├── README.md
       └── requirements.txt

       ---
       2. FUNZIONAMENTO TECNICO DELL'APP

       2.1 Architettura alto-livello

       L'app è uno scraper specializzato per portali immobiliari italiani (Idealista e Immobiliare) con:
       - Backend operativo: camoufox (Firefox-based browser automation)
       - Modalità: sia esecuzione singola (fetch-live-once) che continua (fetch-live-service)
       - Filosofia: "non violare, convivere" — progettato per operare all'interno dei limiti anti-bot dei
       siti target

       2.2 Scraping meccanismo
       Flusso principale:
       1. Configurazione sito-specifica (src/affitto_v2/scrapers/sites/:
         - idealista.py: pattern match per listing, agency detection, private-only filtering
         - immobiliare.py: list switch, scroll selectors, listing patterns
       2. Fetch orchestration (live_fetch.py):
         - Itera su URL di ricerca configurati
         - Gestisce ciclo navigazione con pacing controllato
         - Estrae annunci tramite parser per ogni sito
         - Filtra privati (annunci senza intermediario) se configurato
       3. Parsing e estrazione:
         - Per Idealista: identifica annunci privati via text analysis e link professionale
         - Per Immobiliare: estrae titolo, prezzo, ubicazione da DOM strutturato
         - Memorizza su DB locale (ListingRecord)

       2.3 Pacing e timing anti-bot

       Distribuzione Gamma per interazioni:
       # Da session_policy.py
       pacing_gamma_shape=2.0      # forma distribuzione
       pacing_gamma_scale=1.5      # scala (ritardo medio = 3s)

       Applica pacing a:
       - page.goto() — navigazione tra pagine di ricerca
       - page.click() — click su elementi DOM
       - Chiusura context/browser — cleanup ordinato

       Bootstrap statico risorse:
       - Pre-warming endpoint cloudflare e google per coerenza rete iniziale
       - Wait commit su pagina tecnica, poi chiusura prima di operazioni

       2.4 Gestione anti-bot e challenge

       Detection patterns:
       _CAPTCHA_URL_KEYS = ("captcha-delivery.com", "/captcha", "datadome")
       _HARD_BLOCK_PATTERNS = [
           r"uso\s+improprio",
           r"accesso.{0,40}bloccat",
           "contatta.{0,30}assistenza"
       ]

       Risposta a challenge:
       - DataDome interstitial: trigger cooldown controllato + probe ritardata
       - Hard block HTTP (403, 429): rotazione profilo + cooldown biologico lungo
       - Challenge visibile: stop run, log dettagliato, escalation a assist_required

       Detection DataDome specifico:
       - Controlla URL per geo.captcha-delivery.com/interstitial
       - Monitora cookie di sessione DataDome
       - Applica delay probe prima di retry

       2.5 State machine e guard logic

       Stati del run (guard/state_machine.py):
       warmup -> stable -> [suspect/degraded] -> [cooling/challenge_seen] -> [blocked/assist_required]

       Transizioni criteri:
       - healthy (outcome) → stable/warmup (stato)
       - suspect (outcome) → riduce budget, monitora segnali
       - degraded (outcome) → output minimo, escalation se ripetuto
       - cooling (outcome) → skip pulito per cooldown
       - blocked (outcome) → fine run, assist richiesto

       Triggers stop minimi (STOP_TRIGGERS_2_3_TEST.md):
       - Primo challenge → cooldown breve
       - Due challenge ravvicinati → frozen
       - Budget esaurito (page/detail/identity/retry) → stop sito
       - Due finestre degraded consecutive → assist_required
       - Cooldown budget esaurito → frozen
       - Sessione assist_required → stop servizio continuo

       2.6 Profili persistenti e identità

       Modello profilo (browser/persona.py):
       @dataclass
       class CamoufoxPersona:
           version: int                    # versione schema
           persona_id: str                 # ID univoco
           seed: int                       # deterministica generazione
           site: str                       # affinity sito
           channel_label: str              # browser/canal
           profile_generation: int         # rotazione counter
           screen_label: str               # schermo nominale
           humanize_max_sec: float         # delay massimo umano
           launch_options: dict            # config camoufox materializzata

       Gestione profilo:
       - Profilo separato per site/channel/generation
       - Reuse limitato al solo owner
       - Rotazione su hard_block (reset profilo vecchio)
       - Rotazione preventiva a 24h su immobiliare
       - Cooldown vincolato alla generazione bloccata (non congela generazione nuova)
       Pool di sessioni (core_types.py):
       @dataclass
       class BrowserSessionSlot:
           owner_key: str              # site_channel_gen
           site: str
           channel_label: str
           profile_root: str
           browser, context, page      # oggetti Playwright attivi
           reuse_count: int
           created_monotonic: float

       ---
       3. STORIA DELLE VERSIONI E DECISIONI ARCHITETTURALI

       Evoluzione da v1 a v2.2

       v1_stable (legacy):
       - Browser automation base senza profili persistenti
       - Challenge handling rudimentale
       - No state machine

       2.1_stable (primo consolidamento):
       - Introdotti profili persistenti per sito
       - State machine base (warmup/stable/degraded/blocked)
       - Email notification setup
       - GUI Tkinter base
       - Bugfix su private_only accuracy

       2.2 evolution (30 patch circa):



       ┌─────────────────┬─────────────┬──────────────────────────────────────────────────────────────────
       ┐
       │     Periodo     │  Milestone  │                         Decisione chiave
       │
       ├─────────────────┼─────────────┼──────────────────────────────────────────────────────────────────
       ┤
       │ Fase init       │ Milestone 0 │ Telemetria minima (RiskBudget, TelemetrySnapshot), blocco retry
       │
       │                 │             │ cross-browser
       │
       ├─────────────────┼─────────────┼──────────────────────────────────────────────────────────────────
       ┤
       │ Consolidamento  │ Milestone 1 │ Session pooling per owner, profili isolati per site/channel,
       │
       │                 │             │ profilo_generation tracking
       │
       ├─────────────────┼─────────────┼──────────────────────────────────────────────────────────────────
       ┤
       │ Scheduler       │ Milestone   │ Servizio continuo fetch-live-service, cadenza configurable,
       │
       │ continuo        │ 1.5         │ overlap prevention
       │
       ├─────────────────┼─────────────┼──────────────────────────────────────────────────────────────────
       ┤
       │ Core refactor   │ Strutturale │ Separazione concerns: session_policy.py, bootstrap.py,
       │
       │                 │             │ factory.py, state_machine.py, site configs
       │
       ├─────────────────┼─────────────┼──────────────────────────────────────────────────────────────────
       ┤
       │ Render context  │ Patch       │ Deterministic hardware mimetics, user_agent in policy, canvas
       │
       │                 │             │ noise statico
       │
       ├─────────────────┼─────────────┼──────────────────────────────────────────────────────────────────
       ┤
       │ Pacing          │ Patch       │ Gamma distribution (shape=2.0, scale=1.5), pre-interaction +
       │
       │                 │             │ bootstrap static resources
       │
       ├─────────────────┼─────────────┼──────────────────────────────────────────────────────────────────
       ┤
       │ Profile reset   │ Hardening   │ Hard block → rotate profilo, rotazione preventiva 24h
       │
       │                 │             │ immobiliare, binding cooldown a generation
       │
       ├─────────────────┼─────────────┼──────────────────────────────────────────────────────────────────
       ┤
       │ Bundle Windows  │ Packaging   │ PyInstaller bundle stabile con runtime Tcl/Tk incluso, naming
       │
│                 │             │ affitto_2_3_test_bundle.zip
       │
       ├─────────────────┼─────────────┼──────────────────────────────────────────────────────────────────
       ┤
       │ Camoufox        │ Backend     │ Migrazione da multi-browser fallback a camoufox-only (decisione
       │
       │ adoption        │             │ critica per TLS coherence)
       │
       └─────────────────┴─────────────┴──────────────────────────────────────────────────────────────────
       ┘

       Patch storica rilevante della 2.2 (dal HISTORY.md)
       2026-03-27 — Observable autohealing:
       - Browser affinity per sito (Idealista → msedge, Immobiliare → chrome)
       - Hard block non osservato in VM log lunghi
       - Fix su private_only accuracy: memoria negativa per annunci professionali

       2026-03-28 — Render context + pacing:
       - Deterministic hardware mimetics inline nel render context init script
       - Gamma pacing applicato a goto/click/close
       - Bootstrap static resources cache
       - Nessun bug bloccante emerso, release target 2.2.1

       2026-03-30 — Refactor strutturale (SoC):
       - Creati moduli specializzati per session_policy, bootstrap, factory, guard state_machine
       - render_context.py reso policy-driven
       - live_fetch.py ridotto a orchestratore
       - Hard block applica disposizione esplicita del profilo vecchio (prune + destroy)
       - Estratti contracts in core_types.py, persistenza in guard/store.py, persona in browser/persona.py
       - Suite salita a 85 test OK

       ---
       4. STATO CORRENTE DELLA 2.3_TEST

       Patch aperta: 2.3-patch-01

       Data: 2026-03-31
       Descrizione: Allineamento UA/TLS Firefox/135.0 + rimozione navigator.deviceMemory

       Motivazione tecnica:
       - Camoufox è Firefox-based → TLS fingerprint = Firefox
       - Dichiarava UA Chrome/134 → mismatch passivamente rilevabile (JA4, DataDome, Cloudflare)
       - navigator.deviceMemory è Chrome-only → JavaScript anomaly patch rimossa
       - navigator.userAgent e navigator.hardwareConcurrency riallineati

       File modificati:
       session_policy.py:
         _DEFAULT_USER_AGENT:
           "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0"

       render_context.py:
         - HardwareMimetics inline (x2): UA aggiornato
         - defineNavigatorValue('deviceMemory', ...) rimosso
         - DEVICE_MEMORY replacement rimosso
         - campo navigator_device_memory rimosso da log install_render_context_init_script()

       Stato: Applicata, in attesa di soak su sessione reale

       Non-scope:
       - No state machine changes
       - No pacing changes
       - No WebGL strings changes
       - No hardwareConcurrency changes
       - No canvas noise changes

       Baseline ereditata dalla 2.2.2 refactorizzata:

       - Backend: camoufox
       - Servizio continuo: fetch-live-service
       - Profili persistenti per sito/channel/generation
       - Rotate profilo su hard_block
       - Render context deterministico
       - Pacing Gamma
       - Bootstrap static resources
       - Refactor strutturale completato

       ---
       5. BACKLOG ATTUALE E PROSSIMI STEP

       Milestone 1: Parity Validation (APERTA)

       Obiettivo: Confermare che 2.3_test parta osservabilmente allineata a 2.2

       Deliverable:
       - Verifica parita outcome_tier, state_transition, runtime_disposition, service_state
       - Chiarimento delta locali gia presenti (es. requirements.txt con undetected-playwright==0.3.0)
       - Soak su sessione reale parallela

       KPI minimi:
       - outcome_tier: healthy/suspect/degraded/blocked distribution
       - state_transition: warmup/stable/cooldown paths
       - runtime_disposition: keep/recycle_site_slot/recycle_runtime tracking
       - service_state: stable/degraded/assist_required

       Milestone 2: Site-local Refinement (CANDIDATI)

       Scegliere uno solo per volta:
       1. Immobiliare adaptive prepare
         - Eliminare passaggi meccanici inutili nella prepare phase (switch-to-list, scroll non necessari)
         - Regola: no patch larga, nessuna attribuzione automatica dei block al solo scroll
         - Confronto sempre contro baseline 2.2
       2. Long block observability (>= 1h)
         - Notificare in modo leggibile blocco lungo
         - Una sola notifica ingresso + una sola recovery
         - Zero rumore alert ad ogni ciclo
       3. Site-local soft mode post-hard_block
         - Ridurre pressione 1-2 cicli sul sito appena bloccato
         - Non toccare cadence globale servizio
         - Non degradare altro sito

       Milestone 3: Orchestrator Readability (SECONDARIA)

       Proseguire scomposizione live_fetch.py solo se migliora leggibilita, test e diagnostica

       Milestone 4: Promotion Gate (FUTURA)

       Promuovere solo patch che:
       - Migliora almeno una metrica chiave su run comparabili
       - Non peggiora altro sito
       - Non aumenta costo supporto
       - Non aggiunge rituali manuali

       ---
       6. ANTIBOT SIGNALS E DETECTION LANDSCAPE

       Tecniche antibot moderne (da risk_scoring_e_griglia_segnali_antibot.md)

       Tier 1: quasi sempre determinanti
       1. TLS/transport fingerprint (JA4, JA3):
         - Porte della stretta TLS: versione, ALPN, SNI, suite, estensioni
         - Paper Jarad & Bıçakcı 2026: AUC ~0.998, accuracy ~0.9862 con XGBoost su JA4DB
         - Feature pesanti: ja4_b, cipher_count, ext_count, ALPN, OS, SNI, TLS version
         - Camoufox/Firefox-based aiuta coherence qui
       2. JS runtime / client-side detections:
         - Cloudflare JSD: headless artifacts, API availability, DOM consistency, malicious fingerprints
         - Iniettato su ogni page view HTML
         - DataDome Device Check: verifica automatica device senza user interaction
         - Effetto browser reale: MOLTO ALTO qui
       3. Session continuity / risk cookies:
         - Cloudflare __cf_bm: cifrato, per-sito, scade 30 min inattivita
         - Contiene session identifier e anomaly detection context
         - Smoothing di sessione riduce falsi positivi
         - Effetto browser reale persistente: MOLTO ALTO qui
       4. Sequence + timing tra endpoint:
         - Cloudflare Sequence Rules: ordine richieste, tempo tra endpoint
         - Modella sequenze valide/invalide per funnel ripetitivi
         - Particolarmente rilevante per classifieds (ricerca → lista → dettaglio)
         - Effetto browser reale: BASSO-MEDIO
       5. ML fusion layer:
         - Cloudflare Bot Score 1-99
         - reCAPTCHA v3 risk score per request
         - Unisce tutti i segnali in scoring composito

       Tier 2: molto utili ma subordinate
       - IP/ASN/reputazione rete (Tier 1 passive, browser reale aiuta BASSO)
       - Header e protocol consistency (Tier 1 passive, browser reale aiuta MEDIO)
       - Device fingerprinting (centinaia segnali device, browser reale aiuta MOLTO ALTO)
       - Anomaly detection (deviation da baseline sito)

       Tier 3: potenti ma selettive
       - Mouse dynamics (efficacia ACM 2021, basso senza interazione reale)
       - Keystroke/interaction biometrics (MEDIO su login/search)
       - Graph-based backend models (BASSO se navigazione meccanica)

       Dove browser reale aiuta MOLTO:

       - Runtime JS checks
       - Device/environment verification
       - Session continuity e accumulo score
       - Coherence cross-request
       - Context locale accumulation

       Dove browser reale aiuta POCO:

       - IP reputation (origine sospetta rimane sospetta)
       - TLS fingerprint (se origine già sospetta)
       - Pattern temporali regolari (comportamento meccanico resta meccanico)
       - Session-URL graph anomalo
       - Biometria comportamentale (senza interazione umana reale)

       Segnali rilevati in Idealista/Immobiliare (plausibili):
       - Telemetria passiva di rete e request pattern
       - Strumentazione JS invisibile (non noto pubblico stack)
       - Session continuity con cookie rischio
       - Sequence/timing su lista annunci, pagine dettaglio, funnel contatto
       - ML che fonde i segnali
       - Challenge esplicite solo quando serve

       ---
       7. STRATEGIA DI LINEA 2.3

       Principi guida

       1. Preservare prima di cambiare
         - Baseline 2.2.2 refactorizzata è punto di partenza pratico
         - Ogni patch deve dire: cosa preserva, cosa cambia, come si confronta
       2. Un asse sperimentale per volta
         - NON mischiare: prepare phase + notifiche + lifecycle + parser + packaging
       3. Misurare prima di promuovere
         - Patch devono essere confrontabili su soak, log, costo operativo
         - Template esperimento: ipotesi, variabile, metrica primaria/rischio, finestra osservazione,
       criterio fallimento, rollback
       4. Nessun ritorno a scorciatoie dismesse
         - Multi-browser: NO (camoufox-only)
         - CDP: NO (Playwright async)
         - Spoofing aggressivo: NO
         - Pre-heating esterni: NO
         - Patch speculative senza sintomi reali: NO

       Regola pratica per patch

       Ogni patch di 2.3_test DEVE:
       - Preservare il comportamento sano della 2.2
       - E inoltre, ridurre rumore OPPURE migliorare osservabilita OPPURE migliorare private_only in modo
       misurabile

       Confine tra 2.2 stable e 2.3_test

       2.2 stable (shipping line):
       - Mantenimento consolidato
       - Fix prudenziali supportabili
       - Packaging e validazione distribuzione
       - Nessun salto strategia senza nuova evidenza

       2.3_test (disciplined lab):
       - Refinement per-sito
       - Osservabilita operativa nuova
       - Alleggerimento costi interazionali
       - Ulteriori slice strutturali se aiutano leggibilita

       ---
       8. TELEMETRIA E KPI

       Snapshot telemetria minima (TelemetrySnapshot):

       site                            # idealista | immobiliare
       browser_mode                    # managed_stable
       channel_label                   # camoufox
       identity_switch                 # conteggio switch identita
       session_age_sec                 # da warmup_started | last_success | last_attempt
       profile_age_sec                 # da profile_created_utc
       profile_generation              # versione profilo (rotazione counter)
       cooldown_profile_generation     # generazione in cooldown (se diversa)
       detail_touch_count              # aperture dettaglio per private_only
       retry_count                     # tentativi per outcome
       risk_pause_reason               # challenge_seen_first|cooldown_active|suspect_observe...
       outcome_tier                    # healthy|suspect|degraded|cooling|blocked
       outcome_code                    # specifico codice fallimento
       cooldown_origin                 # blocco family: interstitial|hard_block|challenge
       manual_assist_used              # bool intervento umano
       state_transition                #
       warmup|stable|suspect|degraded|challenge_seen|cooldown|blocked|assist_required
       assist_entry_mode               # challenge_repeat|persistent_degraded

       Risk budget (RiskBudget):

       page_budget                     # pagine ricerca permesse
       detail_budget                   # aperture dettaglio per private_only
       identity_budget                 # switch identita permessi
       retry_budget                    # retry per outcome
       cooldown_budget                 # finestre cooldown permesse
       manual_assist_threshold         # soglia escalation a assist

       Metriche summary run (LiveFetchRunReport):

       retry_count, detail_touch_count, identity_switch_count
       same_site_profile_reuse_count, cross_site_session_reuse_count, site_session_replace_count
       cooldown_count, site_outcome_tiers

       Metriche servizio continuo (fetch-live-service):
       failure_count               # cicli con errore
       overrun_count              # cicli oltre soglia tempo
       missed_cycle_count         # slot persi per delay
       service_state              # stable|degraded|assist_required

       ---
       9. ARCHIVIO STORICO E DECISION LOG

       Documenti di provenienza 2.2 archiviati in:

       docs/context/archive/2_2/
         ├── 2_2_TEST_MANIFEST.md
         ├── README.md
         ├── HANDOFF_2_2_LINE.md
         ├── NEXT_STEPS_2_2_LINE.md
         ├── ROADMAP_NEXT_MILESTONES_2_2_LINE.md
         ├── STRATEGY_2_2_TEST.md
         ├── STATE_MACHINE_2_2_TEST.md
         ├── STOP_TRIGGERS_2_2_TEST.md
         ├── EXPERIMENT_PLAN_2_2_TEST.md
         ├── PROMOTION_GATE_2_2_TEST.md
         └── codex_2_2_line.md

       docs/context/codex/archive/2_2/
         ├── README.md
         ├── ACTIVE_PATCH.md
         ├── HISTORY.md
         ├── INDEX.md
         ├── OUTPUT_CURRENT.md
         ├── PROMPT_CURRENT.md
         ├── REVIEW_CURRENT.md

       Decisioni critiche storiche (tratte da HISTORY.md):

       Profile rotation e binding cooldown (2026-03-27):
       - Hard block → rotate profilo (preemptive anche per 24h su immobiliare)
       - Cooldown vincolato a generazione bloccata (non congela nuova generation)
       - Telemetria estesa con profile_generation, profile_age_sec, cooldown_generation

       Camoufox adoption (2026-03-26):
       - Migrazione da multi-browser fallback (Chromium | Chrome | Firefox | Edge)
       - Test VM lungo: 60 cicli, 100% stable, no degraded/blocked/assist_required
       - Idealista: forte continuita sessione stesso profilo
       - Immobiliare: ricicla periodicamente per slot_reuse_cap

       Private_only accuracy (2026-03-26):
       - Memoria negativa annunci professionali (tabella DB separata)
       - Detail-check salva professionali anche se scartati da pipeline
       - Riuso DB evita riaperture ripetute

       Render context deterministico (2026-03-28):
       - hardware mimetics inline (user_agent, deviceMemory, hardwareConcurrency, WebGL)
       - Canvas noise statico deterministico
       - Pacing Gamma (shape=2.0, scale=1.5) pre-interaction
       - Bootstrap static resources cache

       Refactor strutturale (2026-03-30):
       - Separation of concerns: session_policy, bootstrap, factory, guard state_machine, site configs
       - Render_context policy-driven da hardware signature
       - Live_fetch ridotto a orchestratore
       - Hard_block aplica disposizione profilo vecchio (prune + destroy)

       ---
       10. STRUTTURA DEL CODICE PRINCIPALE

       Moduli chiave
        ┌────────────────────────┬───────────────────────────────────┬────────┬────────────────────────────
       ─┐
       │         Modulo         │          Responsabilita           │ Linee  │            Note
        │
       ├────────────────────────┼───────────────────────────────────┼────────┼────────────────────────────
       ─┤
       │ live_fetch.py          │ Orchestrazione run, cicli fetch,  │ ~1500+ │ Motore centrale, ridotto da
        │
       │                        │ scraping                          │        │  refactor strutturale
        │
       ├────────────────────────┼───────────────────────────────────┼────────┼────────────────────────────
       ─┤
       │ render_context.py      │ Hardware mimetics deterministici, │ ~200   │ Policy-driven, no
        │
       │                        │  JS init script                   │        │ deviceMemory patch
        │
       ├────────────────────────┼───────────────────────────────────┼────────┼────────────────────────────
       ─┤
       │ session_policy.py      │ Policy per sito (UA, hardware,    │ ~80    │ UA Firefox/135.0, no Chrome
        │
       │                        │ pacing, bootstrap)                │        │
        │
       ├────────────────────────┼───────────────────────────────────┼────────┼────────────────────────────
       ─┤
       │ guard/state_machine.py │ Transizioni stato, telemetria,    │ ~250+  │ Tabellare, outcomes → state
        │
       │                        │ decision applying                 │        │
        │
       ├────────────────────────┼───────────────────────────────────┼────────┼────────────────────────────
       ─┤
       │ guard/store.py         │ Persistenza state, profilo        │ ~200+  │ JSON file-based
        │
       │                        │ rotation, cooldown                │        │
        │
       ├────────────────────────┼───────────────────────────────────┼────────┼────────────────────────────
       ─┤
       │ browser/persona.py     │ CamoufoxPersona, profili, session │ ~300+  │ Materialized launch options
        │
       │                        │  identity                         │        │
        │
       ├────────────────────────┼───────────────────────────────────┼────────┼────────────────────────────
       ─┤
       │ browser/bootstrap.py   │ Setup context, render context     │ ~150+  │ Deterministic initial state
        │
       │                        │ install, static resources         │        │
        │
       ├────────────────────────┼───────────────────────────────────┼────────┼────────────────────────────
       ─┤
       │ browser/factory.py     │ Browser launch, context/page      │ ~150+  │ Camoufox-only
        │
       │                        │ creation                          │        │
        │
       ├────────────────────────┼───────────────────────────────────┼────────┼────────────────────────────
       ─┤
       │ sites/idealista.py     │ Selectors, patterns, private-only │ ~90    │ Agency detection,
        │
       │                        │  classification                   │        │ professional classification
        │
       ├────────────────────────┼───────────────────────────────────┼────────┼────────────────────────────
       ─┤
       │ sites/immobiliare.py   │ Selectors, patterns, list switch  │ ~30    │ Simpler than Idealista
        │
       ├────────────────────────┼───────────────────────────────────┼────────┼────────────────────────────
       ─┤
       │ core_types.py          │ Dataclasses: RiskBudget,          │ ~150   │ Contracts dati
        │
       │                        │ TelemetrySnapshot, RunRiskState   │        │
        │
       ├────────────────────────┼───────────────────────────────────┼────────┼────────────────────────────
       ─┤
       │ debug_artifacts.py     │ HTML/JSON artifacts per debug,    │ ~150+  │ Retention 72h, max 120 file
        │
       │                        │ artifact pruning                  │        │
        │
        └────────────────────────┴───────────────────────────────────┴────────┴────────────────────────────
       ─┘

       Flusso di esecuzione run singolo

       fetch_live_once()
         ├─ Load guard state (site cooldown, profile generation)
         ├─ Per ogni URL ricerca:
         │   ├─ Skip se in cooldown
         │   ├─ Load session slot (o crea)
         │   ├─ Check if probe due (interstitial)
         │   ├─ Navigate → goto(search_url) con pacing
         │   ├─ Accept cookies popup
         │   ├─ Immobiliare: click switch-to-list (if needed)
         │   ├─ Scroll/prepare con delay
         │   ├─ Wait selectors e estratti linkslistini
         │   ├─ Scrape ogni listing (titolo, prezzo, link)
         │   │
         │   ├─ Se private_only=True:
         │   │   ├─ Per candidato privato:
         │   │   │   ├─ Goto detail link
         │   │   │   ├─ Check agency signs (text, link /pro/)
         │   │   │   ├─ Classifica publisher (privato|professionista)
         │   │   │   └─ Salva su private_only_agency_cache
         │   │   └─ Filtra out professionali
         │   │
         │   ├─ Inserisci su DB listings
         │   ├─ Classifica outcome (HTTP status, challenge visibility, parse quality)
         │   │
         │   └─ Apply guard outcome:
         │       ├─ Aggiorna entry site (last_attempt, outcome_tier, cooldown, strikes)
         │       ├─ Se hard_block → rotate profilo, destroy vecchio, set cooldown
         │       ├─ Se challenge → cooldown breve + probe delay
         │       ├─ Advance run_state e mark assist se triggers
         │       └─ Build telemetry snapshot
         │
         └─ Chiudi context/browser con pacing
         └─ Ritorna LiveFetchRunReport

       Flusso servizio continuo

       fetch-live-service --max-cycles N
         ├─ Setup runtime condiviso (browser pool)
         ├─ Loop cicli:
         │   ├─ Check service_state
         │   │   ├─ stable → procedi
         │   │   ├─ degraded → log e procedi
         │   │   └─ assist_required → stop pulito
         │   ├─ Attendi cadenza (cycle_minutes)
         │   ├─ Chiama fetch_live_once()
         │   ├─ Leggi run_state, assist_required, stop_reason
         │   ├─ Decide runtime_disposition:
         │   │   ├─ healthy → keep runtime
         │   │   ├─ cooldown/blocked sito → recycle_site_slot
         │   │   ├─ failure tecnico → recycle_runtime
         │   │   ├─ assist_required → stop service
         │   │   └─ degraded multi-sito → recycle_runtime
         │   └─ Update service_state, log metriche
         └─ Cleanup runtime (close all browser/context)

       ---
       11. TECNICHE ANTI-BOT IMPLEMENTATE ATTUALMENTE

       Layer realismo browser

       1. Hardware mimetics deterministici:
         - navigator.userAgent: Firefox/135.0
         - navigator.hardwareConcurrency: 8
         - WebGL vendor/renderer: Intel Iris Xe
         - Canvas noise: statico per determinismo cross-host
         - NO navigator.deviceMemory (rimosso in 2.3-patch-01)
       2. Pacing umanizzato:
         - Gamma distribution ritardi pre-interaction
         - Bootstrap static resources warm-up
         - Delay prima click, goto, close
       3. Profile persistenza:
         - Per site/channel/generation
         - Reuse accumulato
         - Rotazione su hard_block
         - Cooldown vincolato a generazione

       Session coherence

       1. Cookie preservation:
         - First-party cookie storage nel profilo persistente
         - Accumulo stato sessione cross-visit
         - Timing coerente tra visite
       2. Sequence awareness:
         - Ordine request naturale (ricerca → lista → dettaglio)
         - Timing realistico tra endpoint
         - Nessuna parallelizzazione aggressiva

       Content-level defenses
       1. Selettori site-specific:
         - Idealista: agency logo/text, professional link detection
         - Immobiliare: list switch, scroll container selection
         - Nessun hardcoded XPath fragile
       2. Parser quality checks:
         - Validation campi obbligatori (title, price)
         - Fallback parsing se CSS specifico non corrisponde
         - Quality tier classification (good/degraded/parse_issue)

       Behavioral heuristics

       1. Private-only filtering:
         - Detail-check limittato a max 15 annunci
         - Delay 900-1800ms tra check
         - Pausa batch ogni 4 check (1600-3200ms)
         - Memoria negativa annunci professionali
       2. Challenge response:
         - DataDome interstitial rilevato e cooldown applicato
         - Hard block HTTP status (403, 429) → profilo rotate
         - No retry immediato dopo challenge

       ---
       12. NOTA SULLA SICUREZZA E COMPLIANCE

       Il codice monitora segnali anti-bot ma NON:
       - Bypassa o aggira crittografia/CAPTCHA forzato
       - Raccoglie dati PII
       - Usa attacchi clientside sull'infrastruttura target
       - Invia traffico malevolo o attacchi DoS

       Il codice:
       - Naviga pagine pubbliche con browser reale-like
       - Estrae dati visibili nel HTML
       - Implementa pacing e session coherence
       - Rispetta cooldown e challenge visibili
       - Si ferma quando il sito rifiuta chiaramente

       ---
       13. ROADMAP IMMEDIATA (2.3_test)

       1. MILESTONE 1: Parity Validation ← APERTA ADESSO
         - Soak su VM parallela per confronto 2.2 vs 2.3
         - Verifica outcome_tier/state_transition/runtime_disposition
         - Chiarimento delta locali (requirements.txt ereditato)
       2. MILESTONE 2: Site-local Refinement ← DOPO parity
         - Uno solo tra: immobiliare adaptive prepare, long block notification, soft mode
         - Patch piccola, misurabile, rollbackabile
       3. MILESTONE 3/4: Orchestrator readability + promotion gate
         - Futuri, secondari

       ---
       14. FILE CRITICI DA CONOSCERE
       ┌───────────────────────────────────────────────────┬──────────────┬─────────────────────┬─────────
       ─┐
       │                     Percorso                      │     Tipo     │      Proposito      │ Priority
        │
       ├───────────────────────────────────────────────────┼──────────────┼─────────────────────┼─────────
       ─┤
       │                                                   │              │ Stato antibot       │
        │
       │ docs/risk_scoring_e_griglia_segnali_antibot.md    │ Fondamentale │ 2025-2026,          │ MUST
        │
       │                                                   │              │ letteratura,        │ READ
        │
       │                                                   │              │ segnali             │
        │
       ├───────────────────────────────────────────────────┼──────────────┼─────────────────────┼─────────
       ─┤
       │ docs/context/HANDOFF.md                           │ Context      │ Snapshot stato 2.3  │ MUST
        │
       │                                                   │              │ al taglio           │ READ
        │
       ├───────────────────────────────────────────────────┼──────────────┼─────────────────────┼─────────
       ─┤
       │ docs/context/NEXT_STEPS.md                        │ Roadmap      │ Priorita prossimi   │ MUST
        │
       │                                                   │              │ step                │ READ
        │
       ├───────────────────────────────────────────────────┼──────────────┼─────────────────────┼─────────
       ─┤
       │ docs/context/STRATEGY_2_3_TEST.md                 │ Charter      │ Linee guida per     │ READ
        │
       │                                                   │              │ patch 2.3           │
        │
       ├───────────────────────────────────────────────────┼──────────────┼─────────────────────┼─────────
       ─┤
       │ docs/context/STATE_MACHINE_2_3_TEST.md            │ Reference    │ Model stato minimo  │ READ
        │
       ├───────────────────────────────────────────────────┼──────────────┼─────────────────────┼─────────
       ─┤
       │ docs/context/codex/OUTPUT_CURRENT.md              │ Status       │ Stato patch viva    │ READ
        │
       │                                                   │              │ corrente            │
        │
       ├───────────────────────────────────────────────────┼──────────────┼─────────────────────┼─────────
       ─┤
       │ docs/context/codex/HISTORY.md                     │ Log          │ Patch chiuse e      │ READ
        │
       │                                                   │              │ milestone           │
        │
       ├───────────────────────────────────────────────────┼──────────────┼─────────────────────┼─────────
       ─┤
       │ src/affitto_v2/scrapers/live_fetch.py             │ Core         │ Orchestrazione      │ KNOW
        │
       │                                                   │              │ principale          │
        │
       ├───────────────────────────────────────────────────┼──────────────┼─────────────────────┼─────────
       ─┤
       │ src/affitto_v2/scrapers/guard/state_machine.py    │ Core         │ State machine       │ KNOW
        │
       │                                                   │              │ tabellare           │
        │
       ├───────────────────────────────────────────────────┼──────────────┼─────────────────────┼─────────
       ─┤
       │ src/affitto_v2/scrapers/browser/session_policy.py │ Config       │ Policy per sito     │ KNOW
        │
       ├───────────────────────────────────────────────────┼──────────────┼─────────────────────┼─────────
       ─┤
       │ src/affitto_v2/scrapers/render_context.py         │ Spoofing     │ Hardware mimetics   │ KNOW
        │
       └───────────────────────────────────────────────────┴──────────────┴─────────────────────┴─────────
       ─┘

       ---
       CONCLUSIONE
    La repository affitto è un scraper specializzato e sofisticato per immobili italiani che implementa
        una strategia antibot pragmatica e misurata basata su:

       1. Realismo browser (camoufox + profili persistenti)
       2. Session coherence (cookie, timing, sequence awareness)
       3. Site-specific adaptation (selettori, pacing, content logic)
       4. Observable state machine (warmup → stable → suspect/degraded → cooldown/blocked/assist)
       5. Misurabile experimentation (telemetria minima, RiskBudget, KPI chiari)

       La linea 2.3_test è stata appena aperta come laboratorio disciplinato sopra la baseline 2.2.2
       refactorizzata consolidata in VM. La patch viva corrente (2.3-patch-01) allinea UA e TLS a
       Firefox/135.0, coerente col backend camoufox. Il prossimo passo è validare parita osservabile
       contro 2.2 prima di aprire refinement veri.
