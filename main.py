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
DETAY_SAYFASI_DOGRULA = True

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


def fiyat_metnini_temizle(value):
    if value is None:
        return None

    s = str(value).replace("\xa0", " ").strip()
    if re.search(
        r"taksit|aylık|ayda|başlayan|indirim oranı",
        s, re.I
    ):
        return None

    m = re.search(
        r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})+|\d+)"
        r"(?:,(\d{1,2}))?\s*(?:TL|TRY|₺)",
        s, re.I
    )

    if not m:
        m = re.fullmatch(
            r"\s*(\d{1,3}(?:[.\s]\d{3})+|\d+)"
            r"(?:,(\d{1,2}))?\s*",
            s
        )
        if not m:
            return None

    whole = m.group(1).replace(".", "").replace(" ", "")
    decimal = m.group(2)
    raw = whole + ("." + decimal if decimal else "")

    try:
        price = float(raw)
    except ValueError:
        return None

    if MIN_FIYAT <= price <= MAX_FIYAT:
        return round(price, 2)
    return None


def urun_url_temizle(url):
    p = urlsplit(urljoin("https://www.n11.com/", url))
    return urlunsplit((
        p.scheme, p.netloc, p.path.rstrip("/"), "", ""
    ))


def urun_id_al(url):
    """
    n11 ürün URL'lerinden değişmeyen benzersiz kısmı (veya ID'yi) ayıklar.
    Örn: https://www.n11.com/urun/ornek-urun-123456 -> ornek-urun-123456
    """
    temiz_url = urun_url_temizle(url)
    path = urlsplit(temiz_url).path.rstrip("/")
    # Eğer path içinde /urun/ geçiyorsa son parçayı alalım
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


def urun_adi_bul(kart, link, url):
    for attr in ("data-product-name", "title", "aria-label"):
        name = link.get(attr, "")
        if urun_adi_gecerli(name):
            return re.sub(r"\s+", " ", name).strip()[:180]

    selectors = [
        "[itemprop='name']",
        "[data-testid*='product-name']",
        "[data-testid*='product-title']",
        "[class*='productName']",
        "[class*='product-name']",
        "[class*='productTitle']",
        "[class*='product-title']",
        "[class*='proName']",
        "[class*='prdName']"
    ]

    for selector in selectors:
        for el in kart.select(selector):
            name = (
                el.get("content")
                or el.get("title")
                or metin_al(el)
            )
            if urun_adi_gecerli(name):
                return re.sub(r"\s+", " ", name).strip()[:180]

    for img in kart.find_all("img"):
        name = img.get("alt", "")
        if urun_adi_gecerli(name):
            return re.sub(r"\s+", " ", name).strip()[:180]

    for el in kart.select("h1, h2, h3"):
        name = metin_al(el)
        if urun_adi_gecerli(name):
            return name[:180]

    slug = url_slug_adi(url)
    return slug if urun_adi_gecerli(slug) else None


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

        candidate = link
        for parent in link.parents:
            if getattr(parent, "name", None) in ("body", "html"):
                break
            text = metin_al(parent)
            if len(text) <= 1600 and parent.find(
                "a", href=re.compile(r"/urun/")
            ):
                candidate = parent
                break

        results.append((candidate, link, url))

    return results


def sepet_fiyati_bul(container):
    candidates = []

    for el in container.find_all(
        ["span", "div", "p", "strong", "b", "ins"]
    ):
        text = metin_al(el)

        if len(text) > 180:
            continue

        if not re.search(
            r"sepette|sepet fiyatı|sepete özel",
            text, re.I
        ):
            continue

        price = fiyat_metnini_temizle(text)
        if price is not None:
            candidates.append((len(text), price))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    return None


def normal_fiyati_bul(container):
    candidates = []

    for el in container.find_all(
        ["ins", "span", "div", "p", "strong", "b"]
    ):
        classes = " ".join(el.get("class", []))
        itemprop = el.get("itemprop", "")
        text = metin_al(el)

        if len(text) > 100:
            continue

        if re.search(
            r"sepette|sepet fiyatı|kupon|taksit|indirim oranı",
            text, re.I
        ):
            continue

        if not (
            re.search(
                r"price|fiyat|amount|sale|current|newprice",
                classes, re.I
            )
            or itemprop == "price"
        ):
            continue

        raw = el.get("content") or text
        price = fiyat_metnini_temizle(raw)

        if price is not None:
            candidates.append((len(text), price))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    return None


def jsonld_urun_verisi(soup):
    names = []
    prices = []

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue

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

            typ = obj.get("@type", "")
            if isinstance(typ, list):
                typ = " ".join(typ)

            if "Product" not in str(typ):
                continue

            name = obj.get("name")
            if urun_adi_gecerli(name):
                names.append(name.strip())

            offers = obj.get("offers", [])
            offers = offers if isinstance(offers, list) else [offers]

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                raw = offer.get("price") or offer.get("lowPrice")
                if raw is not None:
                    price = fiyat_metnini_temizle(str(raw))
                    if price is not None:
                        prices.append(price)

    return names, prices


def detay_sayfasi_dogrula(url):
    try:
        response = SESSION.get(url, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as e:
        logging.warning("Detay sayfası açılamadı: %s (%s)", url, e)
        return None, None

    names, prices = jsonld_urun_verisi(soup)

    h1 = soup.select_one("h1")
    title = metin_al(h1) if h1 else None

    if not urun_adi_gecerli(title):
        title = names[0] if names else None

    slug_words = set(re.findall(r"[a-z0-9]+", url_slug_adi(url).lower()))
    title_words = set(re.findall(r"[a-z0-9]+", (title or "").lower()))
    meaningful = {w for w in slug_words if len(w) > 2}

    if meaningful and title_words:
        overlap = len(meaningful & title_words) / len(meaningful)
        if overlap < 0.35:
            logging.warning("Ürün adı/URL uyuşmuyor: %s", url)
            return None, None

    basket_price = sepet_fiyati_bul(soup)
    if basket_price is not None:
        return title, basket_price

    if prices:
        return title, min(prices)

    logging.warning("Detay sayfasında yapılandırılmış fiyat yok: %s", url)
    return title, None


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
                    logging.warning(
                        "%s sayfa %s: ürün bulunamadı.",
                        magaza, sayfa
                    )
                    time.sleep(1)
                    continue

                for kart, link, product_url in cards:
                    u_id = urun_id_al(product_url)
                    if u_id in gorulen:
                        continue
                    gorulen.add(u_id)

                    old_record = onceki_kaydi_bul(eski, u_id)
                    name = urun_adi_bul(kart, link, product_url)

                    price = sepet_fiyati_bul(kart)
                    is_basket = price is not None

                    if price is None:
                        price = normal_fiyati_bul(kart)

                    detail_name, detail_price = detay_sayfasi_dogrula(
                        product_url
                    )

                    if detail_name and urun_adi_gecerli(detail_name):
                        name = detail_name

                    if detail_price is not None:
                        price = detail_price
                        is_basket = False

                    if not urun_adi_gecerli(name):
                        old_name = old_record.get("urun_adi", "")
                        name = (
                            old_name
                            if urun_adi_gecerli(old_name)
                            else None
                        )

                    if not name or price is None:
                        logging.warning(
                            "Ad/fiyat doğrulanamadı, kayıt atlandı: %s",
                            product_url
                        )
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
                            "Şüpheli fiyat düşüşü; bildirim ve kayıt atlandı: "
                            "%s | %.2f -> %.2f",
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
                            basket_note = (
                                "\n🎟️ <i>Sepette indirimli fiyat</i>"
                                if is_basket else ""
                            )

                            message = (
                                f"🔥 <b>FİYAT DÜŞTÜ!</b>{basket_note}\n\n"
                                f"🏷️ <b>Ürün:</b> {escape(name)}\n"
                                f"🏪 <b>Arama:</b> {escape(magaza)}\n"
                                f"📉 <b>Eski:</b> {old_price:.2f} TL\n"
                                f"💰 <b>Yeni:</b> {price:.2f} TL\n"
                                f"✅ <b>İndirim:</b> %{drop * 100:.1f}\n"
                                f"💵 <b>Fark:</b> {difference:.2f} TL\n\n"
                                f'<a href="{escape(product_url, quote=True)}">'
                                f"Ürüne Git</a>"
                            )
                            if telegram_mesaj_gonder(message):
                                son_bildirim_fiyati = price
                            else:
                                bildirim_atilsin = False

                    current_son_bildirim = son_bildirim_fiyati if not bildirim_atilsin else price
                    if not bildirim_atilsin:
                        current_son_bildirim = old_record.get("son_bildirim_fiyati")

                    guncel[u_id] = {
                        "fiyat": price,
                        "urun_adi": name,
                        "arama_grubu": magaza,
                        "url": product_url,
                        "son_bildirim_fiyati": current_son_bildirim,
                        "son_guncelleme": time.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    }

                    toplam += 1

                logging.info(
                    "%s sayfa %s işlendi; toplam %s ürün.",
                    magaza, sayfa, toplam
                )
                time.sleep(1)

            except requests.RequestException as e:
                logging.error(
                    "%s sayfa %s hatası: %s", magaza, sayfa, e
                )
                time.sleep(1)

        logging.info("%s tamamlandı: %s ürün.", magaza, toplam)

    if yeni_fiyatlari_kaydet(guncel):
        logging.info(
            "Tarama tamamlandı. Kayıt sayısı: %s", len(guncel)
        )
    else:
        logging.error("Fiyatlar dosyaya kaydedilemedi.")


if __name__ == "__main__":
    main()
