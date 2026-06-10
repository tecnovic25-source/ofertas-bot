# Bot de ofertas Mercado Libre México → Telegram

Busca ofertas de Mercado Libre México desde los RSS de Promodescuentos, obtiene el producto real en Mercado Libre usando Playwright, genera link de afiliado y publica en Telegram cada 10 minutos.

## 1. Instalar dependencias

```bash
py -m pip install -r requirements.txt
py -m playwright install chromium
```

## 2. Configurar credenciales

Copia `.env.example` como `.env`:

```bash
copy .env.example .env
```

Edita `.env` y pega tus datos reales:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
ML_AFFILIATE_ID=...
```

> No subas el archivo `.env` a GitHub.

## 3. Ejecutar

```bash
py app.py
```

Al iniciar enviará un mensaje de bienvenida al grupo, hará un primer ciclo inmediato y después correrá cada 10 minutos.

## Qué hace

- Lee:
  - `https://www.promodescuentos.com/rss/hot`
  - `https://www.promodescuentos.com/rss/new`
- Filtra títulos que contengan `Mercado Libre` o `Mercadolibre`.
- Busca el producto en `listado.mercadolibre.com.mx`.
- Extrae link, precio, precio anterior, descuento, imagen y envío gratis cuando aplique.
- Agrega parámetros de afiliado:
  - `matt_tool`
  - `matt_source=telegram`
  - `matt_campaign=ofertas`
- Publica máximo 8 ofertas por ciclo.
- Guarda IDs publicados en `published_offers.json` para evitar repetidos.
- Reutiliza el mismo navegador/contexto Playwright durante toda la sesión.

## Nota importante

Si Mercado Libre cambia clases HTML o bloquea automatización, revisa los selectores dentro de `extract_offer_from_product_page()`.
