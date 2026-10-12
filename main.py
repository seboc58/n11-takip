import os
import json
import time
import re
import statistics
import requests
from html import escape
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote
from bs4 import BeautifulSoup, NavigableString

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
DATA_FILE = "fiyatlar.json"

MIN_FIYAT = 100.0
MAX_FIYAT = 300000.0
SAYFA_SAYISI = 15
BOS_SAYFA_LIMITI = 2

MAGAZALAR = {
    "Teknosa": "https://www.n11.com/arama?q=teknosa",
    "Mediamarkt": "https://www.n11.com/arama?q=mediamarkt",
    "Braunshop": "https://www.n11.com/arama?q=braunshop",
    "Korayspor": "https://www.n11.com/arama?q=korayspor",
    "Skechers": "https://www.n11.com/arama?q=skechers",
    "Karaca": "https://www.n11.com/arama?q=karaca",
    "Tefal": "https://www.n11.com/arama?q=tefal",
}

MAGAZA_SATICI_ESLESME = {
    "Teknosa": ["teknosa"],
    "Mediamarkt": ["mediamarkt", "media markt", "media-markt"],
    "Braunshop": ["braunshop", "braun shop"],
    "Korayspor": ["korayspor", "koray spor"],
    "Skechers": ["skechers"],
    "Karaca": ["karaca"],
    "Tefal": ["tefal"],
}

FIYAT_CLASS = re.compile(
    r"(price|fiyat|newPrice|salePrice|currentPrice|oldPrice|amount|value)",
    re.I,
)
SEPET_CLASS = re.compile(
    r"(coupon|kupon|basket|sepette|discount|indirim|campaign|kampanya)",
    re.I,
)
KART_CLASS = re.compile(
    r"(column|pro|product|itemCard|catalog|listing|card|result)",
    re.I,
)
ELENECEK = re.compile(
    r"taksit|aylık|ayda|başlayan|seçeneği|kargo|puan|yorum|satış",
    re.I,
)


def telegram_mesaj_gonder(mesaj):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False
    try:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(
            api_url,
            data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "HTML"},
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
    if ELENECEK.search(metin):
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
    except Exception:
        pass
    return 0.0


def urun_url_temizle(url):
    url = urljoin("https://www.n11.com/", url)
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), "", ""))


def metin_al(element):
    if not element:
        return ""
    if isinstance(element, NavigableString):
        return " ".join(str(element).split())
    return " ".join(element.get_text(" ", strip=True).split())


def kupon_normalize(metin):
    if not metin:
        return None
    metin = re.sub(r"\s+", " ", str(metin)).strip().lower()
    return metin[:120] if metin else None


def urun_adi_bul(kart, link_tag):
    if kart is not None:
        for etiket in ("h3", "h2"):
            el = kart.find(etiket)
            ad = metin_al(el)
            if len(ad) > 3:
                return ad[:180]
        img = kart.find("img", alt=True)
        if img and img.get("alt", "").strip():
            return img["alt"].strip()[:180]

    if link_tag is not None:
        if link_tag.get("title"):
            return link_tag["title"].strip()[:180]
        ad = metin_al(link_tag)
        if len(ad) > 3:
            return ad[:180]
    return "Ürün"


def kupon_metni_bul(kart):
    if kart is None:
        return None

    adaylar = []
    for el in kart.find_all(["span", "div", "p", "em", "strong"], class_=SEPET_CLASS):
        metin = metin_al(el)
        if metin and len(metin) >= 3 and re.search(
            r"kupon|sepette|sepet fiyat|kampanya|indirim", metin, re.I
        ):
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
    return kupon_normalize(sorted(set(adaylar), key=len)[0][:120])


def _satici_temizle(deger):
    if not deger:
        return None
    deger = unquote(str(deger)).replace("-", " ").replace("+", " ")
    deger = re.sub(r"\s+", " ", deger).strip()
    if 2 <= len(deger) <= 80:
        return deger
    return None


def satici_adi_bul(kart, link_tag=None):
    adaylar = []

    if link_tag is not None:
        href = link_tag.get("href") or ""
        m = re.search(r"[?&]magaza=([^&]+)", href, re.I)
        if m:
            t = _satici_temizle(m.group(1))
            if t:
                adaylar.append(t)

    kok = kart if kart is not None else link_tag
    if kok is not None:
        for a in kok.find_all("a", href=True):
            href = a.get("href") or ""
            href_l = href.lower()

            m = re.search(r"[?&]magaza=([^&]+)", href, re.I)
            if m:
                t = _satici_temizle(m.group(1))
                if t:
                    adaylar.append(t)

            m = re.search(r"/magaza/([^/?#]+)", href_l)
            if m:
                t = _satici_temizle(m.group(1))
                if t:
                    adaylar.append(t)

            if "/magaza/" in href_l or "magaza=" in href_l:
                t = _satici_temizle(metin_al(a))
                if t:
                    adaylar.append(t)

        for el in kok.find_all(
            ["a", "span", "div", "p"],
            class_=re.compile(
                r"(seller|satici|store|magaza|shop|merchant|vendor|sellerName)",
                re.I,
            ),
        ):
            t = _satici_temizle(metin_al(el))
            if t:
                adaylar.append(t)

    if not adaylar:
        return None

    uniq = list({a.lower(): a for a in adaylar}.values())
    uniq.sort(key=len)
    return uniq[0][:80]


def satici_eslesiyor_mu(magaza_adi, satici):
    if not satici:
        return False

    satici_l = satici.lower().strip()
    anahtarlar = MAGAZA_SATICI_ESLESME.get(magaza_adi, [magaza_adi.lower()])

    for k in anahtarlar:
        k = k.lower().strip()
        if satici_l == k or k in satici_l:
            return True
    return False


def dar_kart_bul(link):
    kart = link.find_parent(["li", "article"])
    if kart is not None:
        return kart

    for parent in link.parents:
        if parent.name != "div":
            continue
        classes = " ".join(parent.get("class") or [])
        if KART_CLASS.search(classes):
            urun_link_sayisi = len(parent.find_all("a", href=re.compile(r"/urun/")))
            if urun_link_sayisi <= 6:
                return parent

    p = link.parent
    if p is not None and p.name in ("div", "span"):
        urun_link_sayisi = len(p.find_all("a", href=re.compile(r"/urun/")))
        if urun_link_sayisi <= 4:
            return p

    return link


def _fiyat_adaylari_topla(kok, sadece_sepet=False):
    if kok is None:
        return []

    adaylar = []
    class_re = SEPET_CLASS if sadece_sepet else FIYAT_CLASS

    for el in kok.find_all(
        ["ins", "del", "span", "div", "p", "strong", "b"], class_=class_re
    ):
        metin = metin_al(el)
        if not metin:
            continue
        if not sadece_sepet and re.search(r"sepette|sepet fiyat", metin, re.I):
            continue
        f = fiyat_metnini_temizle(metin)
        if f > 0:
            adaylar.append(f)

    if not adaylar and not sadece_sepet:
        metin = metin_al(kok)
        if len(metin) <= 400:
            for m in re.finditer(
                r"(\d{1,3}(?:[.\s]\d{3})+|\d+)(?:,\d{1,2})?\s*(?:TL|₺)",
                metin,
                re.I,
            ):
                f = fiyat_metnini_temizle(m.group(0))
                if f > 0:
                    adaylar.append(f)

    if sadece_sepet and not adaylar:
        metin = metin_al(kok)
        if len(metin) <= 400:
            m = re.search(
                r"sepette\s*[^\d]{0,10}(\d{1,3}(?:[.\s]\d{3})+|\d+)(?:,\d{1,2})?",
                metin,
                re.I,
            )
            if m:
                f = fiyat_metnini_temizle(m.group(0))
                if f > 0:
                    adaylar.append(f)

    return adaylar


def _en_mantikli_fiyat(adaylar):
    if not adaylar:
        return 0.0
    uniq = sorted(set(adaylar))
    if len(uniq) == 1:
        return uniq[0]
    med = statistics.median(uniq)
    filt = [x for x in uniq if 0.4 * med <= x <= 2.5 * med]
    if not filt:
        filt = uniq
    return round(float(statistics.median(filt)), 2)


def urun_fiyati_bul(kart, link_tag=None):
    kokler = []
    if link_tag is not None:
        if link_tag.parent is not None:
            kokler.append(link_tag.parent)
        kokler.append(link_tag)
    if kart is not None and kart not in kokler:
        kokler.append(kart)

    liste_aday = []
    sepet_aday = []

    for kok in kokler:
        liste_aday.extend(_fiyat_adaylari_topla(kok, sadece_sepet=False))
        sepet_aday.extend(_fiyat_adaylari_topla(kok, sadece_sepet=True))

    liste_fiyat = _en_mantikli_fiyat(liste_aday)
    sepette_fiyat = _en_mantikli_fiyat(sepet_aday)

    if sepette_fiyat > 0 and (liste_fiyat <= 0 or sepette_fiyat <= liste_fiyat):
        fiyat = sepette_fiyat
    else:
        fiyat = liste_fiyat

    return liste_fiyat, sepette_fiyat, fiyat


def urun_ogelerini_topla(soup):
    sonuc = []
    best = {}

    tum_linkler = soup.find_all("a", href=re.compile(r"/urun/"))
    link_sayisi = len(tum_linkler)

    class_kartlar = soup.find_all(["li", "div", "article"], class_=KART_CLASS)
    class_kart_sayisi = len(class_kartlar)

    for link in tum_linkler:
        href = link.get("href") or ""
        if "/urun/" not in href:
            continue

        urun_url = urun_url_temizle(href)
        kart = dar_kart_bul(link)

        skor = 0
        classes = " ".join(link.get("class") or []).lower()
        if "plink" in classes or "product" in classes:
            skor += 3
        if link.find(["h2", "h3"]):
            skor += 5
        if link.get("title"):
            skor += 2
        if re.search(r"[?&]magaza=", href, re.I):
            skor += 10
        txt = metin_al(link)
        if txt and len(txt) > 10:
            skor += 2

        onceki = best.get(urun_url)
        if onceki is None or skor > onceki[0]:
            best[urun_url] = (skor, link, kart)

    for urun_url, (_, link, kart) in best.items():
        sonuc.append((urun_url, kart, link))

    return sonuc, class_kart_sayisi, link_sayisi


def main():
    print("Fiyat taraması başlıyor...")
    print(
        f"Ayarlar: MIN_FIYAT={MIN_FIYAT}, SAYFA_SAYISI={SAYFA_SAYISI}, "
        f"BOS_SAYFA_LIMITI={BOS_SAYFA_LIMITI}"
    )
    print("Filtre: SATICI ZORUNLU — eşleşmeyen / bilinmeyen satıcı elenir")

    eski_veriler = eski_fiyatlari_yukle()
    guncel_veriler = dict(eski_veriler)
    gorulen_urunler = set()

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
        print(f"\n[{magaza_adi}] taranıyor... URL: {base_url}")
        toplam_urun = 0
        bos_sayfa = 0

        for sayfa in range(1, SAYFA_SAYISI + 1):
            ayirici = "&" if "?" in base_url else "?"
            url = f"{base_url}{ayirici}pg={sayfa}"

            try:
                response = requests.get(url, headers=headers, timeout=30)
                if response.status_code != 200:
                    print(f" -> Sayfa {sayfa} HTTP {response.status_code}")
                    bos_sayfa += 1
                    if bos_sayfa >= BOS_SAYFA_LIMITI:
                        print(" -> Üst üste hatalı sayfa, mağaza bitiriliyor.")
                        break
                    time.sleep(1)
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                ogeler, class_kart_sayisi, link_sayisi = urun_ogelerini_topla(soup)

                print(
                    f" -> Sayfa {sayfa}: class_kart={class_kart_sayisi}, "
                    f"urun_link={link_sayisi}, benzersiz={len(ogeler)}"
                )

                sayfa_urun_sayisi = 0
                fiyatsiz_atilan = 0
                yanlis_satici = 0

                for urun_id, kart, link_tag in ogeler:
                    if urun_id in gorulen_urunler:
                        continue

                    liste_fiyat, sepette_fiyat, fiyat = urun_fiyati_bul(kart, link_tag)
                    if fiyat <= 0:
                        fiyatsiz_atilan += 1
                        continue

                    
                    satici = satici_adi_bul(kart, link_tag)

                    if sayfa == 1 and yanlis_satici < 5:
                        print(
                            f"    SATICI TESTİ: grup={magaza_adi!r} | "
                            f"okunan_satıcı={satici!r} | "
                            f"url={link_tag.get('href', '')!r}"
                        )

                    if not satici_eslesiyor_mu(magaza_adi, satici):
                        yanlis_satici += 1
                        continue


                    ad = urun_adi_bul(kart, link_tag)
                    kupon_metni = kupon_metni_bul(kart)

                    if sayfa_urun_sayisi < 3 and sayfa == 1:
                        print(
                            f"    Örnek: {ad[:50]} | satıcı={satici!r} | "
                            f"liste={liste_fiyat} sepette={sepette_fiyat} "
                            f"takip={fiyat}"
                        )

                    gorulen_urunler.add(urun_id)
                    toplam_urun += 1
                    sayfa_urun_sayisi += 1

                    eski_kayit = guncel_veriler.get(urun_id)
                    if eski_kayit is None:
                        eski_kayit = eski_veriler.get(urun_id)

                    if isinstance(eski_kayit, dict):
                        eski_fiyat = eski_kayit.get("fiyat")
                        eski_kupon = eski_kayit.get("kupon_metni")
                        son_bildirim = eski_kayit.get("son_bildirim_fiyati")
                    else:
                        eski_fiyat = eski_kayit
                        eski_kupon = None
                        son_bildirim = None

                    try:
                        eski_fiyat = (
                            float(eski_fiyat) if eski_fiyat is not None else None
                        )
                    except (TypeError, ValueError):
                        eski_fiyat = None
                    try:
                        son_bildirim = (
                            float(son_bildirim) if son_bildirim is not None else None
                        )
                    except (TypeError, ValueError):
                        son_bildirim = None

                    if not kupon_metni and eski_kupon:
                        kupon_metni = eski_kupon

                    esik = son_bildirim if son_bildirim is not None else eski_fiyat
                    yeni_son_bildirim = son_bildirim

                    if esik is not None and fiyat < esik:
                        if fiyat < (esik * 0.4):
                            print(
                                f"Şüpheli düşüş: {ad[:50]} | {esik:.2f} -> {fiyat:.2f}"
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
                                f"👤 <b>Satıcı:</b> {escape(satici)}\n"
                                f"📉 <b>Eski:</b> {esik:.2f} TL\n"
                                f"💰 <b>Yeni:</b> {fiyat:.2f} TL\n"
                                f"✅ <b>İndirim:</b> %{dusus:.1f}\n"
                                f"💵 <b>Fark:</b> {fark:.2f} TL\n\n"
                                f'🔗 <a href="{escape(urun_id, quote=True)}">'
                                f"Ürüne Git</a>"
                            )
                            if telegram_mesaj_gonder(mesaj):
                                yeni_son_bildirim = fiyat

                    elif (not eski_kupon) and kupon_metni:
                        mesaj = (
                            f"🎟️ <b>YENİ KUPON!</b>\n\n"
                            f"🏷️ <b>Ürün:</b> {escape(ad)}\n"
                            f"🏪 <b>Mağaza:</b> {escape(magaza_adi)}\n"
                            f"👤 <b>Satıcı:</b> {escape(satici)}\n"
                            f"💰 <b>Fiyat:</b> {fiyat:.2f} TL\n"
                            f"🎫 <b>Kupon:</b> {escape(kupon_metni)}\n\n"
                            f'🔗 <a href="{escape(urun_id, quote=True)}">'
                            f"Ürüne Git</a>"
                        )
                        telegram_mesaj_gonder(mesaj)

                    elif (
                        eski_kupon
                        and kupon_metni
                        and kupon_normalize(eski_kupon) != kupon_normalize(kupon_metni)
                    ):
                        mesaj = (
                            f"🎟️ <b>KUPON GÜNCELLENDİ!</b>\n\n"
                            f"🏷️ <b>Ürün:</b> {escape(ad)}\n"
                            f"🏪 <b>Mağaza:</b> {escape(magaza_adi)}\n"
                            f"👤 <b>Satıcı:</b> {escape(satici)}\n"
                            f"💰 <b>Fiyat:</b> {fiyat:.2f} TL\n"
                            f"🎫 <b>Eski:</b> {escape(eski_kupon)}\n"
                            f"🎫 <b>Yeni:</b> {escape(kupon_metni)}\n\n"
                            f'🔗 <a href="{escape(urun_id, quote=True)}">'
                            f"Ürüne Git</a>"
                        )
                        telegram_mesaj_gonder(mesaj)

                    guncel_veriler[urun_id] = {
                        "fiyat": fiyat,
                        "liste_fiyat": liste_fiyat if liste_fiyat > 0 else None,
                        "sepette_fiyat": sepette_fiyat if sepette_fiyat > 0 else None,
                        "kupon_metni": kupon_metni,
                        "son_bildirim_fiyati": yeni_son_bildirim,
                        "urun_adi": ad,
                        "satici": satici,
                        "arama_grubu": magaza_adi,
                        "url": urun_id,
                        "son_guncelleme": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }

                print(
                    f"    Eklenen: {sayfa_urun_sayisi} | "
                    f"Fiyatsız: {fiyatsiz_atilan} | "
                    f"Yanlış/bilinmeyen satıcı: {yanlis_satici} | "
                    f"Toplam: {toplam_urun}"
                )

                if len(ogeler) == 0:
                    bos_sayfa += 1
                    if bos_sayfa >= BOS_SAYFA_LIMITI:
                        print(" -> Üst üste boş sayfa, mağaza bitiriliyor.")
                        break
                else:
                    bos_sayfa = 0

                time.sleep(1)

            except Exception as e:
                print(f"Sayfa {sayfa} hatası: {e}")
                bos_sayfa += 1
                if bos_sayfa >= BOS_SAYFA_LIMITI:
                    break
                time.sleep(1)
                continue

        print(f"==> {magaza_adi} Tamamlandı - Toplam: {toplam_urun} ürün")

    yeni_fiyatlari_kaydet(guncel_veriler)
    print(f"\nTüm tarama tamamlandı! Kayıtlı ürün: {len(guncel_veriler)}")


if __name__ == "__main__":
    main()
