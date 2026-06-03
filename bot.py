import cloudscraper
import requests
import time
import logging

# --- CONFIGURACIÓN DE CREDENCIALES ---
TELEGRAM_TOKEN = "8863123662:AAH54IhPr5pP0po5ev1igb6SlZBZWDekwrU"
CHAT_ID = "-1003953711208"
AFFILIATE_ID = "lazaepvictor20230320140558"

# --- CONFIGURACIÓN DEL BOT ---
SITE_ID = "MLM" 
QUERY_BUSQUEDA = "ofertas tecnologia" 
TIEMPO_ESPERA = 3600 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
productos_enviados = set()

def obtener_productos_oferta():
    """Busca productos evadiendo el TLS Fingerprinting de Mercado Libre."""
    url = f"https://api.mercadolibre.com/sites/{SITE_ID}/search?q={QUERY_BUSQUEDA}&limit=20"
    
    # Aquí está la magia: creamos un scraper que emula el motor de red de un navegador
    scraper = cloudscraper.create_scraper(browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    })
    
    try:
        response = scraper.get(url)
        response.raise_for_status() 
        data = response.json()
        
        ofertas = []
        for item in data.get("results", []):
            precio_original = item.get("original_price")
            precio_actual = item.get("price")
            
            if precio_original and precio_actual and precio_actual < precio_original:
                descuento_porcentaje = int((1 - (precio_actual / precio_original)) * 100)
                
                if descuento_porcentaje >= 10:
                    ofertas.append({
                        "id": item["id"],
                        "titulo": item["title"],
                        "precio_actual": precio_actual,
                        "precio_original": precio_original,
                        "descuento": descuento_porcentaje,
                        "link": item["permalink"],
                        "imagen": item.get("thumbnail").replace("I.jpg", "O.jpg")
                    })
        return ofertas
    except Exception as e:
        logging.error(f"❌ Error al obtener datos de Mercado Libre: {e}")
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
    logging.info("🤖 Bot Iniciado. Evadiendo firewall y buscando chollos...")
    
    while True:
        ofertas = obtener_productos_oferta()
        
        for oferta in ofertas:
            if oferta["id"] not in productos_enviados:
                exito = enviar_mensaje_telegram(oferta)
                if exito:
                    productos_enviados.add(oferta["id"])
                    time.sleep(15) 
        
        logging.info(f"⏳ Esperando {TIEMPO_ESPERA / 60} minutos...")
        time.sleep(TIEMPO_ESPERA)

if __name__ == "__main__":
    iniciar_bot()
