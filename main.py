
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

    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

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

    eslesme = re.search(
        r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})+|\d+)"
        r"(?:,\d{1,2})?(?!\d)",
        metin
    )

    if not eslesme:
        return None

    ham = eslesme.group(0).replace(" ", "")

    if "," in ham:
        ham = ham.replace(".", "").replace(",", ".")
    elif "." in ham and len(ham.rsplit(".", 1)[-1]) == 3:
        ham = ham.replace(".", "")

    try:
        fiyat = float(ham)
    except ValueError:
        return None

    if MIN_FIYAT <= fiyat <= MAX_FIYAT:
        return round(fiyat, 2)

    return None


def urun_url_temizle(url):
    url = urljoin("https://www.n11.com/", url)
    parca = urlsplit(url)

    return urlunsplit((
        parca.scheme,
        parca.netloc,
        parca.path.rstrip("/"),
        "",
        ""
    ))


def metin_al(element):
    if not element:
        return ""
    return " ".join(element.get_text(" ", strip=True).split())


def urun_kartlarini_bul(soup):
    kartlar = soup.find_all(
        ["li", "div", "article"],
        class_=re.compile(
            r"(column|pro|product|itemCard|catalog|listing)",
            re.IGNORECASE
        )
    )

    if not kartlar:
        kartlar = soup.find_all(["li", "article"])

    sonuc = []
    gorulen = set()

    for kart in kartlar:
        link = next(
            (
                a for a in kart.find_all("a", href=True)
                if "/urun/" in a.get("href", "")
            ),
            None
        )

        if not link:
            continue

        url = urun_url_temizle(link["href"])

        if url not in gorulen:
            gorulen.add(url)
            sonuc.append(kart)

    return sonuc


def urun_adi_bul(kart, link, urun_url=None):
    def gecerli_ad(metin):
        if not metin:
            return None

        metin = unquote(str(metin))
        metin = re.sub(r"\s+", " ", metin).strip()

        if len(metin) < 4 or len(metin) > 500:
            return None

        if re.fullmatch(r"[\d.,\s₺€$]+", metin):
            return None

        if re.search(
            r"^\s*(sepete ekle|hemen al|ürünü incele|"
            r"stokta yok|tükendi|ücretsiz kargo)\s*$",
            metin,
            re.IGNORECASE
        ):
            return None

        if re.search(
            r"\b(TL|TRY|USD|EUR)\b|₺|€|\$",
            metin,
            re.IGNORECASE
        ):
            if len(metin) < 45 and re.search(r"\d", metin):
                return None

        try:
            fiyat = fiyat_metnini_temizle(metin)
            if fiyat is not None and len(metin) < 35:
                if re.search(r"\d", metin):
                    return None
        except Exception:
            pass

        return metin[:180]

    # Önce ürün adına ayrılmış HTML alanları
    seciciler = [
        "[itemprop='name']",
        "[data-testid*='product-name']",
        "[data-testid*='product-title']",
        "[class*='productName']",
        "[class*='product-name']",
        "[class*='productTitle']",
        "[class*='product-title']",
        "[class*='proName']",
        "[class*='prdName']",
        "h3",
        "h2",
        "h1",
    ]

    for secici in seciciler:
        try:
            eleman = kart.select_one(secici)

            if not eleman:
                continue

            metin = (
                eleman.get("content")
                or eleman.get("title")
                or metin_al(eleman)
            )

            ad = gecerli_ad(metin)

            if ad:
                return ad

        except Exception:
            continue

    # Ürün bağlantısının başlık bilgileri
    for ozellik in ("title", "aria-label", "data-product-name"):
        try:
            ad = gecerli_ad(link.get(ozellik, ""))
            if ad:
                return ad
        except Exception:
            pass

    # Kart içindeki diğer başlıklı bağlantılar
    try:
        for eleman in kart.select("a[title], a[aria-label]"):
            metin = eleman.get("title") or eleman.get("aria-label")
            ad = gecerli_ad(metin)

            if ad:
                return ad
    except Exception:
        pass

    # Görsel alt metni
    try:
        for resim in kart.find_all("img", alt=True):
            ad = gecerli_ad(resim.get("alt", ""))

            if ad:
                return ad
    except Exception:
        pass

    # Son çare: URL'den ürün adını çıkar
    adres = urun_url

    if not adres:
        try:
            adres = link.get("href")
        except Exception:
            adres = None

    if adres:
        try:
            yol = unquote(
                urlsplit(
                    urljoin("https://www.n11.com/", adres)
                ).path
            )

            slug = yol.rstrip("/").split("/")[-1]

            # URL sonundaki ürün numarasını kaldır
            slug = re.sub(r"-\d+$", "", slug)
            slug = slug.replace("-", " ").strip()

            ad = gecerli_ad(slug)

            if ad:
                return ad.title()

        except Exception:
            pass

    return "Ürün adı bulunamadı"


def urun_fiyati_bul(kart):
    alanlar = kart.find_all(
        ["ins", "span", "div", "p"],
        class_=re.compile(
            r"(price|fiyat|newPrice|salePrice|currentPrice)",
            re.IGNORECASE
        )
    )

    for alan in alanlar:
        fiyat = fiyat_metnini_temizle(metin_al(alan))

        if fiyat is not None:
            return fiyat, False

    alanlar = kart.find_all(
        ["span", "div", "p"],
        class_=re.compile(
            r"(coupon|kupon|basket|sepette|discount|indirim)",
            re.IGNORECASE
        )
    )

    for alan in alanlar:
        metin = metin_al(alan)

        if not re.search(
            r"sepette|sepet fiyatı",
            metin,
            re.IGNORECASE
        ):
            continue

        fiyat = fiyat_metnini_temizle(metin)

        if fiyat is not None:
            return fiyat, True

    return None, False


def main():
    logging.info("Fiyat taraması başladı.")

    eski_veriler = eski_fiyatlari_yukle()
    guncel_veriler = dict(eski_veriler)

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
                kartlar = urun_kartlarini_bul(soup)

                if not kartlar:
                    logging.warning(
                        "%s sayfa %s: Ürün kartı bulunamadı.",
                        magaza, sayfa
                    )
                    time.sleep(1)
                    continue

                sayfa_sayisi = 0

                for kart in kartlar:
                    link = next(
                        (
                            a for a in kart.find_all("a", href=True)
                            if "/urun/" in a.get("href", "")
                        ),
                        None
                    )

                    if not link:
                        continue

                    urun_url = urun_url_temizle(link["href"])

                    if urun_url in gorulen:
                        continue

                    ad = urun_adi_bul(kart, link, urun_url)
                    fiyat, kupon_adayi = urun_fiyati_bul(kart)

                    if fiyat is None:
                        continue

                    gorulen.add(urun_url)
                    toplam += 1
                    sayfa_sayisi += 1

                    eski_kayit = eski_veriler.get(urun_url)

                    if isinstance(eski_kayit, dict):
                        eski_fiyat = eski_kayit.get("fiyat")
                    else:
                        eski_fiyat = eski_kayit

                    try:
                        eski_fiyat = (
                            float(eski_fiyat)
                            if eski_fiyat is not None else None
                        )
                    except (ValueError, TypeError):
                        eski_fiyat = None

                    if eski_fiyat and fiyat < eski_fiyat:
                        dusus = (eski_fiyat - fiyat) / eski_fiyat

                        if dusus > 0.60:
                            logging.warning(
                                "Şüpheli düşüş: %s | %.2f -> %.2f TL",
                                ad, eski_fiyat, fiyat
                            )
                            continue

                        fark = eski_fiyat - fiyat

                        kupon_notu = (
                            "\n🎟️ <i>Sepet fiyatı adayı</i>"
                            if kupon_adayi else ""
                        )

                        mesaj = (
                            f"🔥 <b>FİYAT DÜŞTÜ!</b>{kupon_notu}\n\n"
                            f"🏷️ <b>Ürün:</b> {escape(ad)}\n"
                            f"🏪 <b>Arama:</b> {escape(magaza)}\n"
                            f"📉 <b>Eski:</b> {eski_fiyat:.2f} TL\n"
                            f"💰 <b>Yeni:</b> {fiyat:.2f} TL\n"
                            f"✅ <b>İndirim:</b> %{dusus * 100:.1f}\n"
                            f"💵 <b>Fark:</b> {fark:.2f} TL\n\n"
                            f'🔗 <a href="{escape(urun_url, quote=True)}">'
                            f"Ürüne Git</a>"
                        )

                        telegram_mesaj_gonder(mesaj)

                    guncel_veriler[urun_url] = {
                        "fiyat": fiyat,
                        "urun_adi": ad,
                        "arama_grubu": magaza,
                        "url": urun_url,
                        "son_guncelleme": time.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    }

                logging.info(
                    "%s sayfa %s: %s ürün, toplam %s",
                    magaza, sayfa, sayfa_sayisi, toplam
                )

                time.sleep(1)

            except (requests.RequestException, ValueError) as hata:
                logging.error(
                    "%s sayfa %s hatası: %s",
                    magaza, sayfa, hata
                )
                time.sleep(1)
                continue

        logging.info("%s tamamlandı: %s ürün.", magaza, toplam)

    if yeni_fiyatlari_kaydet(guncel_veriler):
        logging.info(
            "Tarama tamamlandı. Kayıt: %s",
            len(guncel_veriler)
        )
    else:
        logging.error("Fiyatlar dosyaya kaydedilemedi.")


if __name__ == "__main__":
    main()
