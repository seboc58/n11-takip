
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
        return response.json().get("ok", False)

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


def metin_al(element):
    if not element:
        return ""
    return " ".join(element.get_text(" ", strip=True).split())


def fiyat_metnini_temizle(metin):
    if not metin:
        return None

    metin = str(metin).replace("\xa0", " ").strip()

    if re.search(
        r"taksit|aylık|ayda|başlayan|indirim oranı",
        metin,
        re.IGNORECASE
    ):
        return None

    # Öncelikle TL ibaresine bağlı tutarı bul.
    eslesme = re.search(
        r"(?<![\d])(\d{1,3}(?:[.\s]\d{3})+|\d+)"
        r"(?:,\d{1,2})?\s*(?:TL|TRY|₺)",
        metin,
        re.IGNORECASE
    )

    # Bazı fiyat alanlarında para birimi bulunmayabilir.
    if not eslesme:
        eslesme = re.search(
            r"(?<![\d])(\d{1,3}(?:[.\s]\d{3})+|\d+)"
            r"(?:,\d{1,2})?(?!\d)",
            metin
        )

    if not eslesme:
        return None

    ham = eslesme.group(0)
    ham = re.sub(r"\s*(TL|TRY|₺)\s*", "", ham, flags=re.I)
    ham = ham.replace(" ", "")

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


def urun_adi_gecerli(metin):
    if not metin:
        return False

    metin = re.sub(r"\s+", " ", str(metin)).strip()
    ust = metin.upper()

    if len(metin) < 5 or len(metin) > 500:
        return False

    gecersizler = [
        "POPÜLER SAYFALAR",
        "POPULER SAYFALAR",
        "ÜRÜN ADI BULUNAMADI",
        "SEPETE EKLE",
        "HEMEN AL",
        "ÜRÜNÜ İNCELE",
        "ÜCRETSİZ KARGO",
        "STOKTA YOK",
        "FIRSAT ÜRÜNLERİ",
    ]

    if any(x in ust for x in gecersizler):
        return False

    if re.fullmatch(r"[\d.,\s₺€$]+", metin):
        return False

    if len(metin) < 45 and re.search(
        r"\b(TL|TRY|USD|EUR)\b|₺|€|\$",
        metin,
        re.IGNORECASE
    ):
        return False

    return True


def urun_adi_bul(kart, link, urun_url=None):
    # Önce bağlantının kendi ürün bilgileri.
    for ozellik in (
        "data-product-name",
        "title",
        "aria-label",
    ):
        ad = link.get(ozellik, "")
        if urun_adi_gecerli(ad):
            return re.sub(r"\s+", " ", ad).strip()[:180]

    # Ürün adı için daha anlamlı HTML alanları.
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
    ]

    for secici in seciciler:
        for eleman in kart.select(secici):
            ad = (
                eleman.get("content")
                or eleman.get("title")
                or metin_al(eleman)
            )

            if urun_adi_gecerli(ad):
                return re.sub(r"\s+", " ", ad).strip()[:180]

    # Ürün görselinin alt metni.
    for resim in kart.find_all("img"):
        ad = resim.get("alt", "")
        if urun_adi_gecerli(ad):
            return re.sub(r"\s+", " ", ad).strip()[:180]

    # Karttaki başlık etiketleri yalnızca anlamlıysa kullanılır.
    for secici in ("h3", "h2", "h1"):
        for eleman in kart.select(secici):
            ad = metin_al(eleman)
            if urun_adi_gecerli(ad):
                return ad[:180]

    # Son çare: ürün URL'sinden ad oluştur.
    adres = urun_url or link.get("href", "")

    yol = unquote(urlsplit(
        urljoin("https://www.n11.com/", adres)
    ).path)

    slug = yol.rstrip("/").split("/")[-1]
    slug = re.sub(r"-\d+$", "", slug)
    slug = re.sub(r"-+", " ", slug).strip()

    if urun_adi_gecerli(slug):
        return slug

    return None


def sepetteki_fiyati_bul(kart):
    """
    Yalnızca 'sepette' veya 'sepet fiyatı' ifadesiyle
    ilişkili tutarı arar. Normal fiyatı sepet fiyatı saymaz.
    """
    # Önce sepet ibaresi bulunan en küçük HTML alanlarını tara.
    alanlar = kart.find_all(
        ["span", "div", "p", "strong", "b", "ins"],
        limit=500
    )

    adaylar = []

    for alan in alanlar:
        metin = metin_al(alan)

        if not re.search(
            r"sepette|sepet fiyatı|sepete özel",
            metin,
            re.IGNORECASE
        ):
            continue

        # Büyük kartın tüm metni yerine mümkünse küçük alanı seç.
        if len(metin) > 180:
            continue

        fiyat = fiyat_metnini_temizle(metin)

        if fiyat is not None:
            adaylar.append((len(metin), fiyat))

    if adaylar:
        adaylar.sort(key=lambda x: x[0])
        return adaylar[0][1]

    # Bazı sayfalarda ibare ve tutar ayrı HTML alanlarında olabilir.
    # Kart metnindeki ibareden sonra gelen tutarı kontrol et.
    tum_metin = metin_al(kart)

    eslesme = re.search(
        r"(?:sepette|sepet fiyatı|sepete özel)"
        r".{0,100}?(\d{1,3}(?:[.\s]\d{3})+|\d+)"
        r"(?:,\d{1,2})?\s*(?:TL|TRY|₺)",
        tum_metin,
        re.IGNORECASE
    )

    if eslesme:
        fiyat = fiyat_metnini_temizle(eslesme.group(1) + " TL")
        if fiyat is not None:
            return fiyat

    return None


def normal_fiyati_bul(kart):
    # Fiyatla ilişkili sınıfları önce kontrol et.
    alanlar = kart.find_all(
        ["ins", "span", "div", "p", "strong"],
        class_=re.compile(
            r"(price|fiyat|newPrice|salePrice|currentPrice)",
            re.IGNORECASE
        )
    )

    adaylar = []

    for alan in alanlar:
        metin = metin_al(alan)

        # Sepet fiyatı normal fiyat listesine karışmasın.
        if re.search(
            r"sepette|sepet fiyatı|sepete özel",
            metin,
            re.IGNORECASE
        ):
            continue

        fiyat = fiyat_metnini_temizle(metin)

        if fiyat is not None:
            adaylar.append((len(metin), fiyat))

    if adaylar:
        adaylar.sort(key=lambda x: x[0])
        return adaylar[0][1]

    return None


def urun_fiyati_bul(kart):
    # KRİTİK DÜZELTME:
    # Önce sepetteki fiyat, sonra normal fiyat.
    sepet_fiyati = sepetteki_fiyati_bul(kart)

    if sepet_fiyati is not None:
        return sepet_fiyati, True

    normal_fiyat = normal_fiyati_bul(kart)

    if normal_fiyat is not None:
        return normal_fiyat, False

    return None, False


def onceki_kaydi_bul(eski_veriler, urun_url):
    kayit = eski_veriler.get(urun_url)

    if isinstance(kayit, dict):
        return kayit

    return {}


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

                    eski_kayit = onceki_kaydi_bul(
                        eski_veriler, urun_url
                    )

                    ad = urun_adi_bul(kart, link, urun_url)
                    fiyat, sepet_fiyati = urun_fiyati_bul(kart)

                    # Ürün adı bulunamadıysa yanlış genel metin kaydetme.
                    if not ad:
                        eski_ad = eski_kayit.get("urun_adi", "")

                        if urun_adi_gecerli(eski_ad):
                            ad = eski_ad
                        else:
                            logging.warning(
                                "Ürün adı bulunamadı; kayıt atlandı: %s",
                                urun_url
                            )
                            continue

                    if fiyat is None:
                        logging.debug(
                            "Fiyat bulunamadı: %s", urun_url
                        )
                        continue

                    gorulen.add(urun_url)

                    eski_fiyat = eski_kayit.get("fiyat")

                    try:
                        eski_fiyat = (
                            float(eski_fiyat)
                            if eski_fiyat is not None else None
                        )
                    except (ValueError, TypeError):
                        eski_fiyat = None

                    # Çok büyük ve şüpheli düşüşlerde kayıt güncelleme.
                    if eski_fiyat and fiyat < eski_fiyat:
                        dusus = (eski_fiyat - fiyat) / eski_fiyat

                        if dusus > 0.60:
                            logging.warning(
                                "Şüpheli fiyat düşüşü, atlandı: %s "
                                "| %.2f -> %.2f TL",
                                ad, eski_fiyat, fiyat
                            )
                            continue

                        fark = eski_fiyat - fiyat

                        if fark >= 1:
                            sepet_notu = (
                                "\n🎟️ <i>Sepette indirimli fiyat</i>"
                                if sepet_fiyati else ""
                            )

                            mesaj = (
                                f"🔥 <b>FİYAT DÜŞTÜ!</b>{sepet_notu}\n\n"
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

                    toplam += 1
                    sayfa_sayisi += 1

                logging.info(
                    "%s sayfa %s: %s ürün, toplam %s",
                    magaza, sayfa, sayfa_sayisi, toplam
                )

                time.sleep(1)

            except requests.RequestException as hata:
                logging.error(
                    "%s sayfa %s isteği başarısız: %s",
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
