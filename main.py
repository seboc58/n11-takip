import os
import json
import time
import re
import logging
import requests
from html import escape
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote, quote_plus
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
DATA_FILE = "fiyatlar.json"

MIN_FIYAT = 300.0
MAX_FIYAT = 300000.0
SAYFA_SAYISI = 6

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)

MAGAZALAR = {
    "Teknosa": "https://www.n11.com/arama?q=teknosa",
    "n11": "https://www.n11.com/arama?q=n11",
    "Philips": "https://www.n11.com/arama?q=philips",
    "Mediamarkt": "https://www.n11.com/arama?q=mediamarkt",
    "Braunshop": "https://www.n11.com/arama?q=braunshop",
    "Jack&Jones": "https://www.n11.com/arama?q=jack-jones",
    "Skechers": "https://www.n11.com/arama?q=skechers",
    "Karaca": "https://www.n11.com/arama?q=karaca",
    "Tefal": "https://www.n11.com/arama?q=tefal",
    "Brita": "https://www.n11.com/arama?q=brita",
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.n11.com/"
})

MOBILE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}


def telegram_mesaj_gonder(mesaj):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning("Telegram token veya chat ID eksik.")
        return False

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": mesaj,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            logging.error("Telegram API hatası: %s", data)
        return bool(data.get("ok"))
    except (requests.RequestException, ValueError) as e:
        logging.error("Telegram gönderme hatası: %s", e)
        return False


def eski_fiyatlari_yukle():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as e:
        logging.error("Fiyat dosyası okunamadı: %s", e)
        return {}


def yeni_fiyatlari_kaydet(data):
    tmp = DATA_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, DATA_FILE)
        return True
    except OSError as e:
        logging.error("Fiyat dosyası kaydedilemedi: %s", e)
        return False


def metin_al(element):
    if not element:
        return ""
    return " ".join(element.get_text(" ", strip=True).split())


def urun_url_temizle(url):
    p = urlsplit(urljoin("https://www.n11.com/", url))
    return urlunsplit((
        p.scheme, p.netloc, p.path.rstrip("/"), "", ""
    ))


def urun_id_al(url):
    temiz_url = urun_url_temizle(url)
    path = urlsplit(temiz_url).path.rstrip("/")
    parts = path.split("/")
    if "urun" in parts:
        try:
            idx = parts.index("urun")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        except ValueError:
            pass
    return path


def urun_adi_gecerli(name):
    if not name:
        return False

    name = re.sub(r"\s+", " ", str(name)).strip()
    upper = name.upper()

    if len(name) < 6 or len(name) > 300:
        return False

    invalid = [
        "POPÜLER SAYFALAR", "POPULER SAYFALAR",
        "ÜRÜN ADI BULUNAMADI", "SEPETE EKLE",
        "HEMEN AL", "ÜRÜNÜ İNCELE", "ÜCRETSİZ KARGO",
        "FIRSAT ÜRÜNLERİ", "ÇOK SATANLAR", "GİRİŞ YAP"
    ]

    if any(x in upper for x in invalid):
        return False

    if re.fullmatch(r"[\d.,\s₺€$]+", name):
        return False

    if re.search(r"\b(TL|TRY|USD|EUR)\b|₺|€|\$", name, re.I):
        return False

    return True


def url_slug_adi(url):
    path = unquote(urlsplit(url).path)
    slug = path.rstrip("/").split("/")[-1]
    slug = re.sub(r"-\d+$", "", slug)
    return re.sub(r"-+", " ", slug).strip()


def kartlari_bul(soup):
    links = soup.select('a[href*="/urun/"]')
    results = []
    seen = set()

    for link in links:
        url = urun_url_temizle(link.get("href", ""))
        u_id = urun_id_al(url)
        if u_id in seen:
            continue
        seen.add(u_id)
        results.append((link, url))

    return results


def detay_sayfasi_dogrula(url):
    mobile_url = url.replace("www.n11.com", "m.n11.com")
    price = 0.0
    title = None
    seller_name = None

    try:
        response = requests.get(mobile_url, headers=MOBILE_HEADERS, timeout=30)
        if response.status_code != 200:
            return None, None, None

        soup = BeautifulSoup(response.text, 'html.parser')

        for script in soup.find_all('script', type='application/ld+json'):
            try:
                script_text = script.string or script.get_text()
                if not script_text:
                    continue
                data = json.loads(script
