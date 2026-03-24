# REVIEW_CURRENT.md

## Patch corrente
Precisione fetch / modalita `annunci privati`

## Stato review
Verde tecnico nel workspace. Validazione operativa VM ancora da ripetere dopo il refinement Idealista del 2026-03-24.

## Findings chiusi
- falso skip Idealista:
  - il ramo `interstitial_datadome` veniva chiuso subito senza grace period, pur in presenza di pagine headed che si auto-risolvevano dopo pochi secondi
- sottorilevamento agenzie Idealista:
  - molte card professionali avevano il brand solo nel logo `img[alt]` dentro `a[href*="/pro/"]`
  - i vecchi selettori intercettavano quindi quasi solo i casi con alt contenente `Agenzia` o `Immobiliare`
- annunci Idealista "subdoli" ancora passati come privati:
  - nei log piu recenti `idealista` torna `healthy`, ma il summary `private_only` resta con `allowed_without_agency_signal=21`
  - il DOM dettaglio espone pero il publisher type come `Privato` o `Professionista`, quindi il filtro solo-card non era piu sufficiente
- due annunci professionali ancora sfuggiti al secondo controllo:
  - `35159080` e `35009314` mostrano chiaramente `Professionista` nel dettaglio
  - entrambi espongono anche un link `/pro/` nel sidebar/nav, segnale piu robusto del solo parsing del body text

## Verifiche eseguite
- `python -m py_compile src/affitto_v2/scrapers/live_fetch.py tests/test_private_only_and_logging.py` -> OK
- `python -m unittest tests.test_private_only_and_logging -v` -> OK
- `python run.py validate-config` -> OK
- `python run.py doctor` -> OK
- review log `docs/tmp_logs_2.md` -> coerente con anti-bot rientrato ma agency detection ancora incompleta su `idealista`
- ispezione DOM live:
  - schermata "Verifica del dispositivo ..." osservata su `idealista`
  - pagina completa caricata dopo attesa di alcuni secondi
  - diversi annunci agenzia esposti tramite link `/pro/` con nome nel logo `img[alt]`
  - pagina dettaglio annuncio privato con label `Privato`
  - pagina dettaglio annuncio professionale con label `Professionista`
  - verifica live dei due annunci sfuggiti `35159080` e `35009314` -> entrambi `Professionista` con link `/pro/`

## Focus della review
- non era emerso un nuovo `hard_block` reale su `idealista`
- il problema era una combinazione di:
  - classificazione troppo aggressiva dei transient verification pages
  - qualita insufficiente dei selettori agenzia sul DOM attuale di `idealista`
  - assenza di un controllo di conferma sul dettaglio per gli annunci ancora "unknown" in `private_only`
- sul refinement detail-check:
  - il solo body parsing non era sufficiente su tutti i professionali
  - un segnale DOM piu forte e immediato e la presenza del link profilo `/pro/`
  - il ritmo originario del detail-check era probabilmente troppo serrato per una validazione prudente lato anti-bot
- `immobiliare` resta il benchmark piu sano:
  - DOM piu stabile
  - hook agenzia piu forti
  - filtro `private_only` gia efficace in modo credibile

## Esito
- Patch approvata nel workspace.
- Residui aperti:
  - nuova validazione VM/log reali su `idealista` per misurare il delta del controllo dettaglio
  - confermare che il pacing piu lento non peggiori challenge / interstitial
  - possibile telemetria aggiuntiva sugli annunci `private_only_unknown` residui
  - pulizia pre-push verso la repo GitHub privata
