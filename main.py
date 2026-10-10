import os
import requests
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# Dilediğiniz kadar mağazayı buraya ekleyebilirsiniz
MAGAZALAR = {
    "Teknosa": "https://www.n11.com/magaza/teknosa",
    "Mediamarkt": "https://www.n11.com/magaza/mediamarkt",
    "N11": "https://www.n11.com/magaza/n11",
    "Korayspor": "https://www.n11.com/magaza/korayspor",
    "Skechers": "https://www.n11.com/magaza/skechers",
    "Jack%Jones": "https://www.n11.com/magaza/jack-jones",
    "Braunshop": "https://www.n11.com/magaza/braunshop",
    # Örnek yeni mağazalar eklemek isterseniz:
    # "Samsung": "https://www.n11.com/magaza/samsung",
    # "Xiaomi": "https://www.n11.com/magaza/xiaomi"
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
                
                # 1. KUPON / KAMPANYA TARAMASI
                # Mağaza sayfasındaki kupon, indirim veya kampanya etiketlerini yakalar
                kupon_elementleri = soup.find_all(class_=lambda x: x and any(c in x.lower() for c in ["coupon", "voucher", "indirim", "kampanya", "meta"]))
                
                bulunan_kuponlar = set()
                for elem in kupon_elementleri:
                    metin = elem.text.strip().replace("\n", " ")
                    # Anlamlı uzunluktaki kupon/kampanya metinlerini filtrele
                    if len(metin) > 10 and ("TL" in metin or "%" in metin or "Kupon" in metin or "İndirim" in metin):
                        bulunan_kuponlar.add(metin)

                for kupon in bulunan_kuponlar:
                    print(f"Kupon Yakalandı -> {magaza_adi}: {kupon}")
                    mesaj = (
                        f"🎟️ <b>YENİ KUPON / KAMPANYA BULUNDU!</b>\n\n"
                        f"🏪 <b>Mağaza:</b> {magaza_adi}\n"
                        f"🏷️ <b>Detay:</b> {kupon}\n\n"
                        f"🔗 <a href='{url}'>Mağazaya Git</a>"
                    )
                    telegram_mesaj_gonder(mesaj)

                # 2. ÜRÜN TARAMASI
                urunler = soup.find_all(["li", "div"], class_=lambda x: x and any(c in x.lower() for c in ["column", "product", "item"]))
                print(f"{magaza_adi} - Bulunan ürün kutusu: {len(urunler)}")

            else:
                print(f"{magaza_adi} sayfasına erişilemedi, HTTP kod: {response.status_code}")
        except Exception as e:
            print(f"{magaza_adi} tarama hatasi: {e}")

if __name__ == "__main__":
    main()
