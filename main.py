import os
import json
import time
import re
import logging
import requests
from html import escape
from urllib.parse import urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
DATA_FILE = "fiyatlar.json"

MIN_FIYAT = 1000.0
MAX_FIYAT = 300000.0
SAYFA_SAYISI = 6

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)

MAGAZALAR = {
    "Teknosa": "https://www.n11.com/arama?q=teknosa",
    "Mediamarkt": "https://www.n11.com/arama?q=mediamarkt",
    "Braunshop": "https://www.n11.com/arama?q=braunshop",
    "Korayspor": "https://www.n11.com/arama?q=korayspor",
    "Skechers": "https://www.n11.com/arama?q=skechers",
    "Karaca": "https://www.n11.com/arama?q=karaca",
    "Tefal": "https://www.n11.com/arama?q=tefal",
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


def telegram_mesaj_gonder(mesaj):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning("Telegram token veya chat ID eksik.")
        return False

    api_url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            api_url,
            data={
                "chat_id": CHAT_ID,
                "text": mesaj,
                "parse_mode": "HTML"
            },
            timeout=15
        )
        response.raise_for_status()

        sonuc = response.json()
        if not sonuc.get("ok"):
            logging.error("Telegram API hatası: %s", sonuc)
            return False

        return True

    except (requests.RequestException, ValueError) as hata:
        logging.error("Telegram gönderme hatası: %s", hata)
        return False


def eski_fiyatlari_yukle():
    if not os.path.exists(DATA_FILE):
        return {}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            veri = json.load(f)

        return veri if isinstance(veri, dict) else {}

    except (OSError, json.JSONDecodeError) as hata:
        logging.error("Fiyat dosyası okunamadı: %s", hata)
        return {}


def yeni_fiyatlari_kaydet(veri):
    gecici = DATA_FILE + ".tmp"

    try:
        with open(gecici, "w", encoding="utf-8") as f:
            json.dump(veri, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())

        os.replace(gecici, DATA_FILE)
        return True

    except OSError as hata:
        logging.error("Fiyat dosyası kaydedilemedi: %s", hata)
        return False


def fiyat_metnini_temizle(metin):
    if not metin:
        return None

    metin = str(metin).replace("\xa0", " ").strip()

    if re.search(
        r"taksit|aylık|ayda|başlayan",
        metin,
        re.IGNORECASE
    ):
        return None

    # Türkçe fiyat: 4.299,90 / 4299,90 / 4.299
    eslesme =
