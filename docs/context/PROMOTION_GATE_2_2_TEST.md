# PROMOTION_GATE_2_2_TEST.md

## Scopo
Definire quando una patch nata in `2.2_test` puo essere promossa verso `2.1_stable`.

## Regola generale
Nessuna patch si promuove per intuizione.
Serve evidenza comparabile.

## Criteri minimi di promozione
Una patch di `2.2_test` puo entrare in `2.1_stable` solo se:
1. migliora almeno una metrica chiave su run comparabili
2. non peggiora l'altro sito in modo rilevante
3. non aumenta il costo di supporto
4. non aggiunge passaggi manuali nel first-run standard
5. non allarga scope su GUI/packaging/lifecycle senza decisione esplicita

## Evidenze richieste
- log reali comparabili
- telemetria minima comune
- nota rischi residui
- rollback chiaro
- finestra di osservazione dichiarata prima del test

## Soglia minima consigliata
- almeno 10 run comparabili per sito coinvolto, salvo esperimento dichiaratamente piu piccolo
- confronto prima/dopo sullo stesso perimetro operativo
- nessuna promozione se la lettura dei log resta ambigua

## Casi da non promuovere
- patch utile solo in contesto assistito
- patch che riduce block ma aumenta `identity_switch`
- patch che migliora un sito e degrada l'altro
- patch che richiede CDP come routine standard
