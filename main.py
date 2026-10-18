import os
import json
import time
import re
import logging
import requests
from html import escape
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
DATA_FILE = "fiyatlar.json"

MIN_FIYAT = 500.0
MAX_FIYAT = 300000.0
SAYFA_SAYISI = 6

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)

MAGAZALAR = {
    "Teknosa": "https://www.n11.com/arama?q=teknosa",
    "n11": "https://www.n11.com/arama?q=n11",
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
                data = json.loads(script_text)
                stack = data if isinstance(data, list) else [data]
                while stack:
                    obj = stack.pop()
                    if isinstance(obj, list):
                        stack.extend(obj)
                        continue
                    if not isinstance(obj, dict):
                        continue
                    if isinstance(obj.get("@graph"), list):
                        stack.extend(obj["@graph"])

                    if not title and obj.get("@type") == "Product" and obj.get("name"):
                        t_candidate = obj.get("name")
                        if urun_adi_gecerli(t_candidate):
                            title = t_candidate.strip()

                    # Satıcı bilgisini JSON-LD içerisinden yakalama
                    if not seller_name:
                        seller = obj.get('seller') or obj.get('brand')
                        if isinstance(seller, dict):
                            s_name = seller.get('name')
                            if s_name:
                                seller_name = str(s_name).strip()
                        elif isinstance(seller, str):
                            seller_name = seller.strip()

                    offers = obj.get('offers')
                    if offers:
                        if isinstance(offers, list) and len(offers) > 0:
                            first_offer = offers[0]
                            if first_offer.get('price'):
                                val = float(first_offer.get('price'))
                                if val > 0:
                                    price = val
                            # offer içerisindeki seller kontrolü
                            off_seller = first_offer.get('seller')
                            if isinstance(off_seller, dict) and off_seller.get('name'):
                                seller_name = str(off_seller.get('name')).strip()
                        elif isinstance(offers, dict):
                            if offers.get('price'):
                                val = float(offers.get('price'))
                                if val > 0:
                                    price = val
                            off_seller = offers.get('seller')
                            if isinstance(off_seller, dict) and off_seller.get('name'):
                                seller_name = str(off_seller.get('name')).strip()
                if price > 0:
                    break
            except Exception:
                pass

        # Eğer JSON-LD'den satıcı bulunamadıysa HTML içindeki mağaza/satıcı elementlerine bak
        if not seller_name:
            seller_el = soup.select_one(".proSellerName, .sellerName, [class*='seller'], [class*='store']")
            if seller_el:
                seller_name = metin_al(seller_el)

        if not title:
            h1 = soup.select_one("h1")
            if h1:
                title = metin_al(h1)

        if not urun_adi_gecerli(title):
            slug = url_slug_adi(url)
            title = slug if urun_adi_gecerli(slug) else "N11 Ürünü"

        if MIN_FIYAT <= price <= MAX_FIYAT:
            return title, round(price, 2), seller_name

    except Exception as e:
        logging.warning("Detay sayfası açılamadı: %s (%s)", url, e)

    return None, None, None


def onceki_kaydi_bul(data, u_id):
    old = data.get(u_id)
    return old if isinstance(old, dict) else {}


def main():
    logging.info("Fiyat taraması başladı.")

    eski = eski_fiyatlari_yukle()
    guncel = dict(eski)

    for magaza, base_url in MAGAZALAR.items():
        logging.info("[%s] taranıyor.", magaza)
        gorulen = set()
        toplam = 0

        for sayfa in range(1, SAYFA_SAYISI + 1):
            url = f"{base_url}&pg={sayfa}"

            try:
                response = SESSION.get(url, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                cards = kartlari_bul(soup)

                if not cards:
                    logging.warning("%s sayfa %s: ürün bulunamadı.", magaza, sayfa)
                    time.sleep(1)
                    continue

                for link, product_url in cards:
                    u_id = urun_id_al(product_url)
                    if u_id in gorulen:
                        continue
                    gorulen.add(u_id)

                    old_record = onceki_kaydi_bul(eski, u_id)

                    name, price, seller = detay_sayfasi_dogrula(product_url)

                    if not name or price is None:
                        logging.warning("Ad/fiyat doğrulanamadı, kayıt atlandı: %s", product_url)
                        continue

                    # Mağaza Adı Eşleşme Kontrolü (Örn: 'Teknosa' araması yapıldıysa satıcıda 'Teknosa' geçmeli)
                    # Not: "n11" genel arama grubu olduğu için tüm satıcıları kabul edebilir.
                    if magaza.lower() != "n11" and seller:
                        if magaza.lower() not in seller.lower():
                            logging.info("Satıcı uyuşmadı (Aranan: %s, Satan: %s), atlandı: %s", magaza, seller, product_url)
                            continue

                    try:
                        old_price = float(old_record.get("fiyat"))
                    except (TypeError, ValueError):
                        old_price = None

                    try:
                        son_bildirim_fiyati = float(old_record.get("son_bildirim_fiyati"))
                    except (TypeError, ValueError):
                        son_bildirim_fiyati = None

                    if (
                        old_price
                        and price < old_price
                        and (old_price - price) / old_price > 0.60
                    ):
                        logging.warning(
                            "Şüpheli fiyat düşüşü; bildirim ve kayıt atlandı: %s | %.2f -> %.2f",
                            name, old_price, price
                        )
                        continue

                    bildirim_atilsin = False
                    if old_price is not None:
                        if price < old_price:
                            if son_bildirim_fiyati is None or price < son_bildirim_fiyati:
                                bildirim_atilsin = True

                    if bildirim_atilsin:
                        difference = old_price - price
                        drop = difference / old_price

                        if difference >= 1:
                            message = (
                                f"🔥 <b>FİYAT DÜŞTÜ!</b>\n\n"
                                f"🏷️ <b>Ürün:</b> {escape(name)}\n"
                                f"🏪 <b>Mağaza:</b> {escape(seller or magaza)}\n"
                                f"📉 <b>Eski:</b> {old_price:.2f} TL\n"
                                f"💰 <b>Yeni:</b> {price:.2f} TL\n"
                                f"✅ <b>İndirim:</b> %{drop * 100:.1f}\n"
                                f"💵 <b>Fark:</b> {difference:.2f} TL\n\n"
                                f'<a href="{escape(product_url, quote=True)}">Ürüne Git</a>'
                            )
                            if telegram_mesaj_gonder(message):
                                son_bildirim_fiyati = price
                            else:
                                bildirim_atilsin = False

                    current_son_bildirim = son_bildirim_fiyati if bildirim_atilsin else old_record.get("son_bildirim_fiyati")

                    guncel[u_id] = {
                        "fiyat": price,
                        "urun_adi": name,
                        "arama_grubu": magaza,
                        "gercek_satici": seller or magaza,
                        "url": product_url,
                        "son_bildirim_fiyati": current_son_bildirim,
                        "son_guncelleme": time.strftime("%Y-%m-%d %H:%M:%S")
                    }

                    toplam += 1

                logging.info("%s sayfa %s işlendi; toplam %s ürün.", magaza, sayfa, toplam)
                time.sleep(1)

            except requests.RequestException as e:
                logging.error("%s sayfa %s hatası: %s", magaza, sayfa, e)
                time.sleep(1)

        logging.info("%s tamamlandı: %s ürün.", magaza, toplam)

    if yeni_fiyatlari_kaydet(guncel):
        logging.info("Tarama tamamlandı. Kayıt sayısı: %s", len(guncel))
    else:
        logging.error("Fiyatlar dosyaya kaydedilemedi.")


if __name__ == "__main__":
    main()
