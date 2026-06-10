import html
import json
import logging
import os
import re
import time
import traceback
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Optional, List, Set, Dict, Any

import requests
import schedule
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError



def _load_dotenv_early(path: str = ".env") -> None:
    """Carga .env antes de leer constantes de configuración."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_dotenv_early()

# =========================
# CONFIGURACION GENERAL
# =========================
RSS_URLS = [
    "https://www.promodescuentos.com/rss/hot",
    "https://www.promodescuentos.com/rss/new",
]

MAX_OFFERS_PER_CYCLE = int(os.getenv("MAX_OFFERS_PER_CYCLE", "8"))
CYCLE_MINUTES = int(os.getenv("CYCLE_MINUTES", "10"))
PUBLISHED_FILE = os.getenv("PUBLISHED_FILE", "published_offers.json")

ML_AFFILIATE_PARAMS = {
    "matt_source": "telegram",
    "matt_campaign": "ofertas",
}

REAL_CHROME_UA = os.getenv(
    "REAL_CHROME_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36",
)

RSS_HEADERS = {
    "User-Agent": REAL_CHROME_UA,
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("ofertas-ml-bot")


@dataclass
class RSSItem:
    title: str
    link: str
    guid: str
    pub_date: str = ""


@dataclass
class MLOffer:
    source_title: str
    product_title: str
    product_link: str
    affiliate_link: str
    current_price: Optional[float]
    original_price: Optional[float]
    discount_percent: Optional[int]
    image_url: Optional[str]
    free_shipping: bool


# =========================
# UTILIDADES
# =========================
def load_dotenv_local(path: str = ".env") -> None:
    """Carga un .env sencillo sin dependencia externa tipo python-dotenv."""
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Falta configurar la variable de entorno: {name}")
    return value


def stable_hash(value: str) -> str:
    return sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:24]


def normalize_title_for_ml_search(title: str) -> str:
    """Limpia títulos tipo Promodescuentos antes de buscarlos en ML.

    Ejemplo de entrada RSS:
    "102° – Mercado Libre: Silla ejecutiva de oficina"

    Si mandamos eso tal cual a Mercado Libre, la búsqueda queda sucia
    y ML suele regresar resultados raros o ningún producto. Aquí dejamos
    solamente la parte útil del producto.
    """
    clean = html.unescape(title or "")

    # Quédate con lo que viene después de "Mercado Libre:" si existe.
    m = re.search(r"(?i)mercado\s*libre\s*[:\-–—]+\s*(.+)$", clean)
    if m:
        clean = m.group(1)

    clean = re.sub(r"https?://\S+", " ", clean)
    clean = re.sub(r"(?i)\bmercado\s*libre\b|\bmercadolibre\b|\bml\b", " ", clean)

    # Quita temperatura/votos de Promodescuentos: 102°, 154°, etc.
    clean = re.sub(r"\b\d{1,4}\s*°", " ", clean)

    # Quita textos comunes que no ayudan a encontrar el producto.
    clean = re.sub(r"(?i)\bhot\b|\bnuevo\b|\boferta\b|\bpromoción\b|\bpromo\b|\bdescuento\b", " ", clean)

    # Quita precios o porcentajes del título para que la búsqueda sea más natural.
    clean = re.sub(r"\$\s*[0-9][0-9.,]*", " ", clean)
    clean = re.sub(r"\b\d{1,2}\s*%\b", " ", clean)

    # Limpieza de signos raros de RSS.
    clean = re.sub(r"[#|•·]+", " ", clean)
    clean = re.sub(r"[()\[\]{}]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" -–—:|\t\n\r")
    return clean or title.strip()


def parse_mxn(value: Any) -> Optional[float]:
    if value is None:
        return None
    s = str(value).replace("\xa0", " ").strip()
    match = re.search(r"\$?\s*([0-9][0-9.,]*)", s)
    if not match:
        return None

    number = match.group(1)
    # Mexico normalmente usa coma para miles y punto para decimales.
    number = number.replace(",", "")
    try:
        return float(number)
    except ValueError:
        return None


def money(value: Optional[float]) -> str:
    if value is None:
        return "N/D"
    return f"${value:,.0f} MXN"


def extract_discount_percent(text: str) -> Optional[int]:
    if not text:
        return None
    patterns = [
        r"(\d{1,2})\s*%\s*(?:OFF|off|Off|descuento|DESCUENTO)",
        r"(?:OFF|off|descuento|DESCUENTO)\s*(\d{1,2})\s*%",
        r"-(\d{1,2})\s*%",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            value = int(m.group(1))
            if 1 <= value <= 95:
                return value
    return None


def extract_mlm_id(url: str) -> Optional[str]:
    """Extrae IDs tipo MLM-123456789 o MLM123456789."""
    m = re.search(r"MLM-?\d+", url or "")
    if not m:
        return None
    raw = m.group(0)
    return raw if "-" in raw else raw.replace("MLM", "MLM-", 1)


def is_probable_ml_product_url(url: str) -> bool:
    """Acepta URLs reales de producto en ML México.

    Mercado Libre puede devolver productos como:
    - https://articulo.mercadolibre.com.mx/MLM-123...
    - https://www.mercadolibre.com.mx/.../p/MLM123...
    - https://www.mercadolibre.com.mx/.../MLM-123...

    El bot anterior solo aceptaba www.mercadolibre.com.mx/.../MLM-123,
    por eso se brincaba resultados válidos.
    """
    if not url:
        return False
    url = urllib.parse.unquote(html.unescape(url))
    if "mercadolibre.com.mx" not in url:
        return False
    blocked = [
        "listado.mercadolibre.com.mx",
        "ayuda.mercadolibre.com.mx",
        "www.mercadolibre.com.mx/c/",
        "www.mercadolibre.com.mx/ofertas",
        "www.mercadolibre.com.mx/tiendas",
    ]
    if any(b in url for b in blocked):
        return False
    return bool(re.search(r"(?:/MLM-\d+|/p/MLM\d+|MLM-\d+)", url))


def clean_ml_url(url: str) -> str:
    url = urllib.parse.unquote(html.unescape(url)).split("#")[0]
    # En URLs de producto, quitamos query de tracking antes de meter afiliado.
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))


def add_affiliate_params(url: str, affiliate_id: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    query.update(ML_AFFILIATE_PARAMS)
    query["matt_tool"] = affiliate_id
    new_query = urllib.parse.urlencode(query)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def category_emoji(title: str) -> str:
    t = title.lower()
    categories = [
        ("📱", ["celular", "smartphone", "iphone", "android", "galaxy", "motorola", "xiaomi", "redmi", "honor", "pixel"]),
        ("💻", ["laptop", "notebook", "computadora", "pc", "monitor", "teclado", "mouse", "ssd", "ram", "procesador", "tablet", "ipad"]),
        ("📺", ["tv", "televisión", "television", "pantalla", "smart tv", "roku", "chromecast", "proyector"]),
        ("🎧", ["audífono", "audifono", "audífonos", "audifonos", "headset", "bocina", "soundbar", "barra de sonido", "bluetooth", "sony wh", "airpods"]),
        ("👟", ["tenis", "zapato", "zapatos", "nike", "adidas", "puma", "sneakers", "calzado", "sandalias", "botas"]),
        ("🏠", ["hogar", "cocina", "sarten", "sartén", "licuadora", "cafetera", "aspiradora", "mueble", "colchón", "colchon", "silla", "mesa", "closet"]),
        ("🧸", ["juguete", "lego", "barbie", "muñeca", "muneca", "bebé", "bebe", "niño", "niña", "nino", "nina", "hot wheels"]),
        ("💊", ["vitamina", "suplemento", "farmacia", "medicina", "medicamento", "protector solar", "bloqueador", "crema", "shampoo"]),
        ("⚽", ["balón", "balon", "fútbol", "futbol", "gym", "ejercicio", "mancuerna", "bicicleta", "deportivo", "proteína", "proteina"]),
        ("🚁", ["drone", "dron", "cuadricóptero", "cuadricoptero", "helicóptero", "helicoptero"]),
    ]
    for emoji, keywords in categories:
        if any(k in t for k in keywords):
            return emoji
    return "🛒"


def build_message(offer: MLOffer) -> str:
    title = html.escape(offer.product_title.upper()[:130])
    affiliate = html.escape(offer.affiliate_link, quote=True)

    current = offer.current_price
    original = offer.original_price
    discount = offer.discount_percent

    if current is not None and original is not None and original > current:
        savings = original - current
    else:
        savings = None

    emoji = category_emoji(offer.product_title)
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    discount_line = f"🔴 <b>-{discount}% DE DESCUENTO</b>" if discount else "🔴 <b>DESCUENTO DISPONIBLE</b>"
    previous_line = f"<s>Precio anterior: {money(original)}</s>" if original else ""
    savings_line = f"💵 Ahorras: <b>{money(savings)}</b>" if savings else ""
    shipping_line = "✅ ENVIO GRATIS" if offer.free_shipping else ""

    lines = [
        f"{emoji} <b>{title}</b>",
        "",
        f"👉 <a href=\"{affiliate}\">VER OFERTA EN MERCADO LIBRE</a>",
        "",
        discount_line,
        f"🔥 <b>Precio Oferta: {money(current)}</b>",
        previous_line,
        savings_line,
        shipping_line,
        "",
        f"🕐 {now}",
        "",
        "#OfertasML #MercadoLibre #Descuentos #AhorraHoy",
    ]

    return "\n".join([line for line in lines if line != ""])


# =========================
# BOT PRINCIPAL
# =========================
class MercadoLibreTelegramBot:
    def __init__(self) -> None:
        load_dotenv_local()
        self.telegram_token = require_env("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = require_env("TELEGRAM_CHAT_ID")
        self.affiliate_id = require_env("ML_AFFILIATE_ID")

        self.published_ids: Set[str] = self.load_published_ids()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def load_published_ids(self) -> Set[str]:
        if not os.path.exists(PUBLISHED_FILE):
            return set()
        try:
            with open(PUBLISHED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return set(str(x) for x in data)
            if isinstance(data, dict) and isinstance(data.get("published_ids"), list):
                return set(str(x) for x in data["published_ids"])
        except Exception as e:
            logger.warning("No pude leer %s: %s", PUBLISHED_FILE, e)
        return set()

    def save_published_ids(self) -> None:
        try:
            with open(PUBLISHED_FILE, "w", encoding="utf-8") as f:
                json.dump(sorted(self.published_ids), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("No pude guardar %s: %s", PUBLISHED_FILE, e)

    def start_browser(self) -> None:
        logger.info("Iniciando Chromium con Playwright...")
        self.playwright = sync_playwright().start()
        headless = os.getenv("HEADLESS", "true").strip().lower() not in {"0", "false", "no"}
        self.browser = self.playwright.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
            ],
        )
        self.context = self.browser.new_context(
            user_agent=REAL_CHROME_UA,
            locale="es-MX",
            timezone_id="America/Mexico_City",
            viewport={"width": 1366, "height": 768},
            device_scale_factor=1,
            is_mobile=False,
            has_touch=False,
        )
        self.context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['es-MX', 'es', 'en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            """
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(25000)

    def close_browser(self) -> None:
        logger.info("Cerrando navegador...")
        for obj in [self.context, self.browser]:
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass

    def validate_telegram_token(self) -> None:
        """Valida el token antes de gastar tiempo buscando ofertas."""
        if self.telegram_token == "PEGA_AQUI_TU_TOKEN_ACTUAL":
            raise RuntimeError(
                "Falta pegar el token real en .env. Ejecuta configurar_bot.bat y pega el token actual de BotFather."
            )

        url = f"https://api.telegram.org/bot{self.telegram_token}/getMe"
        response = requests.get(url, timeout=20)
        try:
            data = response.json()
        except Exception:
            data = {"ok": False, "description": response.text}

        if response.status_code == 401:
            raise RuntimeError(
                "Telegram error 401 Unauthorized: el TELEGRAM_BOT_TOKEN está mal, incompleto o fue revocado. "
                "Ejecuta configurar_bot.bat y pega el token actual de BotFather."
            )
        if not response.ok or not data.get("ok"):
            raise RuntimeError(f"No pude validar el token de Telegram: {data}")

        bot_username = data.get("result", {}).get("username", "sin_username")
        logger.info("Token de Telegram válido. Bot detectado: @%s", bot_username)

    def telegram_api(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"https://api.telegram.org/bot{self.telegram_token}/{method}"
        response = requests.post(url, data=payload, timeout=30)
        try:
            data = response.json()
        except Exception:
            data = {"ok": False, "description": response.text}

        if response.status_code == 401:
            raise RuntimeError(
                "Telegram error 401 Unauthorized: token inválido/revocado. "
                "Actualiza TELEGRAM_BOT_TOKEN con configurar_bot.bat."
            )
        if not response.ok or not data.get("ok"):
            raise RuntimeError(f"Telegram error {response.status_code}: {data}")
        return data

    def send_welcome(self) -> None:
        text = "Ofertas Mercado Libre"
        try:
            self.telegram_api("sendMessage", {
                "chat_id": self.telegram_chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            })
            logger.info("Mensaje de bienvenida enviado.")
        except Exception as e:
            logger.warning("No pude enviar bienvenida: %s", e)

    def send_offer(self, offer: MLOffer) -> bool:
        message = build_message(offer)

        if offer.image_url:
            try:
                # sendPhoto permite caption con HTML; si Telegram rechaza imagen/caption, caemos a sendMessage.
                self.telegram_api("sendPhoto", {
                    "chat_id": self.telegram_chat_id,
                    "photo": offer.image_url,
                    "caption": message[:1024],
                    "parse_mode": "HTML",
                })
                logger.info("Oferta enviada con foto: %s", offer.product_title)
                return True
            except Exception as e:
                logger.warning("Falló sendPhoto, intento sendMessage. Error: %s", e)

        try:
            self.telegram_api("sendMessage", {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": "false",
            })
            logger.info("Oferta enviada como texto: %s", offer.product_title)
            return True
        except Exception as e:
            logger.error("No pude enviar oferta a Telegram: %s", e)
            return False

    def fetch_rss_items(self) -> List[RSSItem]:
        items: List[RSSItem] = []
        for url in RSS_URLS:
            try:
                response = requests.get(url, headers=RSS_HEADERS, timeout=25)
                response.raise_for_status()
                root = ET.fromstring(response.content)

                for item in root.findall(".//item"):
                    title = (item.findtext("title") or "").strip()
                    link = (item.findtext("link") or "").strip()
                    guid = (item.findtext("guid") or link or title).strip()
                    pub_date = (item.findtext("pubDate") or "").strip()

                    if not title:
                        continue
                    if "mercado libre" not in title.lower() and "mercadolibre" not in title.lower():
                        continue

                    items.append(RSSItem(title=title, link=link, guid=guid, pub_date=pub_date))

                logger.info("RSS leído: %s | items ML acumulados: %s", url, len(items))
            except Exception as e:
                logger.warning("Error leyendo RSS %s: %s", url, e)
        return items

    def find_first_ml_link_from_search(self, query_title: str) -> Optional[str]:
        clean_query = normalize_title_for_ml_search(query_title)
        query = urllib.parse.quote(clean_query.replace(" ", "-"), safe="")
        search_url = f"https://listado.mercadolibre.com.mx/{query}"

        logger.info("Buscando en Mercado Libre: %s", search_url)
        logger.info("Query limpia: %s", clean_query)
        try:
            self.page.goto(search_url, wait_until="domcontentloaded", timeout=35000)
            try:
                self.page.wait_for_load_state("networkidle", timeout=12000)
            except PlaywrightTimeoutError:
                pass
            self.page.wait_for_timeout(2000)

            # ML cambia clases seguido. Por eso tomamos todos los anchors y filtramos por URL.
            links = self.page.eval_on_selector_all(
                "a[href]",
                """
                els => els.map(a => ({
                    href: a.href || a.getAttribute('href') || '',
                    text: (a.innerText || a.getAttribute('title') || '').trim()
                })).filter(x => x.href)
                """,
            )

            for item in links:
                href = item.get("href", "") if isinstance(item, dict) else str(item)
                if is_probable_ml_product_url(href):
                    final_url = clean_ml_url(href)
                    logger.info("Link ML encontrado: %s", final_url)
                    return final_url

            rendered_html = self.page.content()
            patterns = [
                r"https?://articulo\.mercadolibre\.com\.mx/MLM-\d+[^\"'<>\s]*",
                r"https?://www\.mercadolibre\.com\.mx/[^\"'<>\s]+/p/MLM\d+[^\"'<>\s]*",
                r"https?://www\.mercadolibre\.com\.mx/[^\"'<>\s]*MLM-\d+[^\"'<>\s]*",
            ]
            for pattern in patterns:
                m = re.search(pattern, rendered_html)
                if m:
                    final_url = clean_ml_url(m.group(0))
                    logger.info("Link ML encontrado en HTML: %s", final_url)
                    return final_url

            # Si ML mostró captcha/bloqueo, lo dejamos claro en logs.
            page_text = ""
            try:
                page_text = self.page.inner_text("body", timeout=3000).lower()
            except Exception:
                pass
            if any(word in page_text for word in ["captcha", "no eres un robot", "robot", "verifica"]):
                logger.warning("Mercado Libre parece mostrar verificación/captcha. Prueba HEADLESS=false en .env.")

        except Exception as e:
            logger.warning("Error buscando producto ML: %s", e)
        return None

    def extract_offer_from_product_page(self, product_link: str, source_title: str) -> Optional[MLOffer]:
        try:
            self.page.goto(product_link, wait_until="domcontentloaded", timeout=35000)
            try:
                self.page.wait_for_load_state("networkidle", timeout=12000)
            except PlaywrightTimeoutError:
                pass
            self.page.wait_for_timeout(1000)

            data = self.page.evaluate(
                """
                () => {
                    const text = document.body ? document.body.innerText : '';
                    const getText = (selector) => {
                        const el = document.querySelector(selector);
                        return el ? el.innerText.trim() : '';
                    };
                    const getAttr = (selector, attr) => {
                        const el = document.querySelector(selector);
                        return el ? el.getAttribute(attr) : '';
                    };
                    const absoluteUrl = (url) => {
                        if (!url) return '';
                        if (url.startsWith('//')) return 'https:' + url;
                        try { return new URL(url, location.href).href; } catch { return url; }
                    };
                    const badImageText = (value) => /env[ií]o gratis|primera compra|banner|publicidad|promo|promoci[oó]n|meli\+|mercado pago|mercado cr[eé]dito|full|logo|sprite|icon/i.test(value || '');
                    const isGoodImageUrl = (url) => {
                        url = absoluteUrl(url || '');
                        if (!url) return false;
                        if (!/mlstatic\.com/i.test(url)) return false;
                        if (/data:image|logo|sprite|icon|banner|advertising|ads|payment/i.test(url)) return false;
                        if (!/\/D_|\/D_NQ|D_Q_NP|D_NQ_NP/i.test(url)) return false;
                        return true;
                    };
                    const imageCandidates = [];
                    const pushCandidate = (url, score, source, el = null) => {
                        url = absoluteUrl(url || '').split('?')[0];
                        if (!isGoodImageUrl(url)) return;
                        const alt = el ? `${el.getAttribute('alt') || ''} ${el.getAttribute('title') || ''} ${el.getAttribute('aria-label') || ''}` : '';
                        const parentText = el && el.parentElement ? (el.parentElement.innerText || '').slice(0, 180) : '';
                        const label = `${alt} ${parentText}`;
                        if (badImageText(label) || badImageText(url)) return;

                        if (el) {
                            const w = el.naturalWidth || el.width || 0;
                            const h = el.naturalHeight || el.height || 0;
                            if (w && h) {
                                const ratio = w / h;
                                // Evita banners horizontales como "ENVÍO GRATIS EN TU PRIMERA COMPRA".
                                if (ratio > 3.2 || ratio < 0.18) return;
                                if (w < 120 || h < 120) score -= 20;
                                if (w >= 400 && h >= 400) score += 20;
                            }
                        }
                        imageCandidates.push({ url, score, source });
                    };

                    // 1) Meta tags suelen traer la imagen principal real del producto.
                    pushCandidate(getAttr('meta[property="og:image"]', 'content'), 120, 'og:image');
                    pushCandidate(getAttr('meta[name="twitter:image"]', 'content'), 115, 'twitter:image');
                    pushCandidate(getAttr('link[rel="image_src"]', 'href'), 110, 'image_src');

                    // 2) Selectores típicos de la galería del producto en Mercado Libre.
                    const selectors = [
                        'img.ui-pdp-image.ui-pdp-gallery__figure__image',
                        '.ui-pdp-gallery__figure img',
                        '.ui-pdp-image',
                        'img[data-zoom]',
                        'picture img',
                        'figure img'
                    ];
                    selectors.forEach((selector, idx) => {
                        document.querySelectorAll(selector).forEach((img, pos) => {
                            pushCandidate(img.currentSrc || img.src || img.getAttribute('data-src') || img.getAttribute('data-zoom'), 100 - idx * 5 - pos, selector, img);
                        });
                    });

                    // 3) Último respaldo: todas las imágenes, pero filtrando banners/logos.
                    Array.from(document.images).forEach((img, pos) => {
                        pushCandidate(img.currentSrc || img.src || img.getAttribute('data-src'), 40 - pos, 'all-images', img);
                    });

                    imageCandidates.sort((a, b) => b.score - a.score);
                    const bestImage = imageCandidates.length ? imageCandidates[0].url : '';

                    const moneyTexts = Array.from(document.querySelectorAll('.andes-money-amount'))
                        .map(el => el.innerText.replace(/\s+/g, ' ').trim())
                        .filter(Boolean);
                    return {
                        title: getText('h1.ui-pdp-title') || getAttr('meta[property="og:title"]', 'content') || document.title || '',
                        currentText: getText('.ui-pdp-price__second-line .andes-money-amount') || getText('[data-testid="price-part"] .andes-money-amount'),
                        originalText: getText('.ui-pdp-price__original-value .andes-money-amount') || getText('.andes-money-amount--previous'),
                        discountText: getText('.andes-money-amount__discount') || getText('.ui-pdp-price__second-line .andes-money-amount__discount'),
                        priceMeta: getAttr('meta[itemprop="price"]', 'content'),
                        moneyTexts,
                        imageUrl: bestImage,
                        imageSource: imageCandidates.length ? imageCandidates[0].source : '',
                        imageCandidates: imageCandidates.slice(0, 5),
                        text
                    };
                }
                """
            )

            product_title = (data.get("title") or source_title).strip()
            product_title = re.sub(r"\s+\|\s*MercadoLibre.*$", "", product_title, flags=re.I)
            product_title = re.sub(r"\s+", " ", product_title).strip()

            current_price = parse_mxn(data.get("priceMeta")) or parse_mxn(data.get("currentText"))
            original_price = parse_mxn(data.get("originalText"))
            discount_percent = extract_discount_percent(data.get("discountText") or "") or extract_discount_percent(data.get("text") or "")

            money_texts = data.get("moneyTexts") or []
            if current_price is None and money_texts:
                current_price = parse_mxn(money_texts[0])

            if original_price is None and len(money_texts) >= 2:
                candidates = [parse_mxn(x) for x in money_texts]
                candidates = [x for x in candidates if x is not None]
                higher = [x for x in candidates if current_price is not None and x > current_price]
                if higher:
                    original_price = max(higher)

            if discount_percent is None and current_price and original_price and original_price > current_price:
                discount_percent = round((1 - current_price / original_price) * 100)

            if original_price is None and current_price and discount_percent:
                original_price = current_price / (1 - discount_percent / 100)

            image_url = data.get("imageUrl") or None
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url
            if image_url:
                logger.info("Imagen producto elegida [%s]: %s", data.get("imageSource") or "sin-fuente", image_url)
            else:
                logger.info("No encontré imagen de producto válida para: %s", product_title)

            full_text = (data.get("text") or "").lower()
            free_shipping = "envío gratis" in full_text or "envio gratis" in full_text

            affiliate_link = add_affiliate_params(product_link, self.affiliate_id)

            return MLOffer(
                source_title=source_title,
                product_title=product_title,
                product_link=product_link,
                affiliate_link=affiliate_link,
                current_price=current_price,
                original_price=original_price,
                discount_percent=discount_percent,
                image_url=image_url,
                free_shipping=free_shipping,
            )
        except Exception as e:
            logger.warning("Error extrayendo oferta del producto: %s", e)
            return None

    def process_item(self, item: RSSItem) -> bool:
        rss_key = "rss:" + stable_hash(item.guid or item.link or item.title)
        if rss_key in self.published_ids:
            logger.info("RSS ya procesado, salto: %s", item.title)
            return False

        product_link = self.find_first_ml_link_from_search(item.title)
        if not product_link:
            logger.info("No encontré link ML para: %s", item.title)
            return False

        product_key = extract_mlm_id(product_link) or stable_hash(product_link)
        if product_key in self.published_ids:
            logger.info("Producto ya publicado, salto: %s", product_key)
            self.published_ids.add(rss_key)
            self.save_published_ids()
            return False

        offer = self.extract_offer_from_product_page(product_link, item.title)
        if not offer:
            return False

        # Evita publicar cosas donde no pudimos confirmar descuento/precio.
        if not offer.discount_percent or offer.discount_percent <= 0 or not offer.current_price:
            logger.info("Sin descuento/precio confirmado, salto: %s", item.title)
            self.published_ids.add(rss_key)
            self.save_published_ids()
            return False

        sent = self.send_offer(offer)
        if sent:
            self.published_ids.add(rss_key)
            self.published_ids.add(product_key)
            self.save_published_ids()
            return True
        return False

    def run_cycle(self) -> None:
        logger.info("=== Inicia ciclo de búsqueda ===")
        sent_count = 0
        try:
            items = self.fetch_rss_items()
            for item in items:
                if sent_count >= MAX_OFFERS_PER_CYCLE:
                    break
                try:
                    if self.process_item(item):
                        sent_count += 1
                        # Pausa suave para no parecer licuadora industrial pegándole al sitio.
                        time.sleep(2)
                except Exception:
                    logger.error("Error procesando item: %s\n%s", item.title, traceback.format_exc())
                    continue
        except Exception:
            logger.error("Error general en ciclo:\n%s", traceback.format_exc())
        finally:
            logger.info("=== Ciclo terminado. Ofertas enviadas: %s ===", sent_count)


def main() -> None:
    # Carga variables desde .env antes de leer TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID y ML_AFFILIATE_ID.
    load_dotenv_local()

    bot = MercadoLibreTelegramBot()
    try:
        bot.validate_telegram_token()
        bot.start_browser()
        bot.send_welcome()

        # Primer ciclo inmediato al iniciar.
        bot.run_cycle()

        schedule.every(CYCLE_MINUTES).minutes.do(bot.run_cycle)
        logger.info("Bot corriendo cada %s minutos. Ctrl+C para detener.", CYCLE_MINUTES)

        while True:
            schedule.run_pending()
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Bot detenido por el usuario.")
    finally:
        bot.close_browser()


if __name__ == "__main__":
    main()
