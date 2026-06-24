# Bot de Ofertas Mercado Libre México para Telegram

Bot en Python que revisa los feeds RSS de Promodescuentos, busca productos en Mercado Libre México, genera links de afiliado y publica ofertas en un grupo/canal de Telegram.

## Archivos importantes

- `app.py`: bot principal.
- `requirements.txt`: dependencias Python.
- `.github/workflows/ofertas-ml.yml`: GitHub Actions para correr automático.
- `.env.example`: ejemplo de variables, no poner tokens reales aquí.
- `published_offers.json`: memoria para no repetir ofertas.

## Secrets necesarios en GitHub

En el repo:

`Settings -> Secrets and variables -> Actions -> New repository secret`

Crear:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `ML_AFFILIATE_ID`

## Configuración recomendada

- `TELEGRAM_CHAT_ID=-1003961189932`
- `ML_AFFILIATE_ID=lazaepvictor20230320140558`

El token del bot debe ir en Secrets, nunca en `.env` dentro del repositorio.

## Ejecutar localmente

```bash
py -m pip install -r requirements.txt
py -m playwright install chromium
py app.py
```

Para local, crea un `.env` con tus variables reales.

## Ejecutar con GitHub Actions

El workflow corre con cron cada 5 minutos aproximados, en minutos no redondos:

```yaml
2,7,12,17,22,27,32,37,42,47,52,57 * * * *
```

GitHub puede retrasar o saltar ejecuciones cuando tiene mucha carga.

## Cómo mandar más o menos ofertas

En `.github/workflows/ofertas-ml.yml` puedes cambiar:

- `MAX_OFFERS_PER_CYCLE`: máximo que manda por ejecución.
- `MAX_RSS_ITEMS_PER_FEED`: cuántos items lee por feed.
- `MAX_CANDIDATES_PER_CYCLE`: cuántos candidatos intenta buscar en Mercado Libre.
- `MIN_DISCOUNT_PERCENT`: descuento mínimo.
- `ONLY_ML_MENTIONED`: `true` para solo posts que mencionen Mercado Libre, `false` para intentar buscar más productos del feed en ML.

Si quieres más cantidad, prueba:

```yaml
MAX_OFFERS_PER_CYCLE: "15"
MAX_CANDIDATES_PER_CYCLE: "55"
MIN_DISCOUNT_PERCENT: "3"
```

Pero mientras más candidatos revise, más tarda el workflow.
