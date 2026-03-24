# NEXT_STEPS.md

## Punto di partenza
Questa root `2.1_stable` e la baseline privata pulita da cui ripartire.

Per ricostruire il contesto operativo minimo leggere prima:
1. `docs/context/HANDOFF.md`
2. `docs/context/2_1_STABLE_MANIFEST.md`
3. `docs/context/codex/REVIEW_2_1_STABLE.md`

## Priorita ragionevoli da qui in avanti
1. Validazione VM della patch **Precisione fetch / annunci privati** gia implementata:
   - confermare che `idealista` non venga piu skippato troppo presto sui transient `interstitial_datadome` auto-risolti
   - confermare che il secondo controllo dettaglio marchi come `Professionista` parte degli annunci ancora "buoni" a livello card
   - verificare esplicitamente che casi come `35159080` e `35009314` vengano ora scartati
   - misurare ancora `excluded_agency` e `allowed_without_agency_signal` con log reali, verificando un calo credibile di quest'ultimo su `idealista`
   - controllare che il pacing piu lento del detail-check non faccia salire challenge / interstitial rispetto ai run precedenti
2. Continuare il lavoro di qualita parser:
   - ridurre i casi `partial_success_degraded`
   - migliorare soprattutto la lettura dei segnali agenzia su `idealista`
   - se serve, aggiungere telemetria leggera sugli annunci `private_only_unknown` residui per capire cosa passa ancora senza segnale ne in card ne in dettaglio
3. Chiusura operativa pre-push:
   - verificare l'hardening Windows della log rotation su run piu lunghi / GUI + subprocess
   - fare pulizia del working tree per la repo GitHub privata
   - escludere stabilmente i `docs/tmp_logs*.md` locali e selezionare i file docs/context da pubblicare
4. Solo dopo questi punti tornare su:
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
- la review log di alcune ore su VM mostra:
  - `immobiliare` stabile e `healthy` su `chrome`
  - `idealista` senza `hard_block`, ma ancora spesso `degraded`
- la review log+DOM del 2026-03-24 ha aggiunto due fix mirati su `idealista`:
  - attesa anche sul ramo `interstitial_datadome` in headed mode
  - rilevamento agenzia dal logo `img[alt]` dentro `a[href*="/pro/"]`
- i log piu recenti mostrano `idealista` di nuovo `healthy`, ma ancora con circa 13 annunci per pagina senza segnale agenzia
- per questo la patch ora include un secondo controllo dettaglio, limitato e prudente, che legge `Privato` / `Professionista` dalla pagina annuncio
- la priorita quindi non e piu "sbloccare i browser", ma aumentare la precisione utile del fetch e chiudere la validazione pre-push
