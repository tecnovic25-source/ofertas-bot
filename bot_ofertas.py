import requests
import schedule
import time
import re
import xml.etree.ElementTree as ET
from datetime import datetime

# ============================================================
TELEGRAM_TOKEN   = "8863123662:AAH54IhPr5pP0po5ev1igb6SlZBZWDeKwrU"
TELEGRAM_CHAT_ID = "-1003953711208"
AFFILIATE_ID     = "lazaepvictor20230320140558"

PRODUCTOS_POR_CICLO = 8
HORAS_ENTRE_ENVIOS  = 2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

RSS_FEEDS = [
    "https://www.promodescuentos.com/rss/hot",
    "https://www.promodescuentos.com/rss/new",
    "https://www.promodescuentos.com/rss/ofertas",
]

publicados = set()
# ============================================================


def construir_link_afiliado(url):
    if not url:
        return url
    if "mercadolibre.com" in url:
        url_limpia = url.split("?")[0]
        return f"{url_limpia}?matt_tool={AFFILIATE_ID}&matt_source=telegram&matt_campaign=ofertas"
    return url


def extraer_link_ml(texto_html):
    """Extrae SOLO links directos de ML del contenido RSS."""
    if not texto_html:
        return None
    patron = r'https?://(?:www\.)?(?:articulo\.)?mercadolibre\.com\.mx/[^\s"\'<>&]+'
    matches = re.findall(patron, texto_html)
    for m in matches:
        if "MLM" in m:
            return m.strip()
    # Si no hay /MLM, devolver cualquier link de ML
    for m in matches:
        return m.strip()
    return None


def extraer_precios(texto):
    precio_actual = precio_original = descuento = None
    precios = re.findall(r'\$\s*([\d,]+(?:\.\d+)?)', texto)
    nums = []
    for p in precios:
        try:
            nums.append(float(p.replace(',', '')))
        except:
            continue

    desc_match = re.search(r'(\d+)\s*%\s*(?:de\s*)?(?:descuento|off|menos|dto)', texto, re.IGNORECASE)
    if desc_match:
        descuento = int(desc_match.group(1))

    if len(nums) >= 2:
        precio_original = max(nums[:3])
        precio_actual   = min(nums[:3])
        if precio_original > precio_actual and descuento is None:
            descuento = round((1 - precio_actual / precio_original) * 100)
    elif len(nums) == 1:
        precio_actual = nums[0]

    return precio_actual, precio_original, descuento


def leer_feed_rss(url_feed):
    ofertas = []
    try:
        r = requests.get(url_feed, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"  [!] RSS {r.status_code}: {url_feed}")
            return []

        root = ET.fromstring(r.content)
        canal = root.find('channel')
        if canal is None:
            return []

        items = canal.findall('item')
        print(f"  [✓] {len(items)} items en {url_feed.split('/')[-1]}")

        for item in items:
            titulo   = item.findtext('title', '')
            link     = item.findtext('link', '')
            desc_raw = item.findtext('description', '')
            guid     = item.findtext('guid', link)

            texto_completo = f"{titulo} {desc_raw} {link}"

            # Solo ofertas de Mercado Libre
            if 'mercado libre' not in texto_completo.lower() and 'mercadolibre' not in texto_completo.lower():
                continue

            if guid in publicados:
                continue

            # Extraer link DIRECTO de ML — nunca usar link de promodescuentos
            link_ml = extraer_link_ml(desc_raw) or extraer_link_ml(link)
            if not link_ml or "mercadolibre.com" not in link_ml:
                continue  # Descartar si no hay link directo de ML

            precio_act, precio_orig, descuento = extraer_precios(texto_completo)

            imagen = ""
            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc_raw)
            if img_match:
                imagen = img_match.group(1)

            titulo_limpio = re.sub(r'<[^>]+>', '', titulo).strip()
            if len(titulo_limpio) < 5:
                continue

            ofertas.append({
                "titulo":          titulo_limpio[:80],
                "precio_actual":   precio_act,
                "precio_original": precio_orig,
                "descuento":       descuento,
                "link":            link_ml,
                "imagen":          imagen,
                "guid":            guid,
                "envio_gratis":    "envío gratis" in texto_completo.lower() or "envio gratis" in texto_completo.lower(),
            })

    except ET.ParseError as e:
        print(f"  [!] Error XML: {e}")
    except Exception as e:
        print(f"  [!] Error: {e}")

    return ofertas


def buscar_ofertas():
    todas = []
    guids_vistos = set()

    for url in RSS_FEEDS:
        items = leer_feed_rss(url)
        for item in items:
            if item["guid"] not in guids_vistos and item["guid"] not in publicados:
                guids_vistos.add(item["guid"])
                todas.append(item)
        time.sleep(0.5)

    con_desc = sorted([x for x in todas if x["descuento"] and x["descuento"] >= 10],
                      key=lambda x: x["descuento"], reverse=True)
    sin_desc = [x for x in todas if not x["descuento"] or x["descuento"] < 10]

    resultado = (con_desc + sin_desc)[:PRODUCTOS_POR_CICLO]
    print(f"[✓] {len(todas)} ofertas ML encontradas | Publicando {len(resultado)}")
    return resultado


def emoji_categoria(titulo):
    t = titulo.lower()
    if any(x in t for x in ['iphone', 'samsung', 'celular', 'smartphone', 'xiaomi']):
        return '📱'
    if any(x in t for x in ['laptop', 'computadora', 'pc', 'monitor', 'teclado']):
        return '💻'
    if any(x in t for x in ['televisor', 'tv', 'pantalla', 'smart tv']):
        return '📺'
    if any(x in t for x in ['audífono', 'audifonos', 'bocina', 'speaker', 'airpod']):
        return '🎧'
    if any(x in t for x in ['zapato', 'tenis', 'zapatilla', 'ropa', 'camisa', 'vestido']):
        return '👟'
    if any(x in t for x in ['licuadora', 'cafetera', 'microondas', 'lavadora', 'refrigerador']):
        return '🏠'
    if any(x in t for x in ['juguete', 'lego', 'muñeca', 'figura']):
        return '🧸'
    if any(x in t for x in ['perfume', 'crema', 'shampoo', 'vitamina', 'suplemento']):
        return '💊'
    if any(x in t for x in ['bicicleta', 'pesa', 'gym', 'deporte', 'fitness']):
        return '⚽'
    return '🛒'


def formatear_mensaje(p):
    link    = construir_link_afiliado(p["link"])
    emoji   = emoji_categoria(p["titulo"])
    titulo_upper = p["titulo"].upper()
    envio   = "✅ ENVÍO GRATIS\n" if p.get("envio_gratis") else ""
    hora    = datetime.now().strftime('%d/%m/%Y %H:%M')

    # Bloque de precio
    if p["precio_actual"] and p["precio_original"] and p["descuento"]:
        ahorro = p["precio_original"] - p["precio_actual"]
        precio_bloque = (
            f"🔴 -{p['descuento']}% DE DESCUENTO\n"
            f"🔥 Precio Oferta: ${p['precio_actual']:,.2f}\n"
            f"Precio anterior: ${p['precio_original']:,.2f}\n"
            f"💵 Ahorras: ${ahorro:,.2f} MXN"
        )
    elif p["precio_actual"] and p["descuento"]:
        precio_bloque = (
            f"🔴 -{p['descuento']}% DE DESCUENTO\n"
            f"🔥 Precio Oferta: ${p['precio_actual']:,.2f} MXN"
        )
    elif p["precio_actual"]:
        precio_bloque = f"🔥 Precio: ${p['precio_actual']:,.2f} MXN"
    elif p["descuento"]:
        precio_bloque = f"🔴 -{p['descuento']}% DE DESCUENTO"
    else:
        precio_bloque = "💰 Ver precio en el link"

    msg = (
        f"{emoji} *{titulo_upper}*\n\n"
        f"👉 Ver Oferta: {link}\n\n"
        f"{precio_bloque}\n"
        f"{envio}\n"
        f"🕐 _{hora}_\n\n"
        f"#OfertasML #MercadoLibre #Descuentos #AhorraHoy"
    )
    return msg


def enviar_telegram(p):
    global publicados
    texto  = formatear_mensaje(p)
    imagen = p.get("imagen", "")

    try:
        exito = False
        if imagen:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                json={"chat_id": TELEGRAM_CHAT_ID, "photo": imagen,
                      "caption": texto, "parse_mode": "Markdown"},
                timeout=10
            )
            exito = r.status_code == 200

        if not exito:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": texto,
                      "parse_mode": "Markdown", "disable_web_page_preview": False},
                timeout=10
            )
            exito = r.status_code == 200

        if exito:
            publicados.add(p["guid"])
            desc_str = f"{p['descuento']}% off" if p["descuento"] else "oferta"
            print(f"  [✓] {p['titulo'][:50]} | {desc_str}")
        else:
            print(f"  [!] Telegram error: {r.text[:100]}")

    except Exception as e:
        print(f"  [!] {e}")


def ciclo_principal():
    print(f"\n{'='*50}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Buscando ofertas...")
    print(f"{'='*50}")
    ofertas = buscar_ofertas()
    if not ofertas:
        print("[!] Sin ofertas nuevas en este ciclo.")
        return
    print(f"\n📤 Publicando {len(ofertas)} ofertas...\n")
    for p in ofertas:
        enviar_telegram(p)
        time.sleep(3)
    print(f"\n[✓] Listo. Próximo ciclo en {HORAS_ENTRE_ENVIOS} horas.")


def mensaje_inicio():
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id":    TELEGRAM_CHAT_ID,
                "text": (
                    "🔥 *OFERTASMX BOT ACTIVO* 🔥\n\n"
                    "💰 Las mejores ofertas de Mercado Libre directo aquí\n"
                    "🏷️ Solo descuentos reales y verificados\n"
                    "⚡ Actualizaciones cada 2 horas\n\n"
                    "¡Bienvenidos y a ahorrar! 🛒"
                ),
                "parse_mode": "Markdown"
            }, timeout=10
        )
    except:
        pass


if __name__ == "__main__":
    print("=" * 50)
    print("  OfertasMX Bot — RSS + Diseño Pro")
    print("=" * 50)
    mensaje_inicio()
    ciclo_principal()
    schedule.every(HORAS_ENTRE_ENVIOS).hours.do(ciclo_principal)
    print(f"\n[✓] Bot activo. Ctrl+C para detener.\n")
    while True:
        schedule.run_pending()
        time.sleep(60)
