# PROMOTION_GATE_2_3_TEST.md

## Scopo
Definire quando una patch nata in `2.3_test` puo essere promossa verso la linea shipping derivata da `2.2 stable`.

## Regola generale
Nessuna patch si promuove per intuizione.

Serve evidenza comparabile contro la baseline `2.2.2 refactorizzata`.

## Criteri minimi di promozione
Una patch di `2.3_test` puo essere candidata alla promozione solo se:
1. migliora almeno una metrica chiave su run comparabili
2. non peggiora l'altro sito in modo rilevante
3. non aumenta il costo di supporto
4. non aggiunge rituali manuali al percorso standard
5. non allarga scope su packaging o lifecycle senza decisione esplicita

## Evidenze richieste
- log comparabili prima/dopo
- telemetria minima comune
- nota rischi residui
- rollback chiaro
- finestra di osservazione dichiarata

## Casi da non promuovere
- patch utile solo in contesto assistito
- patch che riduce block ma aumenta `identity_switch`
- patch che migliora un sito e degrada l'altro
- patch che riduce il rumore locale ma rompe la leggibilita operativa

## Nota pratica
La `2.3_test` non nasce per riversare patch subito.

Nasce per misurare bene la prossima iterazione sopra la baseline `2.2`.
