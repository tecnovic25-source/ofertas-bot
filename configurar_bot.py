import os
import requests

ENV_PATH = ".env"
DEFAULT_CHAT_ID = "-1003961189932"
DEFAULT_AFFILIATE_ID = "lazaepvictor20230320140558"


def read_env(path=ENV_PATH):
    data = {}
    if not os.path.exists(path):
        return data
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def write_env(token, chat_id, affiliate_id):
    content = f"""TELEGRAM_BOT_TOKEN={token}
TELEGRAM_CHAT_ID={chat_id}
ML_AFFILIATE_ID={affiliate_id}

MAX_OFFERS_PER_CYCLE=8
CYCLE_MINUTES=10
PUBLISHED_FILE=published_offers.json
HEADLESS=true
"""
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(content)


def mask(s):
    if not s or len(s) < 12:
        return "(vacío)"
    return s[:8] + "..." + s[-6:]


def validate_token(token):
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
    except Exception as e:
        return False, f"No pude consultar Telegram: {e}"
    if not r.ok or not data.get("ok"):
        return False, f"Telegram respondió: {data}"
    result = data.get("result", {})
    return True, f"Token válido. Bot detectado: @{result.get('username', 'sin_username')}"


def main():
    current = read_env()
    print("=== CONFIGURADOR BOT OFERTAS MERCADO LIBRE ===")
    print("Este asistente actualiza el archivo .env.")
    print("IMPORTANTE: pega el token ACTUAL de BotFather, el que funcione con getMe/getUpdates.\n")
    print(f"Token actual en .env: {mask(current.get('TELEGRAM_BOT_TOKEN', ''))}")
    print(f"Chat ID actual: {current.get('TELEGRAM_CHAT_ID', DEFAULT_CHAT_ID)}")
    print()

    token = input("Pega el TELEGRAM_BOT_TOKEN actual: ").strip()
    if not token:
        print("No pegaste token. Cancelado.")
        return

    ok, msg = validate_token(token)
    print(msg)
    if not ok:
        print("\nEse token NO sirve. Ve a BotFather > /mybots > tu bot > API Token > Revoke current token, copia el nuevo y ejecuta este configurador otra vez.")
        return

    chat_id_default = current.get("TELEGRAM_CHAT_ID", DEFAULT_CHAT_ID) or DEFAULT_CHAT_ID
    chat_id = input(f"Chat ID del grupo [{chat_id_default}]: ").strip() or chat_id_default
    affiliate_default = current.get("ML_AFFILIATE_ID", DEFAULT_AFFILIATE_ID) or DEFAULT_AFFILIATE_ID
    affiliate_id = input(f"Affiliate ID [{affiliate_default}]: ").strip() or affiliate_default

    write_env(token, chat_id, affiliate_id)
    print("\nListo. .env actualizado correctamente.")
    print("Ahora ejecuta: py app.py")


if __name__ == "__main__":
    main()
