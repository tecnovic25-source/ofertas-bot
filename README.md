# Bot de ofertas Mercado Libre para GitHub Actions

Este bot revisa Promodescuentos, busca productos en Mercado Libre México, genera links de afiliado y publica ofertas en Telegram.

## Archivos que van al repo

Sube estos archivos/carpetas:

- `app.py`
- `requirements.txt`
- `.github/workflows/ofertas-ml.yml`
- `.env.example`
- `.gitignore`
- `published_offers.json`
- `README.md`

No subas `.env` con credenciales reales.

## Secrets necesarios en GitHub

En tu repositorio entra a:

`Settings -> Secrets and variables -> Actions -> New repository secret`

Crea estos secretos:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `ML_AFFILIATE_ID`

Para tu grupo actual, el `TELEGRAM_CHAT_ID` es:

```text
-1003961189932
```

Tu `ML_AFFILIATE_ID` es:

```text
lazaepvictor20230320140558
```

## Cómo correrlo

El workflow se ejecuta automáticamente cada 10 minutos y también puedes iniciarlo manualmente desde:

`Actions -> Ofertas Mercado Libre -> Run workflow`

## Importante

El archivo `published_offers.json` se actualiza automáticamente para evitar repetir ofertas. Por eso el workflow necesita permiso de escritura en el repositorio.
