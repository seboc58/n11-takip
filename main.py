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
        return False
    try:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(
            api_url,
            data={
                "chat_id": CHAT_ID,
                "text": mesaj,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        return r.ok
    except Exception as e:
        print(f"Telegram gönderme hatasi: {e}")
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

        if MIN_FIYAT <= val <= MAX_FIYAT:
            return round(val, 2)

        return 0.0
    except Exception:
        return 0.0


def urun_url_temizle(url):
    """Her zaman aynı formata getir: full URL, query yok, trailing slash yok."""
    url = urljoin("https://www.n11.com/", url)
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), "", ""))


def metin_al(element):
    if not element:
        return ""
    return " ".join(element.get_text(" ", strip=True).split())


def urun_adi_bul(kart, link_tag):
    for etiket in ("h3", "h2"):
        el = kart.find(etiket)
        ad = metin_al(el)
        if len(ad) > 3:
            return ad[:180]

    if link_tag.get("title"):
        return link_tag["title"].strip()[:180]

    img = kart.find("img", alt=True)
    if img and img.get("alt", "").strip():
        return img["alt"].strip()[:180]

    return metin_al(link_tag)[:180] or "Ürün"


def kupon_metni_bul(kart):
    """Karttaki kupon / sepette / kampanya metnini çıkarır."""
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
    """
    Liste fiyatı + sepette fiyatı ayrı bulur.
    Takip için: sepette varsa onu, yoksa liste fiyatını kullanır.
    """
    liste_fiyat = 0.0
    sepette_fiyat = 0.0

    # 1) Normal fiyat alanları
    alanlar = kart.find_all(
        ["ins", "span", "div", "p"],
        class_=re.compile(r"(price|fiyat|newPrice|salePrice|currentPrice|new|amount|value)", re.I),
    )
    for alan in alanlar:
        metin = metin_al(alan)
        if re.search(r"sepette|sepet fiyat", metin, re.I):
            continue
        if any(k in metin.lower() for k in ("taksit", "aylık", "ayda", "başlayan", "seçeneği")):
            continue
        f = fiyat_metnini_temizle(metin)
        if f > 0:
            liste_fiyat = f
            break

    # 2) Sepette / kupon fiyatı
    alanlar = kart.find_all(
        ["span", "div", "p", "ins"],
        class_=re.compile(r"(coupon|kupon|basket|sepette|discount|indirim|campaign)", re.I),
    )
    for alan in alanlar:
        metin = metin_al(alan)
        f = fiyat_metnini_temizle(metin)
        if f > 0:
            sepette_fiyat = f
            break

    if sepette_fiyat <= 0:
        tum = metin_al(kart)
        m = re.search(
            r"sepette\s*[^\d]{0,10}(\d{1,3}(?:[.\s]\d{3})+|\d+)(?:,\d{1,2})?",
            tum,
            re.I,
        )
        if m:
            sepette_fiyat = fiyat_metnini_temizle(m.group(0))

    # Class tutmazsa genel adaylar
    if liste_fiyat <= 0 and sepette_fiyat <= 0:
        adaylar = kart.find_all(
            ["ins", "span", "div", "p"],
            class_=re.compile(r"(price|fiyat|new|amount|value)", re.I),
        )
        if not adaylar:
            adaylar = kart.find_all(string=re.compile(r"TL|₺"))
        for aday in adaylar:
            metin = aday.get_text() if hasattr(aday, "get_text") else str(aday)
            if any(k in metin.lower() for k in ("taksit", "aylık", "ayda", "başlayan", "seçeneği")):
                continue
            f = fiyat_metnini_temizle(metin)
            if f > 0:
                liste_fiyat = f
                break

    fiyat = sepette_fiyat if sepette_fiyat > 0 else liste_fiyat
    return liste_fiyat, sepette_fiyat, fiyat


def main():
    print("Esnek ve Kesin Ürün Fiyat Taraması Başlatılıyor...")
    eski_veriler = eski_fiyatlari_yukle()
    guncel_veriler = dict(eski_veriler)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.n11.com/",
    }

    for magaza_adi, base_url in MAGAZALAR.items():
        print(f"\n[{magaza_adi}] taranıyor...")
        gorulen_urunler = set()
        toplam_urun = 0

        for sayfa in range(1, SAYFA_SAYISI + 1):
            url = f"{base_url}&pg={sayfa}"

            try:
                response = requests.get(url, headers=headers, timeout=30)
                if response.status_code != 200:
                    print(f" -> Sayfa {sayfa} HTTP {response.status_code}, atlanıyor.")
                    time.sleep(1)
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                urun_kartlari = soup.find_all(
                    ["li", "div"],
                    class_=re.compile(r"(column|pro|product)", re.I),
                )
                if not urun_kartlari:
                    urun_kartlari = soup.find_all("li")

                sayfa_urun_sayisi = 0

                for kart in urun_kartlari:
                    link_tag = kart.find("a", href=True)
                    if not link_tag:
                        continue

                    ham_link = link_tag["href"]
                    if "/urun/" not in ham_link:
                        continue

                    urun_id = urun_url_temizle(ham_link)
                    if urun_id in gorulen_urunler:
                        continue

                    liste_fiyat, sepette_fiyat, fiyat = urun_fiyati_bul(kart)
                    if fiyat <= 0:
                        continue

                    ad = urun_adi_bul(kart, link_tag)
                    kupon_metni = kupon_metni_bul(kart)

                    gorulen_urunler.add(urun_id)
                    toplam_urun += 1
                    sayfa_urun_sayisi += 1

                    eski_kayit = eski_veriler.get(urun_id)

                    # Eski format (sadece sayı) uyumu
                    if isinstance(eski_kayit, dict):
                        eski_fiyat = eski_kayit.get("fiyat")
                        eski_kupon = eski_kayit.get("kupon_metni")
                        son_bildirim = eski_kayit.get("son_bildirim_fiyati")
                    else:
                        eski_fiyat = eski_kayit
                        eski_kupon = None
                        son_bildirim = None

                    try:
                        eski_fiyat = float(eski_fiyat) if eski_fiyat is not None else None
                    except (TypeError, ValueError):
                        eski_fiyat = None

                    try:
                        son_bildirim = (
                            float(son_bildirim) if son_bildirim is not None else None
                        )
                    except (TypeError, ValueError):
                        son_bildirim = None

                    # Aynı düşüşü tekrar atmamak için eşik
                    esik = son_bildirim if son_bildirim is not None else eski_fiyat
                    yeni_son_bildirim = son_bildirim

                    # --- FİYAT DÜŞÜŞÜ ---
                    if esik is not None and fiyat < esik:
                        # %60'tan fazla düşüş şüpheli → bildir ama kaydı yine güncelle
                        if fiyat < (esik * 0.4):
                            print(
                                f"Şüpheli düşüş (bildirim yok): {ad[:50]} | "
                                f"{esik:.2f} -> {fiyat:.2f}"
                            )
                        else:
                            fark = esik - fiyat
                            dusus = (fark / esik) * 100
                            kupon_notu = (
                                f"\n🎟️ <i>{escape(kupon_metni)}</i>"
                                if kupon_metni
                                else (
                                    "\n🎟️ <i>Sepet fiyatı</i>"
                                    if sepette_fiyat > 0
                                    else ""
                                )
                            )
                            mesaj = (
                                f"🔥 <b>FİYAT DÜŞTÜ!</b>{kupon_notu}\n\n"
                                f"🏷️ <b>Ürün:</b> {escape(ad)}\n"
                                f"🏪 <b>Mağaza:</b> {escape(magaza_adi)}\n"
                                f"📉 <b>Eski:</b> {esik:.2f} TL\n"
                                f"💰 <b>Yeni:</b> {fiyat:.2f} TL\n"
                                f"✅ <b>İndirim:</b> %{dusus:.1f}\n"
                                f"💵 <b>Fark:</b> {fark:.2f} TL\n\n"
                                f'🔗 <a href="{escape(urun_id, quote=True)}">'
                                f"Ürüne Git</a>"
                            )
                            if telegram_mesaj_gonder(mesaj):
                                yeni_son_bildirim = fiyat

                    # --- YENİ KUPON ---
                    elif (not eski_kupon) and kupon_metni:
                        mesaj = (
                            f"🎟️ <b>YENİ KUPON!</b>\n\n"
                            f"🏷️ <b>Ürün:</b> {escape(ad)}\n"
                            f"🏪 <b>Mağaza:</b> {escape(magaza_adi)}\n"
                            f"💰 <b>Fiyat:</b> {fiyat:.2f} TL\n"
                            f"🎫 <b>Kupon:</b> {escape(kupon_metni)}\n\n"
                            f'🔗 <a href="{escape(urun_id, quote=True)}">'
                            f"Ürüne Git</a>"
                        )
                        telegram_mesaj_gonder(mesaj)

                    # --- KUPON DEĞİŞTİ ---
                    elif eski_kupon and kupon_metni and eski_kupon != kupon_metni:
                        mesaj = (
                            f"🎟️ <b>KUPON GÜNCELLENDİ!</b>\n\n"
                            f"🏷️ <b>Ürün:</b> {escape(ad)}\n"
                            f"🏪 <b>Mağaza:</b> {escape(magaza_adi)}\n"
                            f"💰 <b>Fiyat:</b> {fiyat:.2f} TL\n"
                            f"🎫 <b>Eski:</b> {escape(eski_kupon)}\n"
                            f"🎫 <b>Yeni:</b> {escape(kupon_metni)}\n\n"
                            f'🔗 <a href="{escape(urun_id, quote=True)}">'
                            f"Ürüne Git</a>"
                        )
                        telegram_mesaj_gonder(mesaj)

                    # Her zaman kaydı güncelle
                    guncel_veriler[urun_id] = {
                        "fiyat": fiyat,
                        "liste_fiyat": liste_fiyat if liste_fiyat > 0 else None,
                        "sepette_fiyat": sepette_fiyat if sepette_fiyat > 0 else None,
                        "kupon_metni": kupon_metni,
                        "son_bildirim_fiyati": yeni_son_bildirim,
                        "urun_adi": ad,
                        "arama_grubu": magaza_adi,
                        "url": urun_id,
                        "son_guncelleme": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }

                print(
                    f" -> Sayfa {sayfa} tarandı. Eklenen ürün: {sayfa_urun_sayisi} "
                    f"(Toplam: {toplam_urun})"
                )

                if sayfa_urun_sayisi == 0:
                    break

                time.sleep(1)

            except Exception as e:
                print(f"Sayfa {sayfa} hatası: {e}")
                time.sleep(1)
                continue

        print(f"==> {magaza_adi} Tamamlandı - Toplam: {toplam_urun} ürün")

    yeni_fiyatlari_kaydet(guncel_veriler)
    print("\nTüm tarama tamamlandı!")


if __name__ == "__main__":
    main()
