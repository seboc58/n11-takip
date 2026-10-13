import os
import json
import time
import re
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

MAGAZALAR = {
    "Teknosa": "https://www.n11.com/arama?q=teknosa",
    "N11": "https://www.n11.com/arama?q=n11",
    "Mediamarkt": "https://www.n11.com/arama?q=mediamarkt",
    "Braunshop": "https://www.n11.com/arama?q=braunshop",
    "Jack&Jones": "https://www.n11.com/arama?q=jack-jones",
    "Korayspor": "https://www.n11.com/arama?q=korayspor",
    "Skechers": "https://www.n11.com/arama?q=skechers",
    "Karaca": "https://www.n11.com/arama?q=karaca",
    "Tefal": "https://www.n11.com/arama?q=tefal",
}


def telegram_mesaj_gonder(mesaj):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram gönderilemedi: TELEGRAM_TOKEN veya CHAT_ID eksik.")
        return False
    try:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(
            api_url,
            data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "HTML"},
            timeout=15,
        )
        if not r.ok:
            print(f"Telegram HTTP hatası: {r.status_code} - {r.text[:300]}")
            return False
        try:
            sonuc = r.json()
            return bool(sonuc.get("ok"))
        except Exception:
            return True
    except Exception as e:
        print(f"Telegram gönderme hatası: {e}")
        return False


def eski_fiyatlari_yukle():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                veri = json.load(f)
                return veri if isinstance(veri, dict) else {}
        except Exception as e:
            print(f"Fiyat dosyası okunamadı: {e}")
    return {}


def yeni_fiyatlari_kaydet(veri):
    try:
        gecici = DATA_FILE + ".tmp"
        with open(gecici, "w", encoding="utf-8") as f:
            json.dump(veri, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(gecici, DATA_FILE)
        print(f"Fiyat hafızası kaydedildi: {len(veri)} ürün.")
    except Exception as e:
        print(f"Fiyat dosyası kaydedilemedi: {e}")


def fiyat_metnini_temizle(metin):
    if not metin:
        return 0.0

    metin = str(metin).replace("\xa0", " ").strip()
    if re.search(r"taksit|aylık|ayda|başlayan|seçeneği", metin, re.I):
        return 0.0

    match = re.search(
        r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})+|\d+)(?:,\d{1,2})?(?!\d)",
        metin,
    )
    if not match:
        return 0.0

    raw_val = match.group(0).replace(" ", "")
    try:
        if "," in raw_val:
            raw_val = raw_val.replace(".", "").replace(",", ".")
        elif "." in raw_val and len(raw_val.rsplit(".", 1)[-1]) == 3:
            raw_val = raw_val.replace(".", "")
        val = float(raw_val)
        return round(val, 2) if MIN_FIYAT <= val <= MAX_FIYAT else 0.0
    except Exception:
        return 0.0


def urun_url_temizle(url):
    url = urljoin("https://www.n11.com/", url)
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), "", ""))


def metin_al(element):
    if not element:
        return ""
    return " ".join(element.get_text(" ", strip=True).split())


def urun_adi_gecerli_mi(ad):
    ad = (ad or "").strip()
    if len(ad) < 4:
        return False
    if re.fullmatch(r"[\d.,\s]+\s*(?:TL|₺)", ad, re.I):
        return False
    if re.fullmatch(r"(?:TL|₺)?\s*[\d.,\s]+", ad, re.I):
        return False
    return bool(re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]", ad))


def urun_adi_bul(kart, link_tag, urun_url=""):
    for etiket in ("h3", "h2", "h4"):
        for el in kart.find_all(etiket):
            ad = metin_al(el)
            if urun_adi_gecerli_mi(ad):
                return ad[:180]

    title = (link_tag.get("title") or "").strip()
    if urun_adi_gecerli_mi(title):
        return title[:180]

    img = kart.find("img", alt=True)
    if img:
        alt = (img.get("alt") or "").strip()
        if urun_adi_gecerli_mi(alt):
            return alt[:180]

    link_text = metin_al(link_tag)
    if urun_adi_gecerli_mi(link_text):
        return link_text[:180]

    slug = urlsplit(urun_url or link_tag.get("href", "")).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"-\d+$", "", slug)
    slug = re.sub(r"[-_]+", " ", slug).strip()
    if slug:
        return slug[:180].title()
    return "Ürün"


def kupon_metni_bul(kart):
    adaylar = []
    for el in kart.find_all(
        ["span", "div", "p", "em", "strong"],
        class_=re.compile(
            r"(coupon|kupon|campaign|kampanya|basket|sepette|discount|indirim|badge)",
            re.I,
        ),
    ):
        metin = metin_al(el)
        if not metin or len(metin) < 3:
            continue
        if re.search(r"kupon|sepette|sepet fiyat|kampanya|indirim", metin, re.I):
            adaylar.append(metin)

    if not adaylar:
        tum = metin_al(kart)
        for parca in re.findall(
            r"(?:SEPETTE[^\n]{0,40}|Kupon[^\n]{0,40}|%[0-9]+[^\n]{0,20}indirim)",
            tum,
            re.I,
        ):
            adaylar.append(parca.strip())

    if not adaylar:
        return None
    adaylar = sorted(set(adaylar), key=len)
    return adaylar[0][:120]


def urun_fiyati_bul(kart):
    liste_fiyat = 0.0
    sepette_fiyat = 0.0

    alanlar = kart.find_all(
        ["ins", "span", "div", "p"],
        class_=re.compile(r"(price|fiyat|newPrice|salePrice|currentPrice|new|amount|value)", re.I),
    )
    for alan in alanlar:
        metin = metin_al(alan)
        if re.search(r"sepette|sepet fiyat", metin, re.I):
            continue
        if re.search(r"taksit|aylık|ayda|başlayan|seçeneği", metin, re.I):
            continue
        f = fiyat_metnini_temizle(metin)
        if f > 0:
            liste_fiyat = f
            break

    alanlar = kart.
