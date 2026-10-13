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
    # Başlık alanına fiyat metni geldiyse bunu ürün adı kabul etme.
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

    # Son çare: ürün URL'sindeki slug'dan okunabilir bir ad üret.
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

    alanlar = kart.find_all(
        ["span", "div", "p", "ins"],
        class_=re.compile(r"(coupon|kupon|basket|sepette|discount|indirim|campaign)", re.I),
    )
    for alan in alanlar:
        metin = metin_al(alan)
        if not re.search(r"sepette|sepet fiyat|kupon", metin, re.I):
            continue
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

    if liste_fiyat <= 0:
        adaylar = kart.find_all(
            ["ins", "span", "div", "p"],
            class_=re.compile(r"(price|fiyat|newPrice|salePrice|currentPrice|amount|value)", re.I),
        )
        if not adaylar:
            adaylar = kart.find_all(string=re.compile(r"TL|₺"))
        for aday in adaylar:
            metin = aday.get_text(" ", strip=True) if hasattr(aday, "get_text") else str(aday)
            if re.search(r"sepette|sepet fiyat|taksit|aylık|ayda|başlayan|seçeneği", metin, re.I):
                continue
            f = fiyat_metnini_temizle(metin)
            if f > 0:
                liste_fiyat = f
                break

    fiyat = sepette_fiyat if sepette_fiyat > 0 else liste_fiyat
    return liste_fiyat, sepette_fiyat, fiyat


def urun_karti_ve_linkleri_bul(soup):
    """Her ürün URL'sini kendi en yakın ürün kartıyla eşleştir; üst kapsayıcıyı ürün kartı sanma."""
    sonuc = []
    eklenen = set()

    for link in soup.find_all("a", href=True):
        ham_link = link.get("href", "")
        if "/urun/" not in ham_link:
            continue

        urun_id = urun_url_temizle(ham_link)
        if urun_id in eklenen:
            continue

        kart = None
        for parent in link.parents:
            if getattr(parent, "name", None) not in ("li", "div", "article"):
                continue
            classes = " ".join(parent.get("class", []))
            if re.search(r"(product|column|pro|item)", classes, re.I):
                # En yakın eşleşen kapsayıcıyı al.
                kart = parent
                break

        if kart is None:
            kart = link.parent
        if kart is None:
            continue

        # Seçilen kart başka bir ürünün bağlantısını önce içeriyorsa yanlış eşleşmeyi önle.
        kart_linkleri = [
            a for a in kart.find_all("a", href=True)
            if "/urun/" in a.get("href", "")
        ]
        if kart_linkleri:
            ilk_url = urun_url_temizle(kart_linkleri[0]["href"])
            if ilk_url != urun_id:
                # Daha yakın bir kart bulmak için ebeveyn zincirinde yukarı gitmeden
                # bu bağlantıyı atlama; her bağlantı kendi kartıyla ayrı işlenebilir.
                pass

        eklenen.add(urun_id)
        sonuc.append((kart, link, urun_id))

    return sonuc


def main():
    print("N11 fiyat ve kupon taraması başlatılıyor...")
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

    # Aynı ürün farklı arama gruplarında görünürse aynı çalıştırmada ikinci kez
    # bildirim üretmesini önleyen global küme.
    islenen_urunler = set()

    for magaza_adi, base_url in MAGAZALAR.items():
        print(f"\n[{magaza_adi}] taranıyor...")
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
                urunler = urun_karti_ve_linkleri_bul(soup)
                sayfa_urun_sayisi = 0

                for kart, link_tag, urun_id in urunler:
                    if urun_id in islenen_urunler:
                        continue

                    liste_fiyat, sepette_fiyat, fiyat = urun_fiyati_bul(kart)
                    if fiyat <= 0:
                        continue

                    ad = urun_adi_bul(kart, link_tag, urun_id)
                    kupon_metni = kupon_metni_bul(kart)

                    islenen_urunler.add(urun_id)
                    toplam_urun += 1
                    sayfa_urun_sayisi += 1

                    # Aynı çalıştırma içinde önceki taramalarda güncellenen kaydı oku.
                    eski_kayit = guncel_veriler.get(urun_id)
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
                        son_bildirim = float(son_bildirim) if son_bildirim is not None else None
                    except (TypeError, ValueError):
                        son_bildirim = None

                    esik = son_bildirim if son_bildirim is not None else eski_fiyat
                    yeni_son_bildirim = son_bildirim

                    if esik is not None and fiyat < esik:
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
                                else ("\n🎟️ <i>Sepet fiyatı</i>" if sepette_fiyat > 0 else "")
                            )
                            mesaj = (
                                f"🔥 <b>FİYAT DÜŞTÜ!</b>{kupon_notu}\n\n"
                                f"🏷️ <b>Ürün:</b> {escape(ad)}\n"
                                f"🏪 <b>Mağaza:</b> {escape(magaza_adi)}\n"
                                f"📉 <b>Eski:</b> {esik:.2f} TL\n"
                                f"💰 <b>Yeni:</b> {fiyat:.2f} TL\n"
                                f"✅ <b>İndirim:</b> %{dusus:.1f}\n"
                                f"💵 <b>Fark:</b> {fark:.2f} TL\n\n"
                                f'🔗 <a href="{escape(urun_id, quote=True)}">Ürüne Git</a>'
                            )
                            if telegram_mesaj_gonder(mesaj):
                                yeni_son_bildirim = fiyat
                                print(f"Fiyat bildirimi gönderildi: {ad} - {fiyat:.2f} TL")

                    elif (not eski_kupon) and kupon_metni:
                        mesaj = (
                            f"🎟️ <b>YENİ KUPON!</b>\n\n"
                            f"🏷️ <b>Ürün:</b> {escape(ad)}\n"
                            f"🏪 <b>Mağaza:</b> {escape(magaza_adi)}\n"
                            f"💰 <b>Fiyat:</b> {fiyat:.2f} TL\n"
                            f"🎫 <b>Kupon:</b> {escape(kupon_metni)}\n\n"
                            f'🔗 <a href="{escape(urun_id, quote=True)}">Ürüne Git</a>'
                        )
                        telegram_mesaj_gonder(mesaj)

                    elif eski_kupon and kupon_metni and eski_kupon != kupon_metni:
                        mesaj = (
                            f"🎟️ <b>KUPON GÜNCELLENDİ!</b>\n\n"
                            f"🏷️ <b>Ürün:</b> {escape(ad)}\n"
                            f"🏪 <b>Mağaza:</b> {escape(magaza_adi)}\n"
                            f"💰 <b>Fiyat:</b> {fiyat:.2f} TL\n"
                            f"🎫 <b>Eski:</b> {escape(eski_kupon)}\n"
                            f"🎫 <b>Yeni:</b> {escape(kupon_metni)}\n\n"
                            f'🔗 <a href="{escape(urun_id, quote=True)}">Ürüne Git</a>'
                        )
                        telegram_mesaj_gonder(mesaj)

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
                    f" -> Sayfa {sayfa} tarandı. İşlenen ürün: {sayfa_urun_sayisi} "
                    f"(Mağaza toplamı: {toplam_urun})"
                )
                if sayfa_urun_sayisi == 0:
                    break
                time.sleep(1)

            except Exception as e:
                print(f"Sayfa {sayfa} hatası: {e}")
                time.sleep(1)
                continue

        print(f"==> {magaza_adi} tamamlandı - Toplam: {toplam_urun} ürün")

    yeni_fiyatlari_kaydet(guncel_veriler)
    print("\nTüm tarama tamamlandı!")


if __name__ == "__main__":
    main()
