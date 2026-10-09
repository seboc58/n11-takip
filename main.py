import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
import requests
from bs4 import BeautifulSoup

# Telegram Bilgileri
TELEGRAM_TOKEN = "8848387261:AAHbWKc2-CLx2jXDBY91fAcOio3CTiWtTkw"
CHAT_ID = "485785856"

# 🎯 Takip Etmek İstediğiniz Mağazaların Listesi
MAGAZALAR = {
    "Teknosa": "https://www.n11.com/magaza/teknosa",
    "Mediamarkt": "https://www.n11.com/magaza/mediamarkt",
    "N11": "https://www.n11.com/magaza/n11",
    "Karaca": "https://www.n11.com/magaza/karaca",
    "Skechers": "https://www.n11.com/magaza/skerchers"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Her mağaza için ayrı fiyat hafızası tutulur
fiyat_hafizasi = {}

def telegram_mesaj_gonder(mesaj):
    try:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(api_url, data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "HTML"})
    except Exception as e:
        print(f"Telegram hatasi: {e}")

def magazalari_tara():
    global fiyat_hafizasi
    while True:
        for magaza_adi, url in MAGAZALAR.items():
            try:
                response = requests.get(url, headers=HEADERS, timeout=15)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    urunler = soup.find_all("li", class_="column")

                    for urun in urunler:
                        baslik_etiketi = urun.find("h3", class_="productName")
                        fiyat_etiketi = urun.find("ins") or urun.find("span", class_="newPrice")
                        link_etiketi = urun.find("a")

                        if baslik_etiketi and fiyat_etiketi and link_etiketi:
                            urun_adi = baslik_etiketi.text.strip()
                            fiyat_text = fiyat_etiketi.text.strip().replace("TL", "").replace(".", "").replace(",", ".").strip()
                            link = link_etiketi.get("href", "")

                            try:
                                guncel_fiyat = float(fiyat_text)
                            except ValueError:
                                continue

                            # Mağaza bazlı anahtar (Örn: "Teknosa - iPhone 13")
                            hafiza_anahtari = f"{magaza_adi} - {urun_adi}"

                            if hafiza_anahtari not in fiyat_hafizasi:
                                fiyat_hafizasi[hafiza_anahtari] = guncel_fiyat
                            else:
                                eski_fiyat = fiyat_hafizasi[hafiza_anahtari]
                                if guncel_fiyat != eski_fiyat:
                                    mesaj = (
                                        f"🔔 <b>FİYAT DEĞİŞTİ!</b>\n\n"
                                        f"🏪 <b>Mağaza:</b> {magaza_adi}\n"
                                        f"📦 <b>Ürün:</b> {urun_adi}\n"
                                        f"💵 <b>Eski Fiyat:</b> {eski_fiyat:.2f} TL\n"
                                        f"🏷️ <b>Yeni Fiyat:</b> {guncel_fiyat:.2f} TL\n\n"
                                        f"🔗 <a href='{link}'>Ürüne Gitmek İçin Tıklayın</a>"
                                    )
                                    telegram_mesaj_gonder(mesaj)
                                    fiyat_hafizasi[hafiza_anahtari] = guncel_fiyat
            except Exception as e:
                print(f"{magaza_adi} tarama hatasi: {e}")
            
            # Mağazalar arasında 3 saniye bekle (n11 engeline takılmamak için)
            time.sleep(3)
        
        # Tüm mağazalar tarandıktan sonra 5 dakika bekle
        time.sleep(300)

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Coklu Magaza Takip Botu Aktif!")

if __name__ == "__main__":
    telegram_mesaj_gonder("🚀 Çoklu Mağaza Takip Botu Güncellendi ve Başlatıldı!")
    
    threading.Thread(target=magazalari_tara, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()
