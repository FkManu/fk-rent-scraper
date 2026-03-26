# Risk scoring silenzioso e best practice antibot recenti

Ti lascio la versione utile, non la versione da seminario con 80 slide e zero sostanza.

## Cosa significa davvero **risk scoring silenzioso**

Nei sistemi antibot recenti, il CAPTCHA non è più il fulcro. È diventato uno **step-up challenge** usato solo quando il punteggio di rischio non è abbastanza chiaro. Il grosso del lavoro viene fatto **prima**, in modo invisibile, combinando segnali lato client, lato rete e lato sessione. reCAPTCHA v3 è l’esempio canonico: restituisce un **punteggio** per ogni richiesta senza interrompere l’utente, usa il concetto di **action** per dare contesto al rischio e Google raccomanda di distribuirlo su più pagine proprio per cogliere pattern cross-page. Cloudflare documenta la stessa filosofia con **JavaScript detections** invisibili, scoring ML 1-99, cookie di smoothing di sessione e moduli di anomaly detection. DataDome descrive **Device Check** come una verifica automatica sul device, senza interazione utente, pensata proprio per spotting di automazione e ambienti spoofati.

In pratica, “silenzioso” vuol dire questo: il sistema non aspetta più che tu fallisca un puzzle, ma costruisce una **probabilità di automazione** usando molti segnali deboli messi insieme. Vendor diversi cambiano nomi e packaging, ma la struttura è molto simile: **heuristics**, **invisible client instrumentation**, **ML supervisionato**, **baseline/anomaly detection**, **sequenze di navigazione**, e poi una risposta graduale invece del vecchio blocco secco.

---

# I paper e le fonti più utili

## 1) **Martínez Llamas et al., 2025**
**Balancing Security and Privacy: Web Bot Detection, Privacy Challenges, and Regulatory Compliance under the GDPR and AI Act**

Questo è il paper da leggere per primo perché non vende la solita favoletta “metti ML e sei a posto”. Fa una tassonomia per **fonte dei dati**: traffico, fingerprint, biometria comportamentale; spiega l’arms race tra detection ed evasione; e soprattutto mette sul tavolo il problema che molti segnali antibot possono sconfinare nel **dato personale** o persino in aree sensibili lato GDPR/AI Act. Come mappa del campo, oggi è uno dei testi più completi. Come performance paper, invece, non è il migliore: è una **review interdisciplinare**, non un benchmark operativo.

## 2) **Jarad & Bıçakcı, 2026**
**When Handshakes Tell the Truth: Detecting Web Bad Bots via TLS Fingerprints**

Questo è il paper più interessante sul lato **protocol-level / passive scoring**. Usa fingerprint TLS/JA4 e modelli gradient boosting su JA4DB. Riporta AUC **0.998** per XGBoost, accuratezza attorno a **0.9862**, e risultati molto simili per CatBoost con F1 circa **0.9734**. Il dettaglio importante non è solo “ha metriche alte”, ma **quali feature pesano di più**: il componente **JA4_b**, poi `cipher_count`, `ext_count`, `alpn_code`, `os`, `sni_flag`, `tls_version`. Tradotto: i sistemi moderni guardano sempre di più la **forma della stretta di mano** e non solo il browser JavaScript. Limite: è fortissimo come segnale passivo, ma non basta da solo contro client che si avvicinano molto al browser reale o contro contesti dove la reputazione/session history conta più del singolo handshake.

## 3) **Iliou et al., 2021** + **See et al., 2023** + **Subash et al., 2026**
**Mouse dynamics / behavioral biometrics**

Qui c’è il filone che spiega perché il mouse “umano” è diventato così centrale. Iliou et al. mostrano che combinare **web logs** e **mouse behavioural biometrics** migliora la robustezza contro bot avanzati. See et al. spingono la cosa in modo più realistico: nel loro studio il **mouse dynamics** performa meglio dei semplici request-data, e l’addestramento beneficia anche di mouse data esterni, non solo sito-specifici. La survey 2026 di Subash et al. è fondamentale perché rimette tutti a terra: i sistemi di behavioral biometrics soffrono di **user behavior evolution**, cioè il comportamento degli utenti cambia nel tempo, quindi queste tecniche sono ottime come **layer** ma fragili come verità assoluta.

## 4) **Zhao et al., 2026**
**Non-Intrusive Graph-Based Bot Detection for E-Commerce Using Inductive Graph Neural Networks**

Questo paper è molto vicino al tuo scenario “classifieds / e-commerce / browsing repetitivo”. Propone un framework **non intrusivo** basato su **session-URL graph** e GraphSAGE, quindi niente client-side instrumentation obbligatoria. Sul loro dataset il modello batte una baseline MLP session-only con **AUC 0.9705 vs 0.9102**; in cold-start mantiene **0.9630** con un drop di appena **0.8%**, molto meglio della baseline. Il messaggio importante è architetturale: oggi una difesa seria non guarda solo la singola request, ma anche la **struttura delle visite** e come una sessione si appoggia sull’insieme di URL.

## 5) **BOTracle, 2024/2025**
**A framework for Discriminating Bots and Humans**

BOTracle è interessante perché mette insieme tre famiglie di segnali e lavora su **traffico e-commerce reale** con **40 milioni di page visits mensili**. L’abstract parla di precision, recall e AUC **98% o superiori**. La parte più utile, però, è la discussione sui feature importance: attributi statici come **browser width/height** risultano forti ma sono **facili da falsificare**; per questo gli autori concludono che i meccanismi seri devono integrare **behavioral characteristics**, più costose da emulare e meno stabili per il bot.

## 6) **Perché il settore si sposta sul silenzioso: DMTG 2024, MCA-Bench 2025, VIPER 2026**

La ragione per cui il mercato si è spostato verso scoring invisibile non è solo “UX migliore”. È anche che i CAPTCHA visibili sono sotto pressione. DMTG 2024 mostra che generatori di traiettorie mouse più realistici possono ridurre l’accuracy dei detector CAPTCHA basati sul comportamento; MCA-Bench 2025 costruisce un benchmark multimodale per misurare la robustezza dei CAPTCHA contro VLM-based attacks; VIPER 2026 mostra che anche i CAPTCHA di visual reasoning vanno trattati come bersagli modellabili, e propone Template-Space Randomization come idea difensiva. Morale: i CAPTCHA restano utili, ma sempre più spesso vengono spostati **a valle** del rischio, non messi come porta d’ingresso universale.

---

# Best practice antibot 2025-2026

## 1) **Layering, non monocultura**
La best practice più chiara è usare più motori insieme. Cloudflare espone esplicitamente un layer di **heuristics**, uno di **JavaScript detections**, uno di **ML supervisionato** e uno di **anomaly detection**. F5 parla di rich client-side signals, behavioral analytics, device analysis e code protection. Quindi il pattern vincente non è “scegli il segnale giusto”, ma “combina segnali diversi che falliscono in modi diversi”.

## 2) **Score continuo, non verdict binario**
Le piattaforme moderne ragionano in **punteggi**, non in sì/no. reCAPTCHA v3 usa score per request e contextual actions; Cloudflare assegna bot score **1-99** e usa il cookie `__cf_bm` per “smussare” il punteggio lungo la sessione e ridurre falsi positivi. Questa è una best practice forte perché evita di trattare un singolo evento ambiguo come colpa capitale.

## 3) **Session e sequence awareness**
Guardare singole request è roba da 2018. Cloudflare Sequence Rules usa cookie per tracciare **ordine delle operazioni** e **tempo trascorso** tra endpoint, così puoi modellare sequenze valide o invalide. Per siti con funnel ripetitivi, come ricerca → lista → dettaglio → contatto, questa è una best practice molto più forte del mero rate limit.

## 4) **Client-side instrumentation, ma preferibilmente first-party**
DataDome dice chiaramente che il JS Tag è essenziale perché raccoglie segnali, gestisce sessione e challenge; raccomanda il setup **first-party** per ridurre blocchi da adblocker/privacy filters e, nel caso CloudFront, arriva a dire che il first-party è necessario per rilevazione affidabile.

## 5) **Challenge invisibili prima del CAPTCHA**
DataDome Device Check è l’esempio più esplicito: verifica automatica sul device, senza user interaction, utile per bot sofisticati già dalle prime richieste e per contesti sospetti dove non hai ancora evidenza sufficiente per bloccare o sfidare con CAPTCHA. Cloudflare JSD ha la stessa logica di fondo: raccogli segnali invisibili, poi decidi se lasciar passare, challengiare o inoltrare ad altri motori.

## 6) **Passive backend telemetry**
La best practice più elegante è usare segnali che l’attaccante controlla poco o male: TLS fingerprints, server logs, grafi sessione-URL. Il paper JA4 2026 e il paper GraphSAGE 2026 vanno esattamente in questa direzione. Il vantaggio è doppio: meno frizione per l’utente e più resistenza contro chi sa imitare un browser a livello superficiale.

## 7) **Response ladder, non solo block**
DataDome documenta una scala di risposte: `Allow`, `Timeboxing`, `Rate Limiting`, `Captcha`, `Block`, e perfino `Custom`, dove il backend può decidere logiche come **obfuscate some data** o servire contenuto alternativo. Cloudflare consiglia allo stesso modo di usare built-in bot settings per distinguere tra definitely automated, likely automated e verified bots.

## 8) **Allow-list dei bot legittimi**
Un sistema serio deve anche evitare di spararsi sui crawler leciti. Cloudflare distingue i **verified bots** e raccomanda policy separate per loro.

## 9) **Privacy by design**
La review 2025 insiste molto su PETs, data minimization, basi giuridiche e rischi connessi ai segnali biometrici/comportamentali. Cloudflare, dal lato prodotto, insiste sul fatto che JSD non raccoglie PII e che `__cf_bm` è site-specific, cifrato e non usato per tracking cross-site.

---

# Cosa inferirei per portali come Idealista / Immobiliare

Non ho una fonte primaria pubblica che mi permetta di dire “usano sicuramente vendor X”, quindi non invento il solito folklore da gente che ha visto un cookie e si sente forense. Quello che **è plausibile**, guardando lo stato dell’arte e i pattern documentati dai vendor, è una combinazione di:

- scoring per request + smoothing di sessione;
- client-side JS invisibile o device checks;
- controlli su **ordine e timing** delle operazioni;
- segnali passivi di rete / fingerprint di client;
- risposta graduale su endpoint sensibili, specialmente ricerca, pagine lista, export-like patterns, e funnel ripetitivi.

Per un portale immobiliare, poi, i paper e-commerce sono particolarmente rilevanti: session-URL graph, sequence modeling, differenza tra feature statiche facili da falsificare e behavioral signals più costosi da emulare. Quindi sì, se il tuo browser “reale” passa e quello “gestito” viene segnato, il motivo più probabile non è una singola magia anti-Playwright. È che il punteggio nasce dalla **coerenza complessiva della sessione**, non da un solo bit isolato.

---

# Ordine di lettura consigliato

1. **Martínez Llamas et al. 2025** per la tassonomia completa e il lato GDPR/AI Act.  
2. **Jarad & Bıçakcı 2026** per capire il peso del livello TLS/JA4.  
3. **Iliou 2021 + See 2023 + survey 2026** per behavioral biometrics senza romanticismi.  
4. **Zhao et al. 2026** per i modelli passivi session-URL da e-commerce/classifieds.  
5. **BOTracle 2024/2025** per il punto “static features aiutano, ma il futuro è behavior-heavy”.  
6. **Vendor docs** di Cloudflare, DataDome, F5 per vedere come queste idee diventano prodotto reale.

Il passo utile successivo è trasformare questa letteratura in una **griglia comparativa di segnali**: rete, browser, sessione, sequenza, comportamento, risposta. Quella sì che serve davvero per capire contro cosa stai sbattendo la testa, invece di inseguire l’ennesima flag “stealth” come un criceto con Wi‑Fi.

---

# Griglia dei segnali antibot moderni

Perfetto. Ti costruisco una **griglia dei segnali** fatta bene, cioè utile per capire **come ragionano i sistemi antibot 2025-2026**, non la solita lista “IP, user-agent, cookie, fine” che andava bene quando ancora Internet era un posto meno isterico.

## Come leggere la griglia

Due premesse importanti:

1. **Non esiste quasi mai un singolo segnale decisivo.** I sistemi moderni fanno **risk scoring composito**: tanti segnali deboli, uniti in un punteggio o in una classificazione multilivello. Cloudflare parla esplicitamente di motori diversi, bot score 1-99, smoothing di sessione e sequence rules; reCAPTCHA v3 fa scoring per interazione e per `action`; DataDome usa JS tag, Device Check e una scala di risposte invece del solo CAPTCHA.

2. **Il “browser reale” migliora soprattutto i segnali client-side e di continuità**, ma aiuta molto meno sui segnali di rete, reputazione, pattern temporali e struttura della navigazione. Questo è il punto che spesso viene capito male da chi pensa che “non-headless” basti a diventare un fantasma. Non basta.

---

## 1) **Segnali di origine e traffico di rete**

| Voce | Cosa include | Come viene raccolto | Peso oggi | Perché conta | Limiti / falsi positivi | Effetto di “browser reale” |
|---|---|---|---|---|---|---|
| IP / ASN / geolocazione / tipo rete | IP, ISP, ASN, geolocazione approssimativa, data center vs residential/mobile, frequenza IP | Server logs, reverse intelligence, reputazione rete | **Alto** | È il primo filtro passivo e costa poco. La tassonomia 2025 lo considera uno dei marker più diffusi e immediati. | NAT, carrier-grade NAT, proxy aziendali, roaming, utenti legittimi su IP “sporchi” | **Basso**. Un browser reale non cambia quasi nulla se l’origine è già sospetta. |
| Pattern di traffico | burstiness, cadence, concurrency, rapporto richieste/tempo | Server-side timing e log aggregation | **Alto** | I sistemi recenti non guardano solo “chi sei”, ma **come arrivi** e con che regolarità. Cloudflare usa anche sequenze e timing tra endpoint. | Monitoring legittimi e power users possono sembrare aggressivi | **Basso-Medio**. Il browser reale non corregge un pattern meccanico. |

### Sintesi
Questa famiglia è fortissima perché è **passiva** e non richiede JS. È anche quella dove il browser reale serve meno. Se il tuo traffico ha un odore strano a livello rete, il front-end “umano” conta relativamente poco.

---

## 2) **Segnali HTTP e coerenza protocollare applicativa**

| Voce | Cosa include | Come viene raccolto | Peso oggi | Perché conta | Limiti / falsi positivi | Effetto di “browser reale” |
|---|---|---|---|---|---|---|
| Header profile | `User-Agent`, `Accept`, `Accept-Language`, `Referer`, cookies, content-type, content-length, timestamps | HTTP request/response logs | **Medio-Alto** | La review 2025 indica header, cookie, referer, lingua e timestamp come input molto comuni nel detection layer. | Gli header possono essere facilmente falsificati se presi isolatamente | **Medio**. Un browser reale tende a produrre combinazioni più coerenti, ma da sole non bastano. |
| Header consistency nel tempo | stabilità e compatibilità tra richieste successive | Session analytics | **Alto** | I sistemi moderni valutano la **coerenza cross-request**, non solo il singolo header snapshot. Questo si collega bene con cookie di scoring e session smoothing. | Cambi rete/browser/dispositivo veri possono abbassare la fiducia | **Medio-Alto** se usi sempre la stessa sessione reale. |

### Sintesi
Questi segnali sono meno “glamour” del fingerprinting, ma restano fondamentali. La differenza è che ormai **valgono soprattutto come segnali di coerenza**, non come prova unica.

---

## 3) **Fingerprint TLS / JA3 / JA4 e telemetria di trasporto**

| Voce | Cosa include | Come viene raccolto | Peso oggi | Perché conta | Limiti / falsi positivi | Effetto di “browser reale” |
|---|---|---|---|---|---|---|
| TLS client fingerprint | versione TLS, ALPN, SNI, struttura ClientHello, suite, estensioni | Passive network telemetry | **Molto alto** | JA4 è stato introdotto come evoluzione più robusta di JA3, resistente alla randomizzazione delle estensioni e più adatto ai browser moderni. Cloudflare lo integra nei propri sistemi. | Proxy/CDN intermedi e middleboxes possono alterare parte del quadro | **Medio-Alto**. Un browser reale tende ad avere una handshake più “nativa”, ma non risolve reputazione IP o pattern di richiesta. |
| Feature TLS strutturali | `ja4_b`, `cipher_count`, `ext_count`, `alpn_code`, `tls_version`, `sni_flag` | ML su passive fingerprints | **Molto alto** | Il paper 2026 su TLS bad-bot detection riporta AUC ~0.998 e accuracy ~0.986; le feature più influenti sono `ja4_b`, `cipher_count` ed `ext_count`, seguite da ALPN, OS, SNI e TLS version. | Dipende dal dataset e dalla varietà dei client benigni reali | **Medio-Alto**. Qui il browser reale può aiutare più di quanto aiuti sugli header. |

### Sintesi
Questa è una delle aree più importanti del 2026: **telemetria passiva di basso livello** che non ha bisogno del CAPTCHA e spesso nemmeno del JS. È una delle ragioni per cui “ho messo lo user-agent di Chrome” ormai fa sorridere amaramente.

---

## 4) **Runtime JavaScript e segnali del browser in pagina**

| Voce | Cosa include | Come viene raccolto | Peso oggi | Perché conta | Limiti / falsi positivi | Effetto di “browser reale” |
|---|---|---|---|---|---|---|
| JS environment checks | headless artifacts, API availability, DOM/runtime consistency, malicious fingerprints | Script invisibili lato client | **Molto alto** su siti web tradizionali | Cloudflare JSD dichiara che gira su **ogni richiesta HTML/page view**, inietta JS invisibile, e serve proprio a identificare headless browsers e altri fingerprint malevoli. | Ad blocker, CSP, privacy tools e browser particolari possono degradare il segnale | **Molto alto**. Qui il browser reale fa davvero differenza. |
| Context accumulation | esecuzione su più pagine, background pages, `action` context | Script + backend verification | **Alto** | reCAPTCHA v3 funziona a punteggio, usa `actions`, e raccomanda di essere eseguito anche in background per avere più contesto. | Se usato male lato sito può generare score rumorosi | **Medio-Alto** se la sessione reale accumula contesto autentico. |

### Sintesi
Qui il tuo ragionamento “il browser installato passa più spesso del gestito” è perfettamente coerente con lo stato dell’arte. I sistemi moderni osservano il **runtime vero**, non solo il pacchetto HTTP.

---

## 5) **Fingerprint del device e verifica silenziosa del contesto**

| Voce | Cosa include | Come viene raccolto | Peso oggi | Perché conta | Limiti / falsi positivi | Effetto di “browser reale” |
|---|---|---|---|---|---|---|
| Device / environment proof | segnali del device, ambiente di esecuzione, spoofed env, programmatic access | JS client-side + verifica server-side | **Molto alto** | DataDome Device Check gira sul device senza interazione utente, serve a rilevare framework di automazione, ambienti spoofati o accesso programmatico. | Browser/OS rari o setup aziendali bloccati possono risultare rumorosi | **Molto alto**. Un browser reale migliora parecchio questa famiglia. |
| Fingerprinting non comportamentale | centinaia di segnali, checkpoint ambientali, challenge automatiche | client-side fingerprinting | **Alto** | DataDome dice esplicitamente che Device Check raccoglie **centinaia di segnali**, usa fingerprinting client/device e challenge automatiche, e non si basa su behavioral models in quella fase. | Il fingerprinting ha costi privacy/regolatori più alti | **Molto alto**. |

### Sintesi
Questa è la forma moderna del “CAPTCHA invisibile”, solo molto meno stupida e molto più continua. Non ti ferma con un puzzle, ti pesa. E poi decide se vale la pena farti vedere qualcosa.

---

## 6) **Session continuity, cookie di rischio e memoria di stato**

| Voce | Cosa include | Come viene raccolto | Peso oggi | Perché conta | Limiti / falsi positivi | Effetto di “browser reale” |
|---|---|---|---|---|---|---|
| Risk cookies / score smoothing | cookie di bot management, session identifiers, request pattern memory | first-party / protection cookies | **Molto alto** | Cloudflare usa `__cf_bm` per “smooth out” il bot score e ridurre falsi positivi; il cookie contiene dati legati al calcolo del bot score e può includere un session identifier con anomaly detection. È per-sito, cifrato e scade dopo 30 minuti di inattività. | Reset di sessione, pulizia cookie, rotazione aggressiva spezzano la continuità anche per utenti legittimi | **Molto alto**. Qui il browser reale persistente aiuta tantissimo. |
| Verification memory | remember decision / reduce repeated checks | session memory del vendor | **Alto** | DataDome dichiara che una volta verificato un utente legittimo con Device Check, il risultato viene ricordato e il check non viene ripetuto continuamente. | Session reset o ambienti instabili cancellano il beneficio | **Molto alto**. |

### Sintesi
Questa è una delle differenze più concrete tra **browser gestito rilanciato** e **browser reale persistente**: il secondo accumula **storia utile**. Il primo spesso si presenta come uno sconosciuto cronico. E gli sconosciuti cronici, online, non piacciono a nessuno.

---

## 7) **Sequenze, ordine delle pagine e timing tra azioni**

| Voce | Cosa include | Come viene raccolto | Peso oggi | Perché conta | Limiti / falsi positivi | Effetto di “browser reale” |
|---|---|---|---|---|---|---|
| Sequence rules | ordine richieste, tempo tra endpoint, sequenze valide/invalidhe | cookies + rule engine | **Molto alto** in e-commerce/classifieds | Cloudflare Sequence Rules traccia **ordine** e **tempo tra le richieste** tramite sequence cookies. Questo è esattamente il tipo di segnale utile su funnel ripetitivi. | Power users o strumenti assistivi possono avere pattern anomali ma legittimi | **Medio**. Il browser reale aiuta meno del comportamento reale. |
| Navigation graph / session-url graph | relazione tra sessione e URL, topologia delle visite, comportamento “feature-normal” ma strutturalmente anomalo | backend logs + graph ML | **Molto alto** | Il paper 2026 su e-commerce propone un modello GraphSAGE su session–URL graph, non intrusivo, robusto anche a mild perturbations e utile contro automazione “feature-normal”. | Richiede buona telemetria backend e labeling affidabile | **Basso-Medio**. Un browser reale non ti salva se la struttura della navigazione resta meccanica. |

### Sintesi
Per portali tipo classifieds, questa è probabilmente una delle famiglie più pesanti. Non conta solo **come appare** il client, ma **come si muove dentro il catalogo**. Se una sessione tocca gli URL nel modo “sbagliato”, la faccia pulita del browser conta meno.

---

## 8) **Biometria comportamentale: mouse, tastiera, micro-dinamiche**

| Voce | Cosa include | Come viene raccolto | Peso oggi | Perché conta | Limiti / falsi positivi | Effetto di “browser reale” |
|---|---|---|---|---|---|---|
| Mouse dynamics | traiettorie, velocità, accelerazione, micro-pause, curvature, entropy del movimento | event listeners client-side | **Medio-Alto**, ma selettivo | Il lavoro ACM 2021 mostra che combinare web logs e movimenti mouse migliora efficacia e robustezza contro bot avanzati; lavori successivi del 2024 continuano a usare mouse dynamics e communication metadata. | Privacy, accessibilità, touch devices, trackpad, differenze individuali, drift nel tempo | **Basso** se il browser reale non ha interazione umana reale; **alto** solo se c’è davvero un umano. |
| Keystroke / interaction biometrics | ritmo, dwell time, flight time, sequenze input | client-side instrumentation | **Medio** | È un layer utile per login, search box, contact funnel e altre azioni ad alta intenzione. La ricerca recente continua ad affiancarlo ai segnali mouse. | Molto sensibile a contesto, lingua, device e utente | **Basso** senza interazione reale. |

### Sintesi
Questa famiglia è potente ma più costosa, più sensibile alla privacy e meno universale. È fortissima in alcuni funnel, non necessariamente ovunque. E soprattutto: **browser reale** non equivale a **comportamento umano reale**.

---

## 9) **Heuristics, ML supervisionato e anomaly detection**

| Voce | Cosa include | Come viene raccolto | Peso oggi | Perché conta | Limiti / falsi positivi | Effetto di “browser reale” |
|---|---|---|---|---|---|---|
| Heuristics | firme note, regole, fingerprint malevoli, pattern noti | rules engine | **Alto** | Cloudflare dichiara un motore heuristics che processa tutte le richieste e le confronta con un database crescente di malicious fingerprints. | Rigido da solo, aggirabile se isolato | **Medio**. |
| Supervised ML | score probabilistico, classi human/bot | backend ML + client/server features | **Dominante** | Cloudflare dice che il motore ML copre la maggioranza delle detection e produce il Bot Score 1-99; reCAPTCHA v3 produce un risk score per request; F5 parla esplicitamente di ML e behavioral analytics. | Dataset drift, labeling, bias, cold-start | **Indiretto**. Il browser reale migliora alcune feature, ma il modello pesa il quadro complessivo. |
| Anomaly detection | deviazioni dalla baseline normale del sito/sessione | modelli statistical / unsupervised | **Alto** | Cloudflare lo espone come motore separato per Enterprise; è il layer che aiuta quando l’automazione è “nuova” ma comunque strana rispetto alla baseline. | Nuove campagne umane o eventi insoliti possono assomigliare a anomalie | **Basso-Medio**. |

### Sintesi
Qui si vede bene la filosofia 2026: non c’è “il segnale”. C’è il **meta-layer** che fonde tutto. È il motivo per cui cambiare un singolo dettaglio raramente cambia il destino di una sessione già sospetta.

---

## 10) **Ladder di risposta: allow, rate limit, invisible check, CAPTCHA, block**

Questa non è una famiglia di segnali, ma è il pezzo che spiega **come i segnali vengono tradotti in azione**.

| Livello | Cosa significa | Esempi documentati |
|---|---|---|
| Allow | rischio basso o accettabile | Cloudflare bot scores alti, DataDome `Allow` |
| Soft shaping / smoothing | memoria di sessione, riduzione falsi positivi | `__cf_bm`, verification memory |
| Rate limiting / timeboxing | contenimento graduale | DataDome `Rate Limiting` e `Timeboxing` |
| Invisible client-side check | controlli silenziosi aggiuntivi | DataDome Device Check, Cloudflare JSD, reCAPTCHA v3 score-based flows |
| CAPTCHA / explicit challenge | step-up quando l’evidenza è ambigua o il contesto è sensibile | DataDome: Device Check può precedere un CAPTCHA; reCAPTCHA v3 lascia l’azione al sito |
| Block | rischio alto / policy violata | motori vendor e custom rules |

### Sintesi
Il CAPTCHA, ormai, è spesso solo un **ramo dell’albero decisionale**, non il centro dell’architettura. È per questo che puoi essere segnato o rallentato **prima** di vedere una challenge visibile.

---

# Cosa pesa di più oggi, in pratica

Questa è una **mia sintesi ragionata** dei segnali più influenti nei sistemi moderni, specie su siti web consumer con pagine HTML e funnel di navigazione ripetitivi:

## Tier 1: quasi sempre determinanti
- **TLS / transport fingerprint**
- **JS runtime / client-side detections**
- **session continuity / risk cookies**
- **sequence + timing tra endpoint**
- **ML fusion layer**

Queste cinque famiglie sono il cuore del risk scoring silenzioso moderno.

## Tier 2: molto utili ma spesso subordinate
- **IP / ASN / reputazione rete**
- **header e protocol consistency**
- **device fingerprinting**
- **anomaly detection**

Pesano molto, ma raramente da sole bastano a spiegare tutto il giudizio.

## Tier 3: potenti ma più selettive
- **mouse dynamics**
- **keystroke / interaction biometrics**
- **graph-based backend models**

Sono forti in contesti specifici, ma richiedono telemetria, integrazione e maturità maggiori.

---

# Dove il browser reale aiuta davvero, e dove no

## Aiuta molto
- **runtime JS**
- **device/environment checks**
- **session continuity**
- **coerenza cross-request**
- **accumulo di contesto lato score**

Per questi segnali, un browser reale con profilo persistente è oggettivamente più coerente di un’istanza gestita che riparte spesso da zero.

## Aiuta poco o solo indirettamente
- **IP reputation**
- **TLS fingerprint se l’origine resta sospetta**
- **pattern temporali troppo regolari**
- **session-url graph anomalo**
- **mouse/keyboard biometrics senza interazione reale**

Qui il problema non è “che browser usi”, ma **che forma ha la sessione nel tempo**.

---

# Nota privacy e compliance, che non è folklore legale

La review 2025 è molto chiara: i sistemi antibot moderni si appoggiano spesso a dati che toccano **privacy, data minimization e compliance**. In particolare, log server, IP, URL, fingerprint browser e segnali comportamentali possono creare problemi regolatori se raccolti senza basi e limiti chiari. Il paper propone proprio una tassonomia per fonte dati e discute PETs e data minimization come contrappeso tecnico.

Tradotto in italiano semplice: più il sistema diventa bravo a capire se sei umano, più rischia di somigliare a una macchina di osservazione fine-grained. Il settore lo sa, e infatti i vendor insistono molto su privacy standards, niente PII, cookie per-sito e simili.

---

# Lettura finale della griglia per il tuo scenario

Senza attribuire con certezza uno stack pubblico specifico a Idealista o Immobiliare, la combinazione **più plausibile** per portali classificati / real-estate moderni è:

- **telemetria passiva di rete e request pattern**
- **strumentazione JS invisibile**
- **session continuity**
- **sequence/timing su lista annunci, pagine dettaglio, funnel di contatto**
- **ML che fonde i segnali**
- **challenge esplicite solo quando serve**

Questa è esattamente la forma che emerge sia dalle doc dei vendor sia dalla ricerca 2025-2026.

Il prossimo passo sensato è trasformare questa griglia in una **matrice diagnostica** del tipo:  
**“se una sessione viene bloccata rapidamente, quali famiglie di segnali sono le più sospette e quali invece improbabili?”**  
Quella ti permette di leggere i sintomi senza perdere ore dietro a una singola teoria consolatoria.
