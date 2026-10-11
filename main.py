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
    "Teknosa": "https://www.n11.com/arama?q=teknosa",
    "Mediamarkt": "https://www.n11.com/arama?q=mediamarkt",
    "Braunshop": "https://www.n11.com/arama?q=braunshop",
    "Korayspor": "https://www.n11.com/arama?q=korayspor",
    "Skechers": "https://www.n11.com/arama?q=skechers",
    "Karaca": "https://www.n11.com/arama?q=karaca",
    "Tefal": "https://www.n11.com/arama?q=tefal",
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

def fiyat_metnini_temizle(metin):
    """
    N11 metinlerinden doğrudan TL fiyatını çıkarır.
    Örn: '1.499,00 TL' -> 1499.00
    """
    if not metin:
        return 0.0
    
    # Metin içinden sadece geçerli fiyat kalıbını (Örn: 1.250,50 veya 499,00 veya 1200) yakala
    # TL veya ₺ öncesindeki rakam bloğunu çekmek en güvenlisidir
    match = re.search(r'([\d\.,]+)\s*(?:TL|₺)?', metin)
    if not match:
        return 0.0

    raw_val = match.group(1).strip()
    
    try:
        # Türkiye formatını (1.250,50) Python float formatına (1250.50) çevir
        if "," in raw_val:
            raw_val = raw_val.replace(".", "").replace(",", ".")
        else:
            if raw_val.count(".") > 1:
                raw_val = raw_val.replace(".", "")

        val = float(raw_val)
        
        # Gerçekçi e-ticaret fiyat sınırları: 15 TL ile 250.000 TL arası
        if 15.0 <= val <= 250000.0:
            return val
            
        return 0.0
    except:
        return 0.0

def main():
    print("Esnek ve Kesin Fiyat Taraması Başlatılıyor...")
    eski_veriler = eski_fiyatlari_yukle()
    guncel_veriler = dict(eski_veriler)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.n11.com/"
    }

    for magaza_adi, base_url in MAGAZALAR.items():
        print(f"\n[{magaza_adi}] taranıyor...")
        gorulen_urunler = set()
        toplam_urun = 0

        for sayfa in range(1, 4):
            url = f"{base_url}&pg={sayfa}"
            
            try:
                response = requests.get(url, headers=headers, timeout=30)
                if response.status_code != 200:
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                
                # N11 ürün kartları (li veya div)
                urun_kartlari = soup.find_all("li", class_="column")
                if not urun_kartlari:
                    urun_kartlari = soup.find_all(["li", "div"], class_=re.compile(r'(column|pro|product)', re.I))

                sayfa_urun_sayisi = 0
                for kart in urun_kartlari:
                    link_tag = kart.find("a", href=True)
                    if not link_tag:
                        continue
                        
                    urun_link = link_tag["href"]
                    if "/urun/" not in urun_link:
                        continue

                    if urun_link.startswith("/"):
                        urun_link = "https://www.n11.com" + urun_link

                    urun_id = urun_link.split("?")[0]
                    if urun_id in gorulen_urunler:
                        continue

                    # Fiyat kapsayıcısını bul
                    fiyat_tag = (
                        kart.find("ins") or 
                        kart.find("div", class_=re.compile(r'(price|fiyat)', re.I)) or 
                        kart.find("span", class_=re.compile(r'(price|fiyat|newPrice)', re.I))
                    )
                    
                    if not fiyat_tag:
                        continue

                    fiyat_metni = fiyat_tag.get_text().strip()
                    fiyat = fiyat_metnini_temizle(fiyat_metni)

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

                print(f" -> Sayfa {sayfa} tarandı. Eklenen ürün: {sayfa_urun_sayisi} (Toplam: {toplam_urun})")
                
                if sayfa_urun_sayisi == 0:
                    break
                
                time.sleep(0.5)

            except Exception as e:
                print(f"Sayfa {sayfa} hatası: {e}")
                break

        print(f"==> {magaza_adi} Tamamlandı - Toplam ürün: {toplam_urun}")

    yeni_fiyatlari_kaydet(guncel_veriler)
    print("\nTüm tarama tamamlandı!")

if __name__ == "__main__":
    main()
