# ACTIVE_PATCH.md

## Patch corrente
Precisione fetch / modalita `annunci privati`

## Obiettivo
Ridurre i falsi positivi "solo privati" e aumentare la precisione utile del fetch, soprattutto su `idealista`, senza introdurre bypass aggressivi.

## Contesto
- la patch browser/site guard precedente ha spostato il collo di bottiglia dalla scelta browser alla precisione del fetch
- il filtro URL "privati" lato sito non basta: i risultati possono comunque contenere annunci agenzia
- la modalita `annunci privati` e gia stata introdotta in GUI/runtime/pipeline
- nella review log+DOM del 2026-03-24 sono emersi due problemi specifici su `idealista`:
  - alcuni run headed venivano chiusi troppo presto come `interstitial_datadome`, anche quando la pagina si auto-sbloccava dopo pochi secondi
  - molte card agenzia esponevano il brand solo come `img[alt]` dentro `a[href*="/pro/"]`, quindi i vecchi selettori perdevano gran parte dei casi

## Scope
- mantenere separati:
  - filtro URL lato sito
  - filtro locale lato parser/pipeline
- migliorare la pazienza del ramo `interstitial_datadome` nei run headed
- aumentare la copertura dei selettori agenzia su `idealista`
- aggiungere un secondo controllo dettaglio su `idealista` in modalita `private_only`, solo per gli annunci ancora senza segnale agenzia
- rendere il secondo controllo dettaglio piu robusto e meno aggressivo sul piano anti-bot
- lasciare log e metriche leggibili per misurare `excluded_agency` e `allowed_without_agency_signal`

## Non-scope
- bypass aggressivi anti-bot
- retry cross-browser pesanti sul singolo URL
- refactor ampio di tutto `live_fetch.py`
- nuove feature commerciali o UX non collegate al problema reale

## File principali coinvolti
- `src/affitto_v2/scrapers/live_fetch.py`
- `src/affitto_v2/pipeline.py`
- `src/affitto_v2/gui_app.py`
- `src/affitto_v2/main.py`
- `src/affitto_v2/logging_live.py`
- `tests/test_private_only_and_logging.py`

## Done quando
- `idealista` non viene piu chiuso troppo presto nei transient headed che si auto-risolvono
- gli skip agenzia su `idealista` aumentano in modo credibile rispetto ai log pre-fix
- gli annunci Idealista senza segnale agenzia in card vengono riclassificati meglio tramite il campo `Privato` / `Professionista` nel dettaglio
- i professionali Idealista con profilo `/pro/` nel dettaglio non sfuggono piu al ricontrollo locale
- il summary `private_only` resta leggibile e misurabile
- la log rotation Windows non produce piu rumore operativo nel caso GUI + subprocess

## Stato attuale
Implementazione completata nel workspace; in attesa di nuova validazione VM/log reali dopo il refinement Idealista su pagina dettaglio.

## Residui emersi
- `idealista` puo restare `partial_success_degraded` anche senza falso skip
- la modalita `annunci privati` resta best-effort: anche dopo il controllo dettaglio possono restare annunci `private_only_unknown`
- prima del push su GitHub serve pulizia finale del working tree e selezione accurata dei file da versionare
