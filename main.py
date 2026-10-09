import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
import requests
from bs4 import BeautifulSoup

# Telegram Bilgileri
TELEGRAM_TOKEN = "8848387261:AAHbWKc2-CLx2jXDBY91fAcOio3CTiWtTkw"
CHAT_ID = "485785856"

URL = "https://www.n11.com/magaza/teknosa"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

fiyat_hafizasi = {}

def telegram_mesaj_gonder(mesaj):
    try:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(api_url, data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "HTML"})
    except Exception as e:
        print(f"Telegram hatasi: {e}")

def magazayi_tara():
    global fiyat_hafizasi
    while True:
        try:
            response = requests.get(URL, headers=HEADERS, timeout=15)
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

                        if urun_adi not in fiyat_hafizasi:
                            fiyat_hafizasi[urun_adi] = guncel_fiyat
                        else:
                            eski_fiyat = fiyat_hafizasi[urun_adi]
                            if guncel_fiyat != eski_fiyat:
                                mesaj = (
                                    f"🔔 <b>FİYAT DEĞİŞTİ!</b>\n\n"
                                    f"📦 <b>Ürün:</b> {urun_adi}\n"
                                    f"💵 <b>Eski Fiyat:</b> {eski_fiyat:.2f} TL\n"
                                    f"🏷️ <b>Yeni Fiyat:</b> {guncel_fiyat:.2f} TL\n\n"
                                    f"🔗 <a href='{link}'>Ürüne Gitmek İçin Tıklayın</a>"
                                )
                                telegram_mesaj_gonder(mesaj)
                                fiyat_hafizasi[urun_adi] = guncel_fiyat
        except Exception as e:
            print(f"Tarama hatasi: {e}")
        
        time.sleep(600)

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Aktif!")

if __name__ == "__main__":
    telegram_mesaj_gonder("🚀 n11 Teknosa Mağaza Takip Botu Bulut Üzerinde Başlatıldı!")
    
    # Tarama işlemini arka planda başlat
    threading.Thread(target=magazayi_tara, daemon=True).start()
    
    # Render Web Service portu
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()
