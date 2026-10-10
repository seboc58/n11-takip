import os
import requests
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

MAGAZALAR = {
    "Teknosa": "https://www.n11.com/magaza/teknosa",
    "Mediamarkt": "https://www.n11.com/magaza/mediamarkt",
    "Braunshop": "https://www.n11.com/magaza/braunshop"
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

def main():
    print("Fiyat ve Kupon taraması başlatılıyor...")
    
    for magaza_adi, url in MAGAZALAR.items():
        try:
            print(f"{magaza_adi} taranıyor...")
            response = requests.get(url, headers=HEADERS, timeout=20)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                
                # 1. KUPON TARAMASI
                kupon_elementleri = soup.find_all(class_=lambda x: x and any(c in x.lower() for c in ["coupon", "voucher", "indirim", "kampanya"]))
                for elem in kupon_elementleri:
                    kupon_metni = elem.text.strip().replace("\n", " ")
                    if len(kupon_metni) > 8:
                        mesaj = (
                            f"🎟️ <b>YENİ MAĞAZA KUPONU!</b>\n\n"
                            f"🏪 <b>Mağaza:</b> {magaza_adi}\n"
                            f"🏷️ <b>Detay:</b> {kupon_metni}\n\n"
                            f"🔗 <a href='{url}'>Mağazaya Git</a>"
                        )
                        telegram_mesaj_gonder(mesaj)

                # 2. ÜRÜN TARAMASI
                urunler = soup.find_all(["li", "div"], class_=lambda x: x and any(c in x.lower() for c in ["column", "product", "item"]))
                print(f"Bulunan ürün kutusu: {len(urunler)}")

                for urun in urunler:
                    baslik_etiketi = urun.find(["h3", "h4", "a"], class_=lambda x: x and any(c in x.lower() for c in ["name", "title"]))
                    fiyat_etiketi = urun.find("ins") or urun.find(class_=lambda x: x and any(c in x.lower() for c in ["price", "newprice", "fiyat"]))
                    link_etiketi = urun.find("a")

                    if baslik_etiketi and fiyat_etiketi and link_etiketi:
                        urun_adi = baslik_etiketi.text.strip()
                        fiyat_text = fiyat_etiketi.text.strip().replace("TL", "").replace("₺", "").replace(".", "").replace(",", ".").strip()
                        temiz_fiyat = "".join([c for c in fiyat_text if c.isdigit() or c == '.'])

                        try:
                            guncel_fiyat = float(temiz_fiyat)
                        except ValueError:
                            continue

                        if len(urun_adi) < 3 or guncel_fiyat <= 0:
                            continue

                        # Şimdilik örnek log
                        print(f"Ürün: {urun_adi} | Fiyat: {guncel_fiyat}")
            else:
                print(f"{magaza_adi} sayfasına erişilemedi, HTTP kod: {response.status_code}")
        except Exception as e:
            print(f"{magaza_adi} tarama hatasi: {e}")

if __name__ == "__main__":
    main()
