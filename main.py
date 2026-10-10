import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
import requests
from bs4 import BeautifulSoup

# ==========================================
# AYARLAR
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# Takip edilecek mağazalar (Testi hızlandırmak için şimdilik sadece Teknosa açık kalsın)
MAGAZALAR = {
    "Teknosa": "https://www.n11.com/magaza/teknosa"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}

fiyat_hafizasi = {}
kupon_hafizasi = {}

def telegram_mesaj_gonder(mesaj):
    try:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(api_url, data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"Telegram gönderme hatasi: {e}")

def magazalari_tara():
    global fiyat_hafizasi
    while True:
        for magaza_adi, url in MAGAZALAR.items():
            try:
                print(f"{magaza_adi} taranıyor...")
                response = requests.get(url, headers=HEADERS, timeout=15)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    urunler = soup.find_all(["li", "div"], class_=lambda x: x and any(c in x.lower() for c in ["column", "product", "item"]))
                    
                    print(f"Bulunan hammadde ürün kutusu sayısı: {len(urunler)}")

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

                            hafiza_anahtari = f"{magaza_adi} - {urun_adi}"
                            print(f"Ürün Yakalandı -> {urun_adi} | Fiyat: {guncel_fiyat}")

                            if hafiza_anahtari not in fiyat_hafizasi:
                                # TEST AMAÇLI: İlk yakalanan ürüne yapay olarak 999999 TL yazalım ki fark atıp Telegram'a bassın!
                                fiyat_hafizasi[hafiza_anahtari] = 999999 
                            else:
                                eski_fiyat = fiyat_hafizasi[hafiza_anahtari]
                                if guncel_fiyat != eski_fiyat:
                                    mesaj = (
                                        f"🔔 <b>FİYAT DEĞİŞTİ! (TEST)</b>\n\n"
                                        f"🏪 <b>Mağaza:</b> {magaza_adi}\n"
                                        f"📦 <b>Ürün:</b> {urun_adi}\n"
                                        f"💵 <b>Eski Fiyat:</b> {eski_fiyat:.2f} TL\n"
                                        f"🏷️ <b>Yeni Fiyat:</b> {guncel_fiyat:.2f} TL\n\n"
                                        f"🔗 <a href='{link_etiketi.get('href', url)}'>Ürüne Git</a>"
                                    )
                                    telegram_mesaj_gonder(mesaj)
                                    fiyat_hafizasi[hafiza_anahtari] = guncel_fiyat
            except Exception as e:
                print(f"{magaza_adi} tarama hatasi: {e}")
            
            time.sleep(5)
        
        time.sleep(60)

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fiyat Botu Aktif!")

if __name__ == "__main__":
    telegram_mesaj_gonder("🚀 Bot Başlatıldı ve Test Modunda!")
    threading.Thread(target=magazalari_tara, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()
