# OUTPUT_CURRENT.md

## Patch corrente
Precisione fetch / modalita `annunci privati`

## Stato
Implementazione completata nel workspace e review log/DOM aggiornata al 2026-03-24, incluso refinement Idealista su pagina dettaglio.

## Cosa e stato fatto
- introdotta la modalita `private_only_ads` in config/runtime/GUI
- forzata la coerenza con `extract_agency` quando la modalita e attiva
- applicato filtro locale in pipeline:
  - skip degli annunci con `agency` valorizzata
  - conteggio separato degli annunci tenuti senza segnale agenzia (`private_only_unknown`)
- hardening della log rotation Windows con `SafeRotatingFileHandler`
- disabilitato il file handler nel processo GUI per ridurre contention su `app.log`
- review log+DOM Idealista del 2026-03-24:
  - aggiunta attesa anche sul ramo `interstitial_datadome` per i run headed che si auto-risolvono
  - migliorata l'estrazione agenzia su `idealista` leggendo il brand dal logo `img[alt]` dentro `a[href*="/pro/"]`
  - aggiunto secondo controllo dettaglio, solo in `private_only`, per gli annunci `idealista` senza segnale agenzia in card
  - classificazione del publisher type dal blocco "Persona che pubblica l'annuncio" con skip se risulta `Professionista`
  - refinement successivo:
    - professionale rilevato anche dal link profilo `/pro/` nel dettaglio
    - pacing del detail-check reso piu umano con delay maggiori e pause a blocchi
    - log dedicato degli annunci `unresolved`
- aggiornati i file di contesto operativo (`HANDOFF`, `NEXT_STEPS`, `ACTIVE_PATCH`, `OUTPUT_CURRENT`, `REVIEW_CURRENT`)

## Evidence raccolta
- dai log aggiornati:
  - il falso skip `interstitial_datadome` e rientrato nei run piu recenti
  - `idealista` torna `healthy`, ma mantiene ancora molti annunci senza segnale agenzia in card
  - summary `private_only` ancora con `allowed_without_agency_signal=21`, quindi serviva un controllo piu profondo
- dall'ispezione live del DOM Idealista:
  - presenza reale della schermata "Verifica del dispositivo ..." con auto-risoluzione verso pagina completa dopo alcuni secondi
  - 17 card professionali con link `/pro/` nella pagina ispezionata
  - i vecchi selettori intercettavano solo 2 card agenzia perche molti brand erano esposti solo come `img[alt]` nel link professionale
  - nelle pagine dettaglio il publisher type e esposto in chiaro come `Privato` o `Professionista`
  - i due annunci sfuggiti segnalati dall'utente (`35159080`, `35009314`) risultano entrambi `Professionista` e hanno link `/pro/` gia presenti nel sidebar/nav

## File toccati
- `src/affitto_v2/scrapers/live_fetch.py`
- `tests/test_private_only_and_logging.py`
- `docs/context/HANDOFF.md`
- `docs/context/NEXT_STEPS.md`
- `docs/context/codex/ACTIVE_PATCH.md`
- `docs/context/codex/OUTPUT_CURRENT.md`
- `docs/context/codex/REVIEW_CURRENT.md`

## Verifiche eseguite
- `python -m py_compile src/affitto_v2/scrapers/live_fetch.py tests/test_private_only_and_logging.py`
- `python -m unittest tests.test_private_only_and_logging -v`
- `python run.py validate-config`
- `python run.py doctor`
- ispezione live via browser su:
  - ricerca `idealista`
  - dettaglio annuncio `idealista` privato
  - dettaglio annuncio `idealista` professionale
  - dettaglio degli annunci sfuggiti `35159080` e `35009314`

## Limiti residui
- il ramo `interstitial_datadome` resta prudente: se la verifica non si pulisce entro la finestra di assestamento, il fetch viene comunque chiuso come bloccato
- il secondo controllo dettaglio Idealista e limitato da cap e si interrompe se emerge una challenge, quindi non garantisce riclassificazione completa in tutti i run
- l'impatto anti-bot delle aperture dettaglio non mostra regressioni nei log disponibili, ma va ancora validato con qualche run VM in piu dopo il nuovo pacing conservativo
- serve nuova validazione VM/log reali prima del push GitHub finale
