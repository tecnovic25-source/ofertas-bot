import requests
import time
import logging

# --- CONFIGURACIÓN DE CREDENCIALES ---
TELEGRAM_TOKEN = "8863123662:AAH54IhPr5pP0po5ev1igb6SlZBZWDekwrU"
CHAT_ID = "-1003953711208"
AFFILIATE_ID = "lazaepvictor20230320140558"

# --- CONFIGURACIÓN DEL BOT ---
SITE_ID = "MLM" # MLM es para México. (MLA=Argentina, MCO=Colombia)
QUERY_BUSQUEDA = "ofertas tecnologia" # Qué quieres buscar
TIEMPO_ESPERA = 3600 # Segundos entre cada revisión (3600 = 1 hora)

# Configurar el registro de errores (log)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# Memoria para no repetir productos enviados
productos_enviados = set()

def obtener_productos_oferta():
    """Busca productos en Mercado Libre y filtra los que tienen descuento."""
    url = f"https://api.mercadolibre.com/sites/{SITE_ID}/search?q={QUERY_BUSQUEDA}&limit=20"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        ofertas = []
        for item in data.get("results", []):
            # Verificamos si tiene un precio original (lo que indica que hay descuento)
            precio_original = item.get("original_price")
            precio_actual = item.get("price")
            
            if precio_original and precio_actual and precio_actual < precio_original:
                descuento_porcentaje = int((1 - (precio_actual / precio_original)) * 100)
                
                # Ignorar ofertas muy pequeñas (menores al 10%)
                if descuento_porcentaje >= 10:
                    ofertas.append({
                        "id": item["id"],
                        "titulo": item["title"],
                        "precio_actual": precio_actual,
                        "precio_original": precio_original,
                        "descuento": descuento_porcentaje,
                        "link": item["permalink"],
                        "imagen": item.get("thumbnail").replace("I.jpg", "O.jpg") # Intenta obtener mejor calidad
                    })
        return ofertas
    except Exception as e:
        logging.error(f"Error al obtener datos de Mercado Libre: {e}")
        return []

def generar_link_afiliado(url_original):
    """
    Convierte el link normal al link de afiliado.
    NOTA: La estructura exacta puede variar según las políticas actuales de ML.
    Normalmente, se añade un tracking_id o se pasa por un acortador.
    """
    # Si la URL ya tiene parámetros, usamos '&', si no, usamos '?'
    conector = "&" if "?" in url_original else "?"
    return f"{url_original}{conector}tracking_id={AFFILIATE_ID}"

def enviar_mensaje_telegram(producto):
    """Envía el mensaje con formato al canal de Telegram."""
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
        ofertas = obtener_productos_oferta()
        
        for oferta in ofertas:
            if oferta["id"] not in productos_enviados:
                # Enviamos el mensaje
                exito = enviar_mensaje_telegram(oferta)
                
                if exito:
                    productos_enviados.add(oferta["id"])
                    # Pausa de 15 segundos entre mensajes para no saturar Telegram (Spam limits)
                    time.sleep(15) 
                
        logging.info(f"⏳ Esperando {TIEMPO_ESPERA / 60} minutos para la siguiente búsqueda...")
        time.sleep(TIEMPO_ESPERA)

if _name_ == "_main_":
    iniciar_bot()