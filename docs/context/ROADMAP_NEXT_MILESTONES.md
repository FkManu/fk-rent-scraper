# ROADMAP_NEXT_MILESTONES.md

## Scopo
Questo file definisce le prossime milestone operative del progetto `affitto` partendo dalla baseline viva `2.1_stable`.

L'obiettivo non e ancora la vendita diretta.
L'obiettivo immediato e portare il progetto da **baseline stabile** a **base tecnicamente affidabile, supportabile e quindi preparabile alla vendibilita**.

## Premessa importante
Il progetto opera in una **zona grigia tecnica e operativa** perche il valore centrale dipende da scraping live, resilienza ai cambiamenti dei siti e gestione prudente dei segnali di blocco/challenge.

Per questo motivo:
- non ha senso inseguire feature cosmetiche troppo presto
- l'**autohealing pragmatico** e un asse centrale del prodotto
- l'affidabilita percepita deve essere costruita con:
  - policy conservative
  - stato osservabile
  - recovery leggibile
  - support tooling

---

## Stato di partenza sintetico
La baseline `2.1_stable` oggi offre gia:
- GUI bundle-oriented utilizzabile su Windows
- config validation strutturata
- SQLite con dedup / retention / blacklist
- notifiche Telegram ed Email
- sender profiles cifrati con DPAPI
- live fetch reale su Idealista e Immobiliare
- site guard pragmatico con cooldown/jitter/rotation
- drift detection minima e artifact diagnostici

## Nota stato 2026-03-24
Le prime due milestone operative sono sostanzialmente gia percorse nella baseline locale:
- browser/site guard piu osservabile e adattivo per sito
- modalita `annunci privati` + hardening log rotation gia introdotti

Il focus immediato non e aprire nuova architettura, ma:
- validare gli ultimi fix `idealista`
- misurare meglio la precisione fetch reale
- chiudere il giro pre-push verso la repo GitHub privata

## Nota stato 2026-03-25
I test VM piu lunghi hanno fatto emergere tre intoppi prioritari che hanno interrotto la roadmap lineare:
- bundle GUI Windows non avviabile per packaging Tk incompleto
- cooldown del site guard troppo opaco dopo `interstitial_datadome`, percepito come loop di protezione
- volume ancora eccessivo di aperture dettaglio in `private_only` su annunci gia noti

Questi fix sono ora entrati nella baseline locale:
- riparazione packaging GUI con runtime Tcl/Tk incluso
- probe controllata durante il cooldown interstitial e reset state piu completo
- uso dei browser reali installati con retry mirato su browser alternativo
- riuso del DB per evitare detail-check inutili in `private_only`

Di conseguenza:
- Milestone A e B sono avanzate, ma non ancora chiuse sul piano operativo
- la soglia di uscita attuale non e una nuova feature, ma una validazione VM lunga senza reset frequenti
- ogni lavoro successivo deve continuare a ridurre interazioni sospette e recovery manuali

## Idea da approfondire 2026-03-25 - Browser reale via CDP
E emersa una direzione potenzialmente utile ma da trattare con disciplina: una modalita opzionale che si colleghi a un browser reale gia aperto tramite CDP (`connect_over_cdp`), invece di lanciare sempre un browser Playwright gestito.

L'idea e sensata soprattutto per:
- bootstrap manuale di challenge/verifica dispositivo/login/2FA
- sessioni gia calde e umane su `idealista`
- recovery assistita quando il problema e il launch/profile piu che il parser

Ma non deve diventare default perche:
- richiede preparazione manuale del browser
- aumenta la dipendenza dallo stato del browser dell'utente
- riduce la fedelta/controllabilita rispetto al protocollo Playwright pieno
- complica cleanup, retry e supporto

La posizione di progetto quindi e:
- `managed` resta il browser mode standard
- `cdp` resta per ora solo un'idea da approfondire, non una patch attiva
- GUI non necessaria nella prima iterazione
- nessun marketing interno di questa modalita come bypass definitivo anti-bot

### Lettura manageriale
La base non e improvvisata.
Il punto delicato non e la presenza del prodotto ma la **maturita del motore live**.

In breve:
- **base buona**
- **motore delicato**
- **vendibilita futura subordinata alla resilienza reale**

---

# Principi guida delle prossime milestone

## 1. Affidabilita prima di feature nuove
Prima si riducono:
- attriti di first-run
- bisogno di reset manuale
- opacita dei failure mode
- difficolta di supporto

Solo dopo si amplia il perimetro.

## 2. Autohealing come parte del prodotto
Autohealing qui non significa bypass aggressivo.
Significa:
- capire meglio i failure mode
- reagire in modo coerente
- fermarsi quando serve
- recuperare quando possibile
- spiegare lo stato all'utente

## 3. Osservabilita prima della narrativa commerciale
Prima di parlare seriamente di pacchetti/offerta, il sistema deve riuscire a dire bene:
- cosa e successo
- dove
- con che severita
- se e in recovery
- se richiede intervento umano

## 4. Scope piccoli e verificabili
Ogni patch deve essere:
- delimitata
- verificabile
- documentabile
- orientata a problemi reali emersi in test VM / uso bundle / scraping live

---

# Milestone A - First-Run Reliability

## Obiettivo
Rendere il primo utilizzo su PC/VM/runtime vergini piu lineare e meno fragile, soprattutto sul caso Idealista.

## Perche viene prima
Perche il primo impatto e una soglia critica sia tecnica sia commerciale.
Se il prodotto richiede conoscenza tacita o reset manuali come procedura standard, l'affidabilita percepita crolla subito.

## Problemi da chiudere
- anomalia primo tentativo Idealista in VM
- dipendenza pratica da `Reset Site Guard` al primo avvio
- initial state del guard troppo poco esplicito
- log first-run non ancora abbastanza leggibili
- bundle GUI realmente avviabile senza appoggiarsi all'ambiente Python locale

## Risultato atteso
Su runtime nuovo il prodotto deve:
- partire pulito
- eseguire un `Run Once` comprensibile
- trattare meglio il warmup iniziale
- ridurre o eliminare la necessita di reset manuale come passaggio normale

## Deliverable attesi
- warmup / initial-state refinement del site guard
- log first-run piu parlanti
- feedback GUI piu chiaro sullo stato iniziale
- verifica su VM/PC pulito
- bundle GUI realmente avviabile su Windows senza dipendenze Python esterne

## Criteri di uscita
- primo run su VM pulita spiegabile e ripetibile
- `Reset Site Guard` resta strumento di emergenza, non procedura standard
- Idealista non entra subito in gestione troppo punitiva su contesto vergine

---

# Milestone B - Observable Autohealing

## Obiettivo
Portare il sistema da anti-block reattivo a resilienza piu osservabile e adattiva.

## Focus
Non piu solo:
- cooldown
- jitter
- reset
- retry prudente

Ma anche:
- stato per sito
- tassonomia failure piu leggibile
- recovery esplicita
- diagnosi supportabile

## Problemi da chiudere
- difficolta nel capire rapidamente perche un sito e `degraded` / `blocked`
- differenza poco visibile tra problema temporaneo, challenge, parser drift, lentezza, errore rete
- supporto ancora troppo dipendente da log grezzi

## Risultato atteso
Il sistema deve riuscire a mostrare almeno in forma sintetica:
- ultimo outcome per sito
- streak / cooldown
- ultimo successo
- ultimo blocco o suspect rilevante
- quality estrazione
- stato recovery / warmup / stable / degraded

## Deliverable attesi
- tassonomia outcome piu chiara
- stato sintetico per sito nel runtime o GUI
- policy piu leggibili per suspect / blocked / degraded
- affinita browser per sito piu osservabile e adattiva
- artifact diagnostici piu mirati
- distinzione pratica piu chiara tra `Run Once` e `Ciclo automatico`
- gestione meno cieca del cooldown dopo interstitial, con possibilita di probe controllata
- eventuale modalita opzionale di recovery assistita tramite browser reale via CDP, se e solo se resta separata dal path standard

## Criteri di uscita
- un problema live si capisce piu velocemente senza dover leggere tutto `app.log`
- il supporto puo ragionare per stati e codici, non solo per intuito
- la recovery diventa osservabile, non implicita

---

# Milestone C - Core Hardening & Testability

## Obiettivo
Industrializzare il motore live per ridurre il rischio di patch stratificate e regressioni difficili da controllare.

## Focus tecnico
Il file `scrapers/live_fetch.py` oggi e potente ma troppo centrale.
Va progressivamente spezzato e reso piu testabile.

## Problemi da chiudere
- modulo troppo grande e con troppe responsabilita
- logica guard / parser / anti-bot / browser strategy troppo concentrata
- assenza di test strutturati sul core delicato

## Risultato atteso
Una codebase in cui i cambiamenti al motore live siano:
- piu localizzati
- piu testabili
- meno rischiosi

## Deliverable attesi
- separazione graduale in sottocomponenti
  - browser/session strategy
  - guard state machine
  - anti-bot detection
  - extractor per sito
  - drift diagnostics
- test unitari su guard logic e drift rules
- fixture/snapshot HTML per validare parser senza fetch live
- contratti interni piu chiari per outcome e metriche

## Criteri di uscita
- patch sul core live con superficie di impatto piu contenuta
- regressioni rilevabili prima del test manuale live
- meno dipendenza da debugging reattivo

---

# Milestone D - Vendible Ops Base

## Obiettivo
Preparare la base operativa che rendera possibile la futura proposta commerciale, senza ancora spostare il focus sul marketing.

## Focus
Qui non si vende ancora davvero.
Si costruisce il minimo necessario per poter dire in futuro:
- il prodotto si installa
- il prodotto si capisce
- il prodotto si supporta
- il prodotto ha un perimetro chiaro

## Deliverable attesi
- onboarding guidato piu lineare
- docs di installazione e supporto per PC / VM / VPS
- checklist operativa first-run
- policy di supporto minima
- confini chiari tra:
  - self-hosted
  - setup assistito
  - managed VPS

## Criteri di uscita
- esiste un flusso standard ripetibile per mettere in funzione il prodotto
- il supporto non dipende solo dalla memoria informale del progetto
- la futura offerta commerciale puo poggiare su fondamenta tecniche piu serie

---

# Ordine di esecuzione raccomandato
1. **Milestone A - First-Run Reliability**
2. **Milestone B - Observable Autohealing**
3. **Milestone C - Core Hardening & Testability**
4. **Milestone D - Vendible Ops Base**

## Nota
L'ordine non e casuale.
La futura vendibilita dipende prima dalla riduzione dell'attrito reale e dall'affidabilita percepita del motore live.

---

# Anti-chaos rules per questa fase
- non aprire nuove feature di prodotto che non migliorano affidabilita / supportabilita
- non trattare il reset manuale come soluzione definitiva
- non gonfiare la GUI con troppi controlli avanzati prima di avere stati migliori
- non stratificare altra logica critica in `live_fetch.py` senza criterio
- non vendere narrativamente il progetto prima di aver reso piu leggibile il suo comportamento operativo
- non aumentare le aperture dettaglio `private_only` se prima non si dimostra che il DB puo assorbire i casi gia noti
- non trasformare il CDP in nuovo default senza prima dimostrare che il costo di supporto e lifecycle resta sotto controllo

---

# Prossimi task gia prioritizzati
Task tecnici pronti per Codex:
1. `docs/context/codex/TASK_FIRST_RUN_RELIABILITY.md`
2. `docs/context/codex/TASK_OBSERVABLE_AUTOHEALING.md`

Questi due task corrispondono alle prime due patch utili della roadmap.
