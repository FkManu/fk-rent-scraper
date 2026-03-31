# REVIEW_CURRENT.md

## Patch corrente
`2.3-patch-04` - Autostart servizio continuo solo da boot Windows

## Stato review
Verifica statica completata. Test automatici verdi. Verifica reale post-reboot ancora da eseguire.

## Focus della review
- separazione affidabile tra launch da boot Windows e apertura manuale
- correttezza del flag dipendente `autostart_service_enabled`
- rimozione selettiva della stop-flag stale
- assenza di dialog bloccanti nel percorso autostart automatico
- nessuna regressione su start/stop manuali e stato GUI

## Esito sintetico
- il servizio continuo puo partire automaticamente solo dal ramo boot-autostart
- le aperture manuali della GUI restano passive anche con entrambe le spunte attive
- `autostart_service_enabled` viene forzato non operativo quando `autostart_enabled=False`
- la stop-flag stale viene pulita solo prima dell'avvio automatico da boot
- la suite e verde: `100 passed`

## Rischi residui
- manca verifica reale post-reboot per confermare il launch automatico del servizio nel boot path reale
- il marker env vive nel wrapper `.vbs`: se qualcuno lancia manualmente quello script, il servizio partira come percorso autostart
- `requirements.txt` continua a portare `undetected-playwright==0.3.0` senza un nuovo path operativo dichiarato
