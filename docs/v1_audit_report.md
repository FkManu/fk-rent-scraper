# Audit tecnico `v1_stable` (2026-03-11)

## Scope

Nota storica:
- questo audit descrive la baseline `v1_stable` pre-migrazione.
- i riferimenti a Playwright/Chrome sono storici e non rappresentano il backend operativo corrente di `2.2_test`, che ora usa `camoufox` come default.
Analisi completa della base esistente in `v1_stable` con focus su:
- stabilita runtime
- correttezza deduplica e notifiche
- coerenza configurazione/env
- preparazione a migrazione in `v2_test`

## Inventario rapido
- File Python principali: 7 (`bot.py`, `frontier.py`, `alerting.py`, `log_json.py`, `detectors.py`, `parsers.py`, `migrate_frontier_head_ts.py`)
- Test automatici: assenti
- Runtime artifacts inclusi nella cartella progetto:
  - `playwright-profile`: 1277 file
  - `logs/run.log`: 3,088,486 byte
  - `data.db`: 1,196,032 byte

## Findings (ordinati per severita)

### Critical
1. Eccezioni non gestite nel job schedulato
- Evidenza codice: `v1_stable/bot.py:875-887`, scheduler in `v1_stable/bot.py:939-941`
- Evidenza runtime: `v1_stable/logs/run.log` contiene `raised an exception`, `CaptchaDetected`, `EPIPE`, `EPERM`
- Impatto: il job schedulato puo fallire ripetutamente senza recovery robusto; stato operativo instabile.
- Azione v2: wrapper robusto del ciclo (cattura eccezioni per URL + per job), stato `DEGRADED`, backoff e restart controllato.

2. Credenziali nel file di esempio
- Evidenza: `v1_stable/.env.sample:2` contiene un token Telegram completo.
- Impatto: rischio leakage segreti e revoca token.
- Azione v2: sample solo con placeholder, segreti separati e cifrati localmente.

3. Configurazione URL incoerente tra sample e codice
- Evidenza codice: parsing `SEARCH_URLS` solo JSON o separatore `|` in `v1_stable/bot.py:57-67`
- Evidenza sample: commento e valore comma-separated in `v1_stable/.env.sample:5-6`
- Impatto: configurazioni valide per l'utente possono essere parse male (intera stringa come singolo URL).
- Azione v2: schema config unico validato (JSON array), con validazione UI prima del salvataggio.

### High
4. Snapshot top-K salvata per sito, non per query
- Evidenza: tabella `top_snapshots` keyed by `site` in `v1_stable/bot.py:142-147`; uso in `get_snapshot/set_snapshot` e pipeline `:819-841`.
- Impatto: con piu URL sullo stesso sito, una query puo "mascherare" novita di un'altra.
- Azione v2: key composta `(source_site, search_hash)`.

5. Nessuna retention temporale su `listings`
- Evidenza: tabella creata in `v1_stable/bot.py:128-139`; assenza purge periodica.
- Impatto: crescita DB nel tempo e degrado prestazioni.
- Azione v2: retention rolling 15 giorni (requisito confermato), cleanup scheduler dedicato.

6. Telegram send senza retry/backoff su rate limit
- Evidenza: `send_telegram_message` in `v1_stable/bot.py:223-253` (nessuna gestione 429/retry_after).
- Impatto: possibili notifiche perse in burst.
- Azione v2: coda notifiche con retry esponenziale e parsing `retry_after`.

7. Gestione CAPTCHA non adatta a esecuzione headless hidden
- Evidenza: `input()` in async flow `v1_stable/bot.py:355-357`; `run_hidden.vbs` usa esecuzione senza finestra `v1_stable/run_hidden.vbs:3`.
- Impatto: flussi manuali non affidabili; possono provocare errori di processo.
- Azione v2: policy CAPTCHA configurabile (`pause`, `skip`, `notify-only`) senza `input()` bloccante.

### Medium
8. Variabili env presenti ma non usate
- Evidenza env: `TELEGRAM_MIN_DELAY_MS`, `TELEGRAM_MAX_RETRIES`, `JITTER_PCT` (`v1_stable/.env:31-32,47`)
- Evidenza codice: assenti riferimenti in `bot.py`.
- Impatto: confusione operativa e tuning non effettivo.
- Azione v2: config versionata con validazione strict (errore su chiavi sconosciute).

9. Blocklist agenzie con matching solo substring
- Evidenza: parse lista in `v1_stable/bot.py:97`, check in `v1_stable/bot.py:284-288`.
- Impatto: falsi positivi/negativi, poca governabilita.
- Azione v2: regex compilate + test + CRUD da UI su SQLite.

10. Codice morto/duplicato
- Evidenza: `_safe_run` mai usata (`v1_stable/bot.py:39`), `detect_captcha` importata ma non usata (`v1_stable/bot.py:26`, `v1_stable/detectors.py:10`), `parsers.py` non referenziato.
- Impatto: manutenzione difficile, comportamento non chiaro.
- Azione v2: moduli puliti e testati, rimozione dead code.

11. Rumore log elevato e non strutturato in output runtime
- Evidenza: uso misto `print()` e logger JSON (`v1_stable/bot.py` diffuso, `v1_stable/log_json.py`).
- Impatto: monitoraggio meno affidabile e parsing difficile.
- Azione v2: logging unificato JSON + stream UI live + file rotation.

## Punti positivi da mantenere
- Uso Playwright asincrono con contesto persistente configurabile.
- Deduplica iniziale tramite `frontier` e salvataggio `seen_ids`.
- Escape HTML nel messaggio Telegram (`html_escape`) per robustezza output.
- Layout modulare gia avviato (`frontier`, `alerting`, `log_json`).

## Raccomandazione tecnica per v2
Nota: per robustezza e riduzione blocchi, puntare su "human-like and compliant crawling" (rate limit, pacing, gestione errori, captcha policy) e non su tecniche aggressive di bypass.

Stack consigliato v2 (Windows-first, .exe):
- Core: Python 3.12
- Browser: Playwright (canale Chrome opzionale)
- Storage: SQLite
- Config model: Pydantic + file cifrato per segreti
- GUI: PySide6 (piu curata)
- Packaging: PyInstaller onefile
- Scheduler: APScheduler + watchdog/restart policy

## Backlog migrazione (allineato alle priorita concordate)
1. Audit stabilita -> completato (questo documento).
2. Notifiche email (Gmail/Outlook preset) con invio immediato per nuovi annunci.
3. Packaging `.exe` single-file con configurazione persistente locale.
4. GUI configurazione curata (campi essenziali + log live).
5. Blacklist agenzie regex su SQLite.

## Criteri di accettazione minimi v2 (proposti)
- Polling configurabile con guardrail minimo 5 minuti.
- Deduplica combinata stabile e retention 15 giorni.
- Fallback robusto su errori rete/sito senza crash processo.
- Notifica evento di errore e restart automatico controllato.
- Nessun segreto hardcoded o committato nei template.

## Stato mitigazioni implementate in `v2_test` (update 2026-03-11)

- [x] Segreti in sample/config:
  - introdotti profili mittente separati (`email_profiles.json`) con cifratura locale DPAPI.
  - in `sender_mode=profile`, campi SMTP custom non persistono in `app_config.json`.
- [x] Stabilita runtime:
  - pipeline e comandi live con gestione errori robusta, log live strutturati e diagnostica.
- [x] Anti-bot hardening:
  - site guard per sito (jitter + cooldown backoff), rotazione browser channel, stato persistente.
  - distinzione captcha interattivo vs hard block statico.
- [x] Operativita GUI:
  - run control (`Run once`, ciclo, stop), reset site-guard, reset DB annunci.
  - lock campi notifiche per modalita e validazione URL con sanitizzazione tracking params.
- [x] Qualita estrazione:
  - parser site-specific Idealista/Immobiliare e fallback zona da titolo.
  - digest email per ciclo migliorata (campi puliti, riepilogo per sito).
