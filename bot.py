import cloudscraper
from bs4 import BeautifulSoup
import requests
import time
import logging
import re

# --- CONFIGURACIÓN DE CREDENCIALES ---
TELEGRAM_TOKEN = "8863123662:AAH54IhPr5pP0po5ev1igb6SlZBZWDekwrU"
CHAT_ID = "-1003953711208"
AFFILIATE_ID = "lazaepvictor20230320140558"

# --- CONFIGURACIÓN DEL BOT ---
URL_BUSQUEDA = "https://listado.mercadolibre.com.mx/ofertas-tecnologia" 
TIEMPO_ESPERA = 3600 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
productos_enviados = set()

def obtener_productos_scraping():
    """Descarga el HTML de Mercado Libre y extrae las ofertas manualmente."""
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome','platform': 'windows','desktop': True})
    
    try:
        response = scraper.get(URL_BUSQUEDA)
        response.raise_for_status()
        
        # Parseamos el HTML de la página
        soup = BeautifulSoup(response.text, 'html.parser')
        ofertas = []
        
        # Buscamos las "tarjetas" de los productos en el HTML
        items = soup.find_all('li', class_='ui-search-layout__item')
        
        for item in items[:20]: # Analizamos los primeros 20 resultados
            try:
                # 1. Extraer Título
                titulo_elem = item.find('h2')
                if not titulo_elem: continue
                titulo = titulo_elem.text.strip()
                
                # 2. Extraer Link
                link_elem = item.find('a', class_='ui-search-link')
                if not link_elem: continue
                link_crudo = link_elem.get('href')
                link_limpio = link_crudo.split('?')[0] # Limpiamos rastreadores basura del link
                
                # 3. Extraer Precios (Esto es un poco de magia negra con el HTML)
                # ML suele poner varios span con los precios. Si hay descuento, el primero es el viejo y el segundo el nuevo.
                precios_elem = item.find_all('span', class_='andes-money-amount__fraction')
                if len(precios_elem) >= 2:
                    precio_original = float(precios_elem[0].text.replace(',', ''))
                    precio_actual = float(precios_elem[1].text.replace(',', ''))
                else:
                    continue # Si no tiene dos precios, no está en oferta visible
                
                # 4. Extraer Imagen
                img_elem = item.find('img')
                imagen = img_elem.get('data-src') or img_elem.get('src')
                
                # 5. Generar ID único usando Regex
                id_match = re.search(r'MLM[-_]\d+', link_limpio)
                item_id = id_match.group() if id_match else link_limpio
                
                # 6. Calcular descuento final
                if precio_actual < precio_original:
                    descuento_porcentaje = int((1 - (precio_actual / precio_original)) * 100)
                    
                    if descuento_porcentaje >= 10:
                        ofertas.append({
                            "id": item_id,
                            "titulo": titulo,
                            "precio_actual": precio_actual,
                            "precio_original": precio_original,
                            "descuento": descuento_porcentaje,
                            "link": link_limpio,
                            "imagen": imagen
                        })
            except Exception as item_error:
                # Si falla un producto (ej. diseño raro), lo ignoramos y pasamos al siguiente
                continue
                
        return ofertas
    except Exception as e:
        logging.error(f"❌ Error al hacer scraping de la página: {e}")
        return []

def generar_link_afiliado(url_original):
    conector = "&" if "?" in url_original else "?"
    return f"{url_original}{conector}tracking_id={AFFILIATE_ID}"

def enviar_mensaje_telegram(producto):
    link_afiliado = generar_link_afiliado(producto['link'])
    
    mensaje = (
        f"🔥 <b>¡SÚPER OFERTA ENCONTRADA!</b> 🔥\n\n"
        f"📦 <b>Producto:</b> {producto['titulo']}\n\n"
        f"❌ Precio Original: <strike>${producto['precio_original']:,.2f}</strike>\n"
        f"✅ <b>Precio Oferta: ${producto['precio_actual']:,.2f}</b>\n"
        f"📉 <i>¡Descuento del {producto['descuento']}%!</i>\n\n"
        f"👉 <b>Cómpralo aquí:</b> <a href='{link_afiliado}'>Enlace de Compra</a>"
    )
    
    url_telegram = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    
    payload = {
        "chat_id": CHAT_ID,
        "photo": producto['imagen'],
        "caption": mensaje,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url_telegram, data=payload)
        response.raise_for_status()
        logging.info(f"✅ Oferta enviada a Telegram: {producto['titulo']}")
        return True
    except Exception as e:
        logging.error(f"❌ Error al enviar a Telegram: {e}")
        return False

def iniciar_bot():
    logging.info("🤖 Bot Iniciado. Leyendo HTML de Mercado Libre (Modo Web Scraper)...")
    
    while True:
        ofertas = obtener_productos_scraping()
        
        for oferta in ofertas:
            if oferta["id"] not in productos_enviados:
                exito = enviar_mensaje_telegram(oferta)
                if exito:
                    productos_enviados.add(oferta["id"])
                    time.sleep(15) 
        
        logging.info(f"⏳ Esperando {TIEMPO_ESPERA / 60} minutos...")
        time.sleep(TIEMPO_ESPERA)

if _name_ == "_main_":
    iniciar_bot()
