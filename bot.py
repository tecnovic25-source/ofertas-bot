import requests
import time
import logging

# --- CONFIGURACIÓN DE CREDENCIALES ---
TELEGRAM_TOKEN = "8863123662:AAH54IhPr5pP0po5ev1igb6SlZBZWDekwrU"
CHAT_ID = "-1003953711208"
AFFILIATE_ID = "lazaepvictor20230320140558"

# --- CREDENCIALES APP MERCADO LIBRE ---
ML_CLIENT_ID = "4161006128754088"
ML_CLIENT_SECRET = "WgGvo8pjksE1nsWFMABeYh0wznNeu4MQ"

# --- CONFIGURACIÓN DEL BOT ---
SITE_ID = "MLM" 
QUERY_BUSQUEDA = "ofertas tecnologia" 
TIEMPO_ESPERA = 3600 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
productos_enviados = set()

def obtener_token_ml():
    """Obtiene el token de autorización de Mercado Libre usando tus credenciales."""
    url = "https://api.mercadolibre.com/oauth/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": ML_CLIENT_ID,
        "client_secret": ML_CLIENT_SECRET
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    try:
        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status()
        token = response.json().get("access_token")
        logging.info("🔑 Token de Mercado Libre obtenido correctamente.")
        return token
    except Exception as e:
        logging.error(f"❌ Error al obtener token de ML: {e}")
        return None

def obtener_productos_oferta(access_token):
    """Busca productos en Mercado Libre."""
    url = f"https://api.mercadolibre.com/sites/{SITE_ID}/search"

    params = {
        "q": QUERY_BUSQUEDA,
        "limit": 20
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=20)

        if response.status_code == 403:
            logging.error(f"❌ Mercado Libre bloqueó la búsqueda. Respuesta: {response.text}")
            return []

        response.raise_for_status()
        data = response.json()

        ofertas = []

        for item in data.get("results", []):
            precio_original = item.get("original_price")
            precio_actual = item.get("price")

            if precio_original and precio_actual and precio_actual < precio_original:
                descuento_porcentaje = int((1 - (precio_actual / precio_original)) * 100)

                if descuento_porcentaje >= 10:
                    thumbnail = item.get("thumbnail") or ""

                    ofertas.append({
                        "id": item.get("id"),
                        "titulo": item.get("title"),
                        "precio_actual": precio_actual,
                        "precio_original": precio_original,
                        "descuento": descuento_porcentaje,
                        "link": item.get("permalink"),
                        "imagen": thumbnail.replace("I.jpg", "O.jpg") if thumbnail else thumbnail
                    })

        return ofertas

    except Exception as e:
        logging.error(f"Error al obtener datos de Mercado Libre: {e}")
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
        logging.info(f"✅ Oferta enviada: {producto['titulo']}")
        return True
    except Exception as e:
        logging.error(f"❌ Error al enviar a Telegram: {e}")
        return False

def iniciar_bot():
    logging.info("🤖 Bot de Ofertas Iniciado. Buscando chollos...")
    
    while True:
        # 1. Obtener el token de ML antes de buscar
        token_ml = obtener_token_ml()
        
        if token_ml:
            # 2. Buscar ofertas pasándole el token
            ofertas = obtener_productos_oferta(token_ml)
            
            for oferta in ofertas:
                if oferta["id"] not in productos_enviados:
                    exito = enviar_mensaje_telegram(oferta)
                    if exito:
                        productos_enviados.add(oferta["id"])
                        time.sleep(15) 
        
        logging.info(f"⏳ Esperando {TIEMPO_ESPERA / 60} minutos para la siguiente búsqueda...")
        time.sleep(TIEMPO_ESPERA)

if __name__ == "__main__":
    iniciar_bot()
