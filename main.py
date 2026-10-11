import os
import json
import time
import re
import requests
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
DATA_FILE = "fiyatlar.json"

MAGAZALAR = {
    "Teknosa": "https://www.n11.com/arama?q=teknosa&srt=PRICE_LOW",
    "Mediamarkt": "https://www.n11.com/arama?q=mediamarkt&srt=PRICE_LOW",
    "Braunshop": "https://www.n11.com/arama?q=braunshop&srt=PRICE_LOW",
    "Korayspor": "https://www.n11.com/arama?q=korayspor&srt=PRICE_LOW",
    "Skechers": "https://www.n11.com/arama?q=skechers&srt=PRICE_LOW",
    "Karaca": "https://www.n11.com/arama?q=karaca&srt=PRICE_LOW",
    "Tefal": "https://www.n11.com/arama?q=tefal&srt=PRICE_LOW",
}

def telegram_mesaj_gonder(mesaj):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    try:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(api_url, data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"Telegram gönderme hatasi: {e}")

def eski_fiyatlari_yukle():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def yeni_fiyatlari_kaydet(veri):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(veri, f, ensure_ascii=False, indent=2)
    except:
        pass

def fiyat_temizle(metin):
    if not metin:
        return 0.0
    metin_temiz = metin.replace("TL", "").replace("TL.", "").strip()
    m = re.findall(r'([\d\.]+[\d\,]+)', metin_temiz)
    if not m:
        m = re.findall(r'(\d+)', metin_temiz)
        if not m:
            return 0.0

    for val_str in m:
        try:
            clean_val = val_str.replace(".", "").replace(",", ".")
            if "." in clean_val and clean_val.count(".") > 1:
                clean_val = clean_val.replace(".", "", clean_val.count(".") - 1)
            
            f = float(clean_val)
            if 15.0 <= f <= 300000.0:
                return f
        except:
            continue
    return 0.0

def main():
    print("Arama Tabanlı Çok Sayfalı Tarama Başlatılıyor...")
    eski_veriler = eski_fiyatlari_yukle()
    guncel_veriler = dict(eski_veriler)

    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.n11.com/"
    }

    for magaza_adi, base_url in MAGAZALAR.items():
        print(f"\n[{magaza_adi}] taranıyor...")
        gorulen_urunler = set()
        toplam_urun = 0

        for sayfa in range(1, 11):
            url = f"{base_url}&pg={sayfa}"
            
            try:
                response = requests.get(url, headers=headers, timeout=30)
                if response.status_code != 200:
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                linkler = soup.find_all("a", href=True)
                
                sayfa_urun_sayisi = 0
                for link in linkler:
                    urun_link = link["href"]
                    if "/urun/" not in urun_link:
                        continue

                    if urun_link.startswith("/"):
                        urun_link = "https://www.n11.com" + urun_link

                    urun_id = urun_link.split("?")[0]
                    if urun_id in gorulen_urunler:
                        continue

                    parent = link.find_parent(["li", "div", "article"])
                    kapsayici_metin = parent.get_text() if parent else link.get_text()

                    fiyat = fiyat_temizle(kapsayici_metin)
                    if fiyat <= 0:
                        continue

                    gorulen_urunler.add(urun_id)
                    toplam_urun += 1
                    sayfa_urun_sayisi += 1

                    eski_fiyat = eski_veriler.get(urun_id)
                    if eski_fiyat is not None and fiyat < eski_fiyat:
                        mesaj = (
                            f"🔥 <b>FİYAT DÜŞTÜ!</b>\n\n"
                            f"🏪 <b>Mağaza:</b> {magaza_adi}\n"
                            f"📉 <b>Eski Fiyat:</b> {eski_fiyat:.2f} TL\n"
                            f"🏷️ <b>Yeni Fiyat:</b> {fiyat:.2f} TL\n\n"
                            f"🔗 <a href='{urun_link}'>Ürüne Git</a>"
                        )
                        telegram_mesaj_gonder(mesaj)

                    guncel_veriler[str(urun_id)] = fiyat

                print(f" -> Sayfa {sayfa} tarandı. Yeni ürün: {sayfa_urun_sayisi} (Toplam: {toplam_urun})")
                
                if sayfa_urun_sayisi == 0:
                    break
                
                time.sleep(0.5)

            except Exception as e:
                print(f"Sayfa {sayfa} hatası: {e}")
                break

        print(f"==> {magaza_adi} Tamamlandı - Toplam taranan benzersiz ürün: {toplam_urun}")

    yeni_fiyatlari_kaydet(guncel_veriler)
    print("\nTüm arama taramaları tamamlandı, fiyatlar kaydedildi.")

if __name__ == "__main__":
    main()
