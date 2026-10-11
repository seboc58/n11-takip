import os
import json
import requests
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
DATA_FILE = "fiyatlar.json"

MAGAZALAR = {
    "Teknosa": "https://www.n11.com/magaza/teknosa",
    "Mediamarkt": "https://www.n11.com/magaza/mediamarkt",
    "Braunshop": "https://www.n11.com/magaza/braunshop",
    "Korayspor": "https://www.n11.com/magaza/korayspor",
    "Skechers": "https://www.n11.com/magaza/skechers",
    "Karaca": "https://www.n11.com/magaza/karaca",
    "Tefal": "https://www.n11.com/magaza/tefal",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.n11.com/"
}

def telegram_mesaj_gonder(mesaj):
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

def main():
    print("Fiyat ve Kupon taraması başlatılıyor...")
    eski_veriler = eski_fiyatlari_yukle()
    guncel_veriler = dict(eski_veriler)

    for magaza_adi, base_url in MAGAZALAR.items():
        print(f"{magaza_adi} taranıyor...")
        sayfa = 1
        toplam_urun = 0

        while True:
            # n11 sayfalama yapısı: ?pg=1, ?pg=2...
            url = f"{base_url}?pg={sayfa}" if sayfa == 1 else f"{base_url}?pg={sayfa}"
            
            try:
                response = requests.get(url, headers=HEADERS, timeout=20)
                if response.status_code != 200:
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                
                # n11 mağaza ürün kartları seçicisi
                urun_kartlari = soup.select("ul.list-items > li, div.column")
                
                # Eğer bu sayfada ürün bulunamadıysa döngüyü bitir (Son sayfayı geçtik demektir)
                if not urun_kartlari:
                    break

                bulunan_sayfa_urunu = 0
                for kart in urun_kartlari:
                    link_elem = kart.find("a", href=True)
                    if not link_elem:
                        continue
                    
                    urun_link = link_elem["href"]
                    if urun_link.startswith("/"):
                        urun_link = "https://www.n11.com" + urun_link

                    # Ürün adını al
                    baslik_elem = kart.find(["h3", "h4", "span"], class_=lambda x: x and any(c in x.lower() for c in ["title", "name"]))
                    urun_adi = baslik_elem.text.strip() if baslik_elem else "Ürün"

                    # Fiyatı al
                    fiyat_elem = kart.find(["ins", "span", "div"], class_=lambda x: x and any(c in x.lower() for c in ["price", "new", "amount"]))
                    if not fiyat_elem:
                        fiyat_elem = kart.find(string=lambda t: t and "TL" in t)

                    if fiyat_elem:
                        fiyat_metni = fiyat_elem.text if hasattr(fiyat_elem, 'text') else str(fiyat_elem)
                        fiyat_str = fiyat_metni.replace(".", "").replace(",", ".").replace("TL", "").strip()
                        
                        try:
                            fiyat = float(''.join(c for c in fiyat_str if c.isdigit() or c == '.'))
                        except ValueError:
                            continue

                        urun_id = urun_link.split("?")[0]
                        eski_fiyat = eski_veriler.get(urun_id)

                        if eski_fiyat is not None:
                            if fiyat < eski_fiyat:
                                mesaj = (
                                    f"🔥 <b>FİYAT DÜŞTÜ!</b>\n\n"
                                    f"🏪 <b>Mağaza:</b> {magaza_adi}\n"
                                    f"📦 <b>Ürün:</b> {urun_adi}\n"
                                    f"📉 <b>Eski Fiyat:</b> {eski_fiyat:.2f} TL\n"
                                    f"🏷️ <b>Yeni Fiyat:</b> {fiyat:.2f} TL\n\n"
                                    f"🔗 <a href='{urun_link}'>Ürüne Git</a>"
                                )
                                telegram_mesaj_gonder(mesaj)
                        
                        guncel_veriler[str(urun_id)] = fiyat
                        toplam_urun += 1
                        bulunan_sayfa_urunu += 1

                # Eğer bu sayfadan hiç ürün çekemediysek veya mağazanın son sayfasına geldiysek döngüyü kır
                if bulunan_sayfa_urunu == 0 or sayfa > 20:  # Güvenlik sınırı (maksimum 20 sayfa = çok büyük mağazalar için)
                    break

                sayfa += 1
            except Exception as e:
                print(f"{magaza_adi} sayfa {sayfa} hata: {e}")
                break

        print(f"{magaza_adi} - Toplam taranan ürün: {toplam_urun}")

    yeni_fiyatlari_kaydet(guncel_veriler)
    print("Tarama tamamlandı ve fiyatlar kaydedildi.")

if __name__ == "__main__":
    main()
