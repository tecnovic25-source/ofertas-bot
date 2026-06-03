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
TIEMPO_ESPERA = 60 # ⚠️ BAJAMOS EL TIEMPO A 60 SEGUNDOS PARA PRUEBAS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
productos_enviados = set()

def obtener_productos_scraping():
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome','platform': 'windows','desktop': True})
    
    try:
        response = scraper.get(URL_BUSQUEDA)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. Validar qué página nos devolvió ML exactamente
        titulo_pagina = soup.title.text if soup.title else 'Sin título'
        logging.info(f"📄 Título de la página cargada: {titulo_pagina}")
        
        # 2. Buscar las tarjetas de productos
        items = soup.find_all('li', class_='ui-search-layout__item')
        logging.info(f"🔍 Se encontraron {len(items)} elementos de producto en el HTML.")
        
        ofertas = []
        for item in items[:20]:
            try:
                titulo_elem = item.find('h2')
                if not titulo_elem: continue
                titulo = titulo_elem.text.strip()
                
                link_elem = item.find('a', class_='ui-search-link')
                if not link_elem: continue
                link_crudo = link_elem.get('href')
                link_limpio = link_crudo.split('?')[0]
                
                # Precios
                precios_elem = item.find_all('span', class_='andes-money-amount__fraction')
                if len(precios_elem) >= 2:
                    precio_original = float(precios_elem[0].text.replace(',', ''))
                    precio_actual = float(precios_elem[1].text.replace(',', ''))
                else:
                    continue
                
                img_elem = item.find('img')
                imagen = img_elem.get('data-src') or img_elem.get('src')
                
                id_match = re.search(r'MLM[-_]\d+', link_limpio)
                item_id = id_match.group() if id_match else link_limpio
                
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
            except Exception as e:
                continue
                
        logging.info(f"✅ Se extrajeron exitosamente {len(ofertas)} ofertas con más del 10% de descuento.")
        return ofertas
    except Exception as e:
        logging.error(f"❌ Error al hacer scraping: {e}")
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
        logging.info(f"🚀 Mensaje enviado a Telegram: {producto['titulo']}")
        return True
    except Exception as e:
        logging.error(f"❌ Error al enviar a Telegram: {e}")
        return False

def iniciar_bot():
    logging.info("🤖 Bot Iniciado. Modo Diagnóstico Activado...")
    
    while True:
        ofertas = obtener_productos_scraping()
        
        for oferta in ofertas:
            if oferta["id"] not in productos_enviados:
                exito = enviar_mensaje_telegram(oferta)
                if exito:
                    productos_enviados.add(oferta["id"])
                    time.sleep(5) # Lo bajamos a 5 segundos para pruebas
        
        logging.info(f"⏳ Esperando {TIEMPO_ESPERA} segundos para el siguiente escaneo...")
        time.sleep(TIEMPO_ESPERA)

if __name__ == "__main__":
    iniciar_bot()
