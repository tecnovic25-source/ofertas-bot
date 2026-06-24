import html
import json
import logging
import os
import random
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import requests
import schedule
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================
RSS_FEEDS = [
    "https://www.promodescuentos.com/rss/hot",
    "https://www.promodescuentos.com/rss/new",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# ============================================================
# MODELOS
# ============================================================
@dataclass
class RSSItem:
    title: str
    link: str
    guid: str
    description: str = ""


@dataclass
class ProductOffer:
    source_id: str
    source_title: str
    clean_title: str
    ml_url: str
    affiliate_url: str
    image_url: Optional[str]
    current_price: Optional[float]
    original_price: Optional[float]
    discount_percent: Optional[int]
    free_shipping: bool


# ============================================================
# HELPERS DE ENTORNO
# ============================================================
def load_dotenv_if_exists(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None or str(value).strip() == "":
        raise RuntimeError(f"Falta configurar la variable de entorno: {name}")
    return str(value).strip()


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logging.warning("Variable %s inválida: %r. Uso default=%s", name, raw, default)
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "si", "sí", "y"}


# ============================================================
# NORMALIZACIÓN Y EXTRACCIÓN
# ============================================================
def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def strip_html(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_spaces(text)


def remove_accents_basic(text: str) -> str:
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ü": "u",
        "ñ": "n",
        "Á": "A",
        "É": "E",
        "Í": "I",
        "Ó": "O",
        "Ú": "U",
        "Ü": "U",
        "Ñ": "N",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def mentions_mercado_libre(item: RSSItem) -> bool:
    haystack = remove_accents_basic(f"{item.title} {item.description} {item.link}").lower()
    return (
        "mercado libre" in haystack
        or "mercadolibre" in haystack
        or "mercado-libre" in haystack
        or "meli" in haystack
    )


def clean_promodescuentos_title(title: str) -> str:
    text = normalize_spaces(title)

    # Quita temperatura de Promodescuentos: 156° —, 123º -, etc.
    text = re.sub(r"^\s*[-+]?\d+\s*[°º]\s*[-–—:]*\s*", "", text, flags=re.I)

    # Quita menciones de tienda al inicio o en medio.
    text = re.sub(r"\bMercado\s*Libre\b\s*[:\-–—]*\s*", "", text, flags=re.I)
    text = re.sub(r"\bMercadolibre\b\s*[:\-–—]*\s*", "", text, flags=re.I)
    text = re.sub(r"\bML\b\s*[:\-–—]*\s*", "", text, flags=re.I)

    # Quita prefijos comunes de descuentos y cupones que ensucian la búsqueda.
    text = re.sub(r"\b(?:cup[oó]n|c[oó]digo|descuento|oferta|promo|promoci[oó]n)\b\s*[:\-–—]*\s*", "", text, flags=re.I)
    text = re.sub(r"\b\d{1,2}\s*%\s*(?:off|de descuento|dto|desc)?\b", "", text, flags=re.I)
    text = re.sub(r"\b\d+x\d+\b", "", text, flags=re.I)

    # Quita precios del título para que ML busque por producto, no por ruido.
    text = re.sub(r"\$\s?\d[\d,.]*", "", text)

    # Limpia paréntesis demasiado promocionales.
    text = re.sub(r"\((?:[^)]*(?:env[ií]o|gratis|cup[oó]n|prime|cashback)[^)]*)\)", "", text, flags=re.I)

    # Quita caracteres raros, deja letras/números básicos y símbolos útiles.
    text = re.sub(r"[^\w\s%\-.,+/()áéíóúÁÉÍÓÚñÑüÜ]", " ", text)
    text = normalize_spaces(text.strip(" -–—:,."))
    return text[:140]


def generate_search_queries(item: RSSItem) -> List[str]:
    base = clean_promodescuentos_title(item.title)
    queries: List[str] = []

    def add(q: str) -> None:
        q = normalize_spaces(q).strip(" -–—:,.()")
        if len(q) >= 5 and q.lower() not in [x.lower() for x in queries]:
            queries.append(q[:140])

    add(base)

    # Variantes sin frases que a veces rompen los resultados.
    q2 = re.sub(r"\b(?:con|para|compatible|color|modelo|incluye|paquete|set)\b.*$", "", base, flags=re.I)
    add(q2)

    # Si trae coma, prueba solo el primer segmento.
    if "," in base:
        add(base.split(",", 1)[0])

    # Versión sin acentos.
    add(remove_accents_basic(base))

    # Último fallback: descripción sin HTML, corta.
    desc = strip_html(item.description)
    desc = clean_promodescuentos_title(desc)
    if desc and len(desc) > len(base):
        add(desc[:120])

    return queries[:4]


def parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    text = html.unescape(text)
    # Captura $1,234.56, 1.234,56, $ 999, etc.
    matches = re.findall(r"\$\s*([0-9][0-9.,]*)", text)
    if not matches:
        return None
    raw = matches[0]
    raw = raw.replace(" ", "")

    # Formato MX común: 1,299.00
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        # Si la coma parece decimal, úsala decimal; si no, miles.
        if len(raw.split(",")[-1]) == 2:
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")

    try:
        return float(raw)
    except ValueError:
        return None


def parse_discount(text: str) -> Optional[int]:
    if not text:
        return None
    patterns = [
        r"(\d{1,2})\s*%\s*(?:OFF|off|Off)",
        r"(\d{1,2})\s*%\s*(?:de\s*)?descuento",
        r"-(\d{1,2})\s*%",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            value = int(match.group(1))
            if 1 <= value <= 95:
                return value
    return None


def discount_from_prices(current: Optional[float], original: Optional[float]) -> Optional[int]:
    if not current or not original or original <= current:
        return None
    pct = round((original - current) * 100 / original)
    if 1 <= pct <= 95:
        return int(pct)
    return None


def money(value: Optional[float]) -> str:
    if value is None:
        return "N/D"
    return f"${value:,.0f} MXN"


def append_affiliate_params(url: str, affiliate_id: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update(
        {
            "matt_tool": affiliate_id,
            "matt_source": "telegram",
            "matt_campaign": "ofertas",
        }
    )
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def product_key(url: str, current_price: Optional[float]) -> str:
    match = re.search(r"\b(MLM\d+)\b", url, flags=re.I)
    base = match.group(1).upper() if match else url.split("?")[0].rstrip("/")
    if current_price:
        return f"{base}:{int(current_price)}"
    return base


# ============================================================
# RSS
# ============================================================
def fetch_rss_items(max_items_per_feed: int) -> List[RSSItem]:
    results: List[RSSItem] = []
    seen: Set[str] = set()

    for feed_url in RSS_FEEDS:
        try:
            resp = SESSION.get(feed_url, timeout=25)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")[:max_items_per_feed]
            count_before = len(results)

            for node in items:
                title = normalize_spaces(node.findtext("title") or "")
                link = normalize_spaces(node.findtext("link") or "")
                guid = normalize_spaces(node.findtext("guid") or link or title)
                description = node.findtext("description") or ""
                description = strip_html(description)

                if not title:
                    continue
                unique = guid or link or title
                if unique in seen:
                    continue
                seen.add(unique)
                results.append(RSSItem(title=title, link=link, guid=unique, description=description))

            logging.info(
                "RSS leído: %s | nuevos items: %s | acumulados: %s",
                feed_url,
                len(results) - count_before,
                len(results),
            )
        except Exception as exc:
            logging.warning("No pude leer RSS %s: %s", feed_url, exc)

    return results


# ============================================================
# TELEGRAM
# ============================================================
class TelegramClient:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.api_base = f"https://api.telegram.org/bot{token}"

    def _post(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.api_base}/{method}"
        resp = SESSION.post(url, data=payload, timeout=35)
        try:
            data = resp.json()
        except Exception:
            data = {"ok": False, "description": resp.text[:300]}
        if not data.get("ok"):
            raise RuntimeError(f"Telegram error {resp.status_code}: {data}")
        return data

    def validate(self) -> None:
        resp = SESSION.get(f"{self.api_base}/getMe", timeout=20)
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Token de Telegram inválido: {data}")
        logging.info("Bot validado en Telegram: @%s", data["result"].get("username"))

    def send_message(self, text: str) -> None:
        self._post(
            "sendMessage",
            {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": "false",
            },
        )

    def send_photo(self, photo_url: str, caption: str) -> None:
        self._post(
            "sendPhoto",
            {
                "chat_id": self.chat_id,
                "photo": photo_url,
                "caption": caption[:1020],
                "parse_mode": "HTML",
            },
        )

    def send_offer(self, offer: ProductOffer) -> None:
        message = build_telegram_message(offer)
        if offer.image_url:
            try:
                self.send_photo(offer.image_url, message)
                return
            except Exception as exc:
                logging.warning("Falló sendPhoto, intento sendMessage. Error: %s", exc)
        self.send_message(message)


# ============================================================
# MENSAJE
# ============================================================
def category_emoji(title: str) -> str:
    t = remove_accents_basic(title.lower())
    categories = [
        ("📱", ["iphone", "samsung", "celular", "smartphone", "xiaomi", "motorola", "redmi", "watch", "apple watch"]),
        ("💻", ["laptop", "notebook", "pc", "monitor", "teclado", "mouse", "ssd", "ram", "tablet", "impresora"]),
        ("📺", ["tv", "television", "pantalla", "smart tv", "proyector"]),
        ("🎧", ["audifonos", "audífonos", "bocina", "jbl", "soundbar", "headset", "bluetooth"]),
        ("👟", ["tenis", "zapatos", "sneaker", "nike", "adidas", "puma", "ropa", "playera", "pantalon"]),
        ("🏠", ["cocina", "sarten", "almohada", "colchon", "silla", "mesa", "organizador", "recipiente", "hogar", "licuadora", "cafetera"]),
        ("🧸", ["juguete", "lego", "muñeca", "hot wheels", "nintendo", "switch", "pokemon", "playmobil"]),
        ("💊", ["vitamina", "suplemento", "proteina", "farmacia", "salud"]),
        ("⚽", ["balon", "futbol", "deporte", "gym", "mancuerna", "bicicleta"]),
        ("🚁", ["drone", "dron", "rc", "control remoto"]),
    ]
    for emoji, words in categories:
        if any(word in t for word in words):
            return emoji
    return "🛒"


def build_telegram_message(offer: ProductOffer) -> str:
    title = html.escape(offer.clean_title.upper())
    emoji = category_emoji(offer.clean_title)
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    discount = offer.discount_percent
    current = offer.current_price
    original = offer.original_price
    savings = None
    if current and original and original > current:
        savings = original - current

    lines = [
        f"{emoji} <b>{title}</b>",
        "",
        f"👉 <a href=\"{html.escape(offer.affiliate_url)}\">VER OFERTA EN MERCADO LIBRE</a>",
        "",
    ]

    if discount:
        lines.append(f"🔴 <b>-{discount}% DE DESCUENTO</b>")
    else:
        lines.append("🔴 <b>OFERTA DESTACADA</b>")

    if current:
        lines.append(f"🔥 <b>Precio Oferta: {money(current)}</b>")
    if original and current and original > current:
        lines.append(f"<s>Precio anterior: {money(original)}</s>")
    if savings:
        lines.append(f"💵 Ahorras: <b>{money(savings)}</b>")
    if offer.free_shipping:
        lines.append("✅ ENVIO GRATIS")

    lines.extend(
        [
            "",
            f"🕐 {now}",
            "",
            "#OfertasML #MercadoLibre #Descuentos #AhorraHoy",
        ]
    )
    return "\n".join(lines)


# ============================================================
# PLAYWRIGHT / MERCADO LIBRE
# ============================================================
class MercadoLibreScraper:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None

    def start(self) -> None:
        logging.info("Iniciando Chromium con Playwright...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1366,768",
            ],
        )
        self.context = self.browser.new_context(
            user_agent=USER_AGENT,
            locale="es-MX",
            timezone_id="America/Mexico_City",
            viewport={"width": 1366, "height": 768},
        )
        self.context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

    def close(self) -> None:
        try:
            if self.context:
                self.context.close()
        finally:
            try:
                if self.browser:
                    self.browser.close()
            finally:
                if self.playwright:
                    self.playwright.stop()

    def search_offer(self, item: RSSItem, affiliate_id: str, min_discount: int) -> Optional[ProductOffer]:
        queries = generate_search_queries(item)
        if not queries:
            return None

        for query in queries:
            try:
                offer = self._search_with_query(item, query, affiliate_id, min_discount)
                if offer:
                    return offer
            except Exception as exc:
                logging.warning("Falló búsqueda '%s': %s", query, exc)

        return None

    def _search_with_query(self, item: RSSItem, query: str, affiliate_id: str, min_discount: int) -> Optional[ProductOffer]:
        assert self.context is not None
        search_url = "https://listado.mercadolibre.com.mx/" + urllib.parse.quote(query.replace(" ", "-"))
        logging.info("Buscando en Mercado Libre: %s", search_url)
        logging.info("Query limpia: %s", query)

        page = self.context.new_page()
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=35000)
            page.wait_for_timeout(random.randint(1200, 2600))

            body_text = page.locator("body").inner_text(timeout=10000)[:5000]
            if re.search(r"captcha|robot|verifica", body_text, flags=re.I):
                logging.warning("Mercado Libre parece pedir captcha/verificación.")
                return None

            cards = page.evaluate(
                """
                () => {
                  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
                  const abs = (u) => {
                    try { return new URL(u, location.href).href; } catch(e) { return null; }
                  };
                  const cardNodes = Array.from(document.querySelectorAll(
                    'li.ui-search-layout__item, div.ui-search-result__wrapper, div.poly-card, div.ui-search-result, .andes-card'
                  ));
                  return cardNodes.slice(0, 12).map(card => {
                    const anchors = Array.from(card.querySelectorAll('a[href]'));
                    let link = null;
                    for (const a of anchors) {
                      const href = abs(a.getAttribute('href'));
                      if (!href) continue;
                      if (href.includes('mercadolibre.com.mx') && /MLM|\/p\//i.test(href)) {
                        link = href.split('#')[0];
                        break;
                      }
                    }
                    const titleNode = card.querySelector('h2, h3, .ui-search-item__title, .poly-component__title, .poly-component__title-wrapper');
                    const title = clean(titleNode ? titleNode.innerText : (anchors[0] ? anchors[0].innerText : ''));
                    const text = clean(card.innerText);
                    const imgs = Array.from(card.querySelectorAll('img')).map(img =>
                      img.getAttribute('data-src') || img.getAttribute('src') || img.getAttribute('srcset') || ''
                    ).filter(Boolean);
                    return {link, title, text, imgs};
                  }).filter(x => x.link && x.title);
                }
                """
            )

            if not cards:
                logging.info("No encontré cards útiles para: %s", query)
                return None

            for card in cards[:5]:
                link = self._normalize_ml_url(card.get("link") or "")
                if not link:
                    continue

                card_text = card.get("text") or ""
                card_current = parse_price(card_text)
                card_discount = parse_discount(card_text)
                card_free_shipping = bool(re.search(r"env[ií]o\s+gratis", card_text, flags=re.I))
                card_image = self._best_image_from_list(card.get("imgs") or [])

                detail = self._extract_product_detail(link)

                current = detail.get("current_price") or card_current
                original = detail.get("original_price")
                discount = detail.get("discount_percent") or card_discount
                if not discount:
                    discount = discount_from_prices(current, original)
                if not discount:
                    discount = parse_discount(item.title + " " + item.description)

                if discount and discount < min_discount:
                    logging.info("Salto por descuento bajo (%s%%): %s", discount, link)
                    continue

                if not current:
                    logging.info("Salto porque no encontré precio actual: %s", link)
                    continue

                # Si no hay descuento/original, normalmente es mal candidato. Lo saltamos para mantener calidad.
                if not discount and not original:
                    logging.info("Salto porque no encontré descuento claro: %s", link)
                    continue

                product_title = detail.get("title") or card.get("title") or query
                product_title = clean_promodescuentos_title(product_title)
                image = detail.get("image_url") or card_image
                free_shipping = bool(detail.get("free_shipping") or card_free_shipping)

                logging.info("Link ML encontrado: %s", link)
                if image:
                    logging.info("Imagen producto elegida: %s", image)

                return ProductOffer(
                    source_id=item.guid,
                    source_title=item.title,
                    clean_title=product_title,
                    ml_url=link,
                    affiliate_url=append_affiliate_params(link, affiliate_id),
                    image_url=image,
                    current_price=current,
                    original_price=original,
                    discount_percent=discount,
                    free_shipping=free_shipping,
                )

            return None
        except PlaywrightTimeoutError:
            logging.warning("Timeout buscando: %s", query)
            return None
        finally:
            page.close()

    def _normalize_ml_url(self, url: str) -> Optional[str]:
        if not url:
            return None
        url = html.unescape(url)
        parsed = urllib.parse.urlparse(url)
        if "mercadolibre.com.mx" not in parsed.netloc:
            return None

        # Quita tracking pesado de ML antes de poner nuestro afiliado.
        clean = urllib.parse.urlunparse(parsed._replace(query="", fragment=""))
        if re.search(r"MLM\d+", clean, flags=re.I) or "/p/" in clean:
            return clean
        return None

    def _extract_product_detail(self, url: str) -> Dict[str, Any]:
        assert self.context is not None
        page = self.context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=35000)
            page.wait_for_timeout(random.randint(1300, 2600))

            data = page.evaluate(
                """
                () => {
                  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
                  const pickAttr = (selectors, attr) => {
                    for (const sel of selectors) {
                      const el = document.querySelector(sel);
                      if (el && el.getAttribute(attr)) return el.getAttribute(attr);
                    }
                    return null;
                  };
                  const titleEl = document.querySelector('h1.ui-pdp-title, h1, meta[property="og:title"]');
                  let title = '';
                  if (titleEl) title = titleEl.tagName === 'META' ? titleEl.getAttribute('content') : titleEl.innerText;

                  const imageCandidates = [];
                  const metaImgs = [
                    'meta[property="og:image"]',
                    'meta[property="og:image:secure_url"]',
                    'meta[name="twitter:image"]'
                  ];
                  for (const sel of metaImgs) {
                    const val = pickAttr([sel], 'content');
                    if (val) imageCandidates.push(val);
                  }
                  document.querySelectorAll('img').forEach(img => {
                    const src = img.getAttribute('data-zoom') || img.getAttribute('data-src') || img.getAttribute('src') || '';
                    if (src) imageCandidates.push(src);
                  });

                  const bodyText = clean(document.body ? document.body.innerText : '');
                  const priceArea = clean((document.querySelector('.ui-pdp-price, .ui-pdp-price__main-container, .ui-pdp-container__row--price') || document.body).innerText || '');
                  const fullText = priceArea + ' ' + bodyText.slice(0, 5000);

                  return {
                    title: clean(title),
                    fullText,
                    imageCandidates,
                    freeShipping: /env[ií]o\s+gratis/i.test(bodyText)
                  };
                }
                """
            )

            text = data.get("fullText") or ""
            current, original = self._extract_prices_from_product_text(text)
            discount = parse_discount(text)
            if not discount:
                discount = discount_from_prices(current, original)

            image = self._best_image_from_list(data.get("imageCandidates") or [])

            return {
                "title": normalize_spaces(data.get("title") or ""),
                "current_price": current,
                "original_price": original,
                "discount_percent": discount,
                "image_url": image,
                "free_shipping": bool(data.get("freeShipping")),
            }
        except Exception as exc:
            logging.warning("No pude extraer detalle de producto %s: %s", url, exc)
            return {}
        finally:
            page.close()

    def _extract_prices_from_product_text(self, text: str) -> Tuple[Optional[float], Optional[float]]:
        if not text:
            return None, None
        prices = []
        for raw in re.findall(r"\$\s*[0-9][0-9.,]*", text):
            val = parse_price(raw)
            if val and val > 1:
                prices.append(val)

        # El primer precio visible suele ser el actual, pero en ML a veces se repite muchas veces.
        unique: List[float] = []
        for p in prices:
            if all(abs(p - x) > 0.01 for x in unique):
                unique.append(p)

        if not unique:
            return None, None

        current = unique[0]
        original = None

        # Si hay algún precio mayor al actual por al menos 5%, probablemente es precio anterior.
        greater = [p for p in unique[1:] if p > current * 1.05]
        if greater:
            original = max(greater)

        return current, original

    def _best_image_from_list(self, candidates: Sequence[str]) -> Optional[str]:
        cleaned: List[str] = []
        for img in candidates:
            if not img:
                continue
            img = img.split(" ")[0].strip()
            img = html.unescape(img)
            if img.startswith("//"):
                img = "https:" + img
            if not img.startswith("http"):
                continue
            if "mlstatic.com" not in img:
                continue
            low = img.lower()
            if any(bad in low for bad in ["sprite", "logo", "icon", "brand", "banner", "warning", "placeholder"]):
                continue
            if not re.search(r"/D_[A-Z0-9_\-]+", img):
                continue
            # Evita banners promocionales conocidos; deja fotos de producto.
            if "envio" in low or "shipping" in low or "full" in low and "D_NQ" not in img:
                continue
            if img not in cleaned:
                cleaned.append(img)

        if not cleaned:
            return None

        # Priorizamos imágenes de producto de alta calidad.
        def score(url: str) -> int:
            s = 0
            if "D_NQ_NP" in url:
                s += 10
            if "D_Q_NP" in url:
                s += 8
            if "-O." in url or "_O." in url:
                s += 3
            if re.search(r"_\d{5,}", url):
                s += 2
            return s

        cleaned.sort(key=score, reverse=True)
        return cleaned[0]


# ============================================================
# MEMORIA
# ============================================================
def load_published(path: str) -> Set[str]:
    file_path = Path(path)
    if not file_path.exists():
        return set()
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(x) for x in data}
        if isinstance(data, dict):
            # Compatibilidad por si antes se guardó como dict.
            return {str(x) for x in data.get("published", [])}
    except Exception as exc:
        logging.warning("No pude leer %s: %s", path, exc)
    return set()


def save_published(path: str, published: Set[str]) -> None:
    file_path = Path(path)
    file_path.write_text(json.dumps(sorted(published), ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# BOT PRINCIPAL
# ============================================================
class OfertasMLBot:
    def __init__(self):
        load_dotenv_if_exists()
        self.telegram_token = env("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = env("TELEGRAM_CHAT_ID")
        self.affiliate_id = env("ML_AFFILIATE_ID")

        self.max_offers = env_int("MAX_OFFERS_PER_CYCLE", 12)
        self.cycle_minutes = env_int("CYCLE_MINUTES", 10)
        self.max_items_per_feed = env_int("MAX_RSS_ITEMS_PER_FEED", 45)
        self.max_candidates = env_int("MAX_CANDIDATES_PER_CYCLE", 40)
        self.min_discount = env_int("MIN_DISCOUNT_PERCENT", 5)
        self.only_ml_mentioned = env_bool("ONLY_ML_MENTIONED", True)
        self.run_once = env_bool("RUN_ONCE", False)
        self.headless = env_bool("HEADLESS", True)
        self.send_welcome = env_bool("SEND_WELCOME", False)
        self.published_file = env("PUBLISHED_FILE", "published_offers.json")

        self.telegram = TelegramClient(self.telegram_token, self.telegram_chat_id)
        self.scraper = MercadoLibreScraper(headless=self.headless)
        self.published = load_published(self.published_file)

    def start(self) -> None:
        self.telegram.validate()
        self.scraper.start()
        try:
            if self.send_welcome:
                try:
                    self.telegram.send_message("Ofertas Mercado Libre")
                    logging.info("Mensaje de bienvenida enviado.")
                except Exception as exc:
                    logging.warning("No pude enviar bienvenida: %s", exc)

            self.run_cycle()
            if self.run_once:
                return

            logging.info("Bot corriendo cada %s minutos. Ctrl+C para detener.", self.cycle_minutes)
            schedule.every(self.cycle_minutes).minutes.do(self.run_cycle)
            while True:
                schedule.run_pending()
                time.sleep(1)
        finally:
            save_published(self.published_file, self.published)
            self.scraper.close()

    def run_cycle(self) -> None:
        logging.info("=== Inicia ciclo de búsqueda ===")
        sent = 0
        processed = 0

        items = fetch_rss_items(self.max_items_per_feed)

        if self.only_ml_mentioned:
            filtered = [item for item in items if mentions_mercado_libre(item)]
            logging.info("Filtro Mercado Libre: %s de %s items", len(filtered), len(items))
        else:
            filtered = items
            logging.info("Filtro Mercado Libre desactivado: procesaré %s items", len(filtered))

        # Prioriza hot/new que mencionan ML, pero mezcla un poquito para no quedarse siempre en los mismos.
        random.shuffle(filtered)

        for item in filtered:
            if sent >= self.max_offers:
                break
            if processed >= self.max_candidates:
                break

            processed += 1

            rough_id = str(item.guid or item.link or item.title)
            if rough_id in self.published:
                logging.info("RSS ya procesado, salto: %s", item.title)
                continue

            try:
                offer = self.scraper.search_offer(item, self.affiliate_id, self.min_discount)
                if not offer:
                    logging.info("No encontré oferta válida para: %s", item.title)
                    self.published.add(rough_id)
                    continue

                key = product_key(offer.ml_url, offer.current_price)
                if key in self.published:
                    logging.info("Producto ya publicado, salto: %s", key)
                    self.published.add(rough_id)
                    continue

                self.telegram.send_offer(offer)
                self.published.add(key)
                self.published.add(rough_id)
                sent += 1
                logging.info("Oferta enviada (%s/%s): %s", sent, self.max_offers, offer.clean_title)
                time.sleep(random.uniform(1.0, 2.2))
            except Exception as exc:
                logging.error("No pude enviar/procesar oferta '%s': %s", item.title, exc)

        save_published(self.published_file, self.published)
        logging.info("=== Ciclo terminado. Ofertas enviadas: %s | candidatos revisados: %s ===", sent, processed)


def main() -> None:
    bot = OfertasMLBot()
    bot.start()


if __name__ == "__main__":
    main()
