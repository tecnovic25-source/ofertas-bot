import requests
import schedule
import time
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from playwright.sync_api import sync_playwright

# ============================================================
TELEGRAM_TOKEN   = "8863123662:AAH54IhPr5pP0po5ev1igb6SlZBZWDeKwrU"
TELEGRAM_CHAT_ID = "-1003953711208"
AFFILIATE_ID     = "lazaepvictor20230320140558"

PRODUCTOS_POR_CICLO  = 8
MINUTOS_ENTRE_ENVIOS = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "es-MX,es;q=0.9",
}

RSS_FEEDS = [
    "https://www.promodescuentos.com/rss/hot",
    "https://www.promodescuentos.com/rss/new",
]

publicados = set()
pw = None
browser = None
# ============================================================


def iniciar_browser():
    global pw, browser
    if browser is None:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        print("[✓] Browser iniciado")


def construir_link_afiliado(url):
    if not url or "mercadolibre.com" not in url:
        return url
    url_limpia = url.split("?")[0]
    return f"{url_limpia}?matt_tool={AFFILIATE_ID}&matt_source=telegram&matt_campaign=ofertas"


def buscar_producto_en_ml(titulo_producto):
    """Busca el producto en ML y devuelve el link del primer resultado."""
    global browser
    try:
        # Limpiar título para búsqueda
        titulo_limpio = re.sub(r'\|.*$', '', titulo_producto).strip()
        titulo_limpio = re.sub(r'\$[\d,]+', '', titulo_limpio).strip()
        titulo_limpio = re.sub(r'\d+%', '', titulo_limpio).strip()
        titulo_limpio = titulo_limpio[:60].strip()

        keyword = requests.utils.quote(titulo_limpio)
        url_busqueda = f"https://listado.mercadolibre.com.mx/{keyword}"

        page = browser.new_page()
        page.set_extra_http_headers({"Accept-Language": "es-MX"})
        page.goto(url_busqueda, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2000)

        # Buscar primer link de producto MLM
        links = page.query_selector_all('a[href*="/MLM"]')
        link_ml = None
        for el in links[:5]:
            href = el.get_attribute("href")
            if href and "/MLM" in href and "mercadolibre.com.mx" in href:
                link_ml = href.split("?")[0]
                break

        # Intentar con selector de tarjeta de producto
        if not link_ml:
            el = page.query_selector('.ui-search-item__group__element a, .poly-card a')
            if el:
                href = el.get_attribute("href")
                if href and "mercadolibre.com" in href:
                    link_ml = href.split("?")[0]

        page.close()
        return link_ml

    except Exception as e:
        print(f"    [!] Error búsqueda ML: {e}")
        try:
            page.close()
        except:
            pass
        return None


def extraer_precios_titulo(titulo):
    precio_actual = precio_original = descuento = None

    desc_match = re.search(r'(\d+)\s*%', titulo)
    if desc_match:
        d = int(desc_match.group(1))
        if 1 < d < 95:
            descuento = d

    precios = re.findall(r'\$\s*([\d,]+(?:\.\d+)?)', titulo)
    nums = []
    for p in precios:
        try:
            n = float(p.replace(',', ''))
            if n > 10:
                nums.append(n)
        except:
            continue

    if len(nums) >= 2:
        precio_original = max(nums[:3])
        precio_actual   = min(nums[:3])
        if precio_original > precio_actual and not descuento:
            descuento = round((1 - precio_actual / precio_original) * 100)
    elif len(nums) == 1:
        precio_actual = nums[0]

    return precio_actual, precio_original, descuento


def leer_feed_rss(url_feed):
    ofertas = []
    try:
        r = requests.get(url_feed,
            headers={**HEADERS, "Accept": "application/rss+xml, */*"},
            timeout=15)
        if r.status_code != 200:
            print(f"  [!] RSS {r.status_code}")
            return []

        root = ET.fromstring(r.content)
        canal = root.find('channel')
        if canal is None:
            return []

        items = canal.findall('item')
        print(f"  [✓] {len(items)} items en {url_feed.split('/')[2]}")

        ml_count = 0
        for item in items:
            titulo   = item.findtext('title', '')
            desc_raw = item.findtext('description', '')
            guid     = item.findtext('guid', '')

            if 'mercado libre' not in titulo.lower():
                continue
            if guid in publicados:
                continue

            # Limpiar título
            titulo_limpio = re.sub(r'^[\d°\s\-]+', '', titulo).strip()
            titulo_limpio = re.sub(r'^Mercado [Ll]ibre:\s*', '', titulo_limpio).strip()
            titulo_limpio = re.sub(r'\s*\|.*$', '', titulo_limpio).strip()

            if len(titulo_limpio) < 5:
                continue

            print(f"    → Buscando en ML: {titulo_limpio[:50]}...")

            # Buscar producto directamente en ML
            link_ml = buscar_producto_en_ml(titulo_limpio)

            if not link_ml:
                print(f"    [!] No encontrado, saltando")
                continue

            print(f"    [✓] {link_ml[-50:]}")

            precio_act, precio_orig, descuento = extraer_precios_titulo(titulo)

            imagen = ""
            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc_raw)
            if img_match:
                imagen = img_match.group(1)

            ml_count += 1
            ofertas.append({
                "titulo":          titulo_limpio[:80],
                "precio_actual":   precio_act,
                "precio_original": precio_orig,
                "descuento":       descuento,
                "link":            link_ml,
                "imagen":          imagen,
                "guid":            guid,
                "envio_gratis":    "envío gratis" in titulo.lower(),
            })
            time.sleep(1)

        print(f"    → {ml_count} ofertas procesadas")
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
        time.sleep(1)

    con_desc = sorted([x for x in todas if x["descuento"] and x["descuento"] >= 5],
                      key=lambda x: x["descuento"], reverse=True)
    sin_desc = [x for x in todas if not x["descuento"] or x["descuento"] < 5]
    resultado = (con_desc + sin_desc)[:PRODUCTOS_POR_CICLO]
    print(f"[✓] {len(todas)} ofertas | Publicando {len(resultado)}")
    return resultado


def emoji_categoria(titulo):
    t = titulo.lower()
    if any(x in t for x in ['iphone', 'samsung', 'celular', 'smartphone', 'xiaomi', 'motorola']):
        return '📱'
    if any(x in t for x in ['laptop', 'computadora', 'pc', 'monitor', 'teclado']):
        return '💻'
    if any(x in t for x in ['televisor', 'tv', 'pantalla', 'smart tv', 'hisense', 'lg ', 'tcl']):
        return '📺'
    if any(x in t for x in ['audífono', 'audifonos', 'bocina', 'speaker', 'airpod', 'jbl']):
        return '🎧'
    if any(x in t for x in ['zapato', 'tenis', 'zapatilla', 'ropa', 'camisa', 'vestido', 'mochila']):
        return '👟'
    if any(x in t for x in ['licuadora', 'cafetera', 'microondas', 'lavadora', 'refrigerador']):
        return '🏠'
    if any(x in t for x in ['juguete', 'lego', 'muñeca', 'figura']):
        return '🧸'
    if any(x in t for x in ['perfume', 'crema', 'shampoo', 'vitamina', 'suplemento']):
        return '💊'
    if any(x in t for x in ['bicicleta', 'pesa', 'gym', 'deporte', 'fitness']):
        return '⚽'
    if any(x in t for x in ['dron', 'drone', 'dji', 'osmo']):
        return '🚁'
    if any(x in t for x in ['meta quest', 'realidad virtual', 'oculus']):
        return '🥽'
    return '🛒'


def formatear_mensaje(p):
    link  = construir_link_afiliado(p["link"])
    emoji = emoji_categoria(p["titulo"])
    envio = "✅ ENVIO GRATIS\n" if p.get("envio_gratis") else ""
    hora  = datetime.now().strftime("%d/%m/%Y %H:%M")
    titulo_html = p["titulo"].upper().replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    if p["precio_actual"] and p["precio_original"] and p["descuento"]:
        ahorro = p["precio_original"] - p["precio_actual"]
        precio_bloque = (
            f"🔴 <b>-{p['descuento']}% DE DESCUENTO</b>\n"
            f"🔥 <b>Precio Oferta: ${p['precio_actual']:,.2f} MXN</b>\n"
            f"<s>Precio anterior: ${p['precio_original']:,.2f} MXN</s>\n"
            f"💵 Ahorras: <b>${ahorro:,.2f} MXN</b>"
        )
    elif p["precio_actual"] and p["descuento"]:
        precio_bloque = (
            f"🔴 <b>-{p['descuento']}% DE DESCUENTO</b>\n"
            f"🔥 <b>Precio Oferta: ${p['precio_actual']:,.2f} MXN</b>"
        )
    elif p["descuento"]:
        precio_bloque = f"🔴 <b>-{p['descuento']}% DE DESCUENTO</b>"
    elif p["precio_actual"]:
        precio_bloque = f"🔥 <b>Precio: ${p['precio_actual']:,.2f} MXN</b>"
    else:
        precio_bloque = "💰 Ver precio en el link"

    return (
        f"{emoji} <b>{titulo_html}</b>\n\n"
        f'👉 <a href="{link}">VER OFERTA EN MERCADO LIBRE</a>\n\n'
        f"{precio_bloque}\n"
        f"{envio}\n"
        f"🕐 {hora}\n\n"
        f"#OfertasML #MercadoLibre #Descuentos #AhorraHoy"
    )


def enviar_telegram(p):
    texto  = formatear_mensaje(p)
    imagen = p.get("imagen", "")
    try:
        exito = False
        if imagen:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                json={"chat_id": TELEGRAM_CHAT_ID, "photo": imagen,
                      "caption": texto, "parse_mode": "HTML"},
                timeout=10
            )
            exito = r.status_code == 200
        if not exito:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": texto,
                      "parse_mode": "HTML"},
                timeout=10
            )
            exito = r.status_code == 200
        if exito:
            publicados.add(p["guid"])
            print(f"  [✓] {p['titulo'][:50]}")
        else:
            print(f"  [!] Telegram: {r.text[:80]}")
    except Exception as e:
        print(f"  [!] {e}")


def ciclo_principal():
    print(f"\n{'='*50}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Buscando ofertas...")
    print(f"{'='*50}")
    ofertas = buscar_ofertas()
    if not ofertas:
        print("[!] Sin ofertas nuevas.")
        return
    print(f"\n📤 Publicando {len(ofertas)} ofertas...\n")
    for p in ofertas:
        enviar_telegram(p)
        time.sleep(3)
    print(f"\n[✓] Listo. Próximo en {MINUTOS_ENTRE_ENVIOS} min.")


def mensaje_inicio():
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID,
                  "text": "🔥 <b>OFERTASMX BOT ACTIVO</b> 🔥\n\n💰 Las mejores ofertas de Mercado Libre\n⚡ Actualizaciones cada 10 minutos\n\n¡Bienvenidos y a ahorrar! 🛒",
                  "parse_mode": "HTML"},
            timeout=10
        )
    except:
        pass


if __name__ == "__main__":
    print("=" * 50)
    print("  OfertasMX Bot — Búsqueda directa en ML")
    print("=" * 50)
    iniciar_browser()
    mensaje_inicio()
    ciclo_principal()
    schedule.every(MINUTOS_ENTRE_ENVIOS).minutes.do(ciclo_principal)
    print(f"\n[✓] Bot activo. Ctrl+C para detener.\n")
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        if browser:
            browser.close()
            pw.stop()
        print("\n[✓] Bot detenido.")
