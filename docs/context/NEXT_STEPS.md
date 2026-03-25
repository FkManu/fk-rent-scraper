# NEXT_STEPS.md

## Punto di partenza
Questa root `2.1_stable` e la baseline privata pulita da cui ripartire.

Per ricostruire il contesto operativo minimo leggere prima:
1. `docs/context/HANDOFF.md`
2. `docs/context/2_1_STABLE_MANIFEST.md`
3. `docs/context/codex/REVIEW_2_1_STABLE.md`

## Priorita ragionevoli da qui in avanti
1. Validazione VM lunga della patch attuale **site guard + browser routing + private_only**:
   - confermare che `idealista` non ricada in lunghe sequenze di solo `cooldown_active` dopo un `interstitial_datadome`
   - verificare la presenza dei log di probe controllata del cooldown, invece del reset manuale come via standard
   - confermare che `idealista` usi `msedge` installato quando disponibile e che `immobiliare` resti su `chrome`
   - osservare quando scatta il retry con browser alternativo e se salva davvero qualche ciclo bloccato
2. Validazione VM della riduzione aperture dettaglio in `private_only`:
   - confermare che gli annunci gia presenti nel DB non vengano piu riaperti per riclassificazione
   - misurare il delta tra primo ciclo e cicli successivi nei log `Idealista private-only detail verification start`
   - verificare che i professionali gia noti nel DB vengano riusati senza nuova visita dettaglio
   - continuare a misurare `excluded_agency` e `allowed_without_agency_signal` per capire quanto resta ancora davvero `unknown`
3. Idea da approfondire in seguito: modalita opzionale **browser reale via CDP**:
   - non sostituire il path corrente `managed`; la modalita CDP deve restare opzionale
   - target operativo: usare un browser Chromium reale gia aperto dall'utente, collegandosi a `http://127.0.0.1:9222`
   - caso d'uso principale: bootstrap manuale challenge/login/2FA o recovery assistita quando `idealista` richiede una sessione umana gia calda
   - prerequisiti da documentare chiaramente:
     - browser avviato manualmente con `--remote-debugging-port=9222`
     - profilo dedicato separato da quello personale
     - nessuna chiusura automatica del browser fisico da parte dell'app
  - first step consigliato, solo se la riapriremo davvero:
     - patch CLI-only
     - nessuna GUI iniziale
     - nessuna rotazione canale automatica in modalita CDP
     - nessun retry cross-browser automatico in modalita CDP
     - strategia pagina prudente: preferire nuova tab dedicata rispetto al riuso aggressivo della tab utente
4. Continuare il lavoro di qualita parser solo dove serve:
   - ridurre i casi `partial_success_degraded`
   - migliorare soprattutto la lettura dei segnali agenzia su `idealista`
   - se serve, aggiungere telemetria leggera sugli annunci `private_only_unknown` residui per capire cosa passa ancora senza segnale ne in card ne in dettaglio
5. Chiusura operativa pre-push:
   - verificare l'hardening Windows della log rotation su run piu lunghi / GUI + subprocess
   - fare pulizia del working tree per la repo GitHub privata
   - escludere stabilmente i `docs/tmp_logs*.md` locali e selezionare i file docs/context da pubblicare
6. Solo dopo questi punti tornare su:
   - hardening/testability piu ampio del core live
   - installazione/distribuzione Windows piu blindata
   - rifinitura UX mirata
   - futura base operativa per vendibilita/supporto

Per il dettaglio completo vedere:
- `docs/context/ROADMAP_NEXT_MILESTONES.md`
- `docs/context/codex/TASK_FIRST_RUN_RELIABILITY.md`
- `docs/context/codex/TASK_OBSERVABLE_AUTOHEALING.md`

## Stato GitHub
- baseline privata gia pubblicata come repo privata:
  - `FkManu/fk-rent-scraper`
- branch attuale:
  - `main`
- commit iniziale:
  - `Initial private baseline from 2.1_stable`

## Cose da evitare
- non reimportare runtime, build, dist o transcript grezzi in questa root
- non riaprire `v1_stable` come base tecnica
- non aggiungere nuove feature solo perche la root e pulita

## Regola pratica
Nuove patch si aprono da qui, con scope piccolo e verificabile.

## Nota operativa aggiornata
- la review VM del 2026-03-25 ha mostrato che gli intoppi prioritari non erano chiusi:
  - GUI bundle non avviabile per packaging Tk incompleto
  - `idealista` poteva ricadere in un cooldown del site guard percepito come "loop di protezione"
  - il fallback da `msedge` a `chrome` su bundle peggiorava la probabilita di `interstitial_datadome`
- questi punti sono stati corretti nel workspace:
  - packaging GUI con runtime Tcl/Tk incluso
  - cooldown interstitial con probe controllata e clear challenge piu severo
  - uso dei browser reali installati e retry mirato con browser alternativo sui blocked outcome
  - riuso del DB per tagliare le visite dettaglio `private_only`
- la priorita quindi resta una sola:
  - validare in VM che il nuovo equilibrio regga per qualche ora senza reset manuali frequenti e con meno aperture dettaglio superflue
- valutazione strategica aggiuntiva del 2026-03-25:
  - una modalita `connect_over_cdp` puo avere senso come strumento specialistico di recovery/stabilizzazione
  - non va resa default:
    - richiede browser gia aperto e preparato manualmente
    - Playwright la documenta come connessione a fedelta inferiore rispetto al protocollo Playwright pieno
    - complica lifecycle, cleanup e supporto se usata come percorso standard
