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

# Mağaza sayfaları yerine koruması daha esnek olan n11 arama / kategori sayfaları
MAGAZALAR = {
    "Teknosa Ürünleri": "https://www.n11.com/arama?q=teknosa",
    "MediaMartk Ürünleri": "https://www.n11.com/arama?q=mediamarkt",
    "Braun Ürünleri": "https://www.n11.com/arama?q=braun"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.n11.com/"
}

fiyat_hafizasi = {}
kupon_hafizasi = {}

def telegram_mesaj_gonder(mesaj):
    try:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(api_url, data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"Telegram gönderme hatasi: {e}", flush=True)

def magazalari_tara():
    global fiyat_hafizasi
    
    # Test için sahte ürün
    fiyat_hafizasi["Test Ürünü - Kontrol"] = 999999

    while True:
        for magaza_adi, url in MAGAZALAR.items():
            try:
                print(f"{magaza_adi} arama sayfasından taranıyor...", flush=True)
                response = requests.get(url, headers=HEADERS, timeout=20)
                
                print(f"HTTP Durum Kodu: {response.status_code}", flush=True)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    
                    # n11 arama sonuçlarındaki ürün kartları (genellikle li veya div elementleri)
                    urunler = soup.find_all(["li", "div"], class_=lambda x: x and any(c in x.lower() for c in ["column", "product", "item"]))
                    print(f"Bulunan ürün kutusu sayısı: {len(urunler)}", flush=True)

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
                            print(f"Ürün Yakalandı -> {urun_adi} | Fiyat: {guncel_fiyat}", flush=True)

                            if hafiza_anahtari not in fiyat_hafizasi:
                                fiyat_hafizasi[hafiza_anahtari] = guncel_fiyat
                            else:
                                eski_fiyat = fiyat_hafizasi[hafiza_anahtari]
                                if guncel_fiyat != eski_fiyat:
                                    mesaj = (
                                        f"🔔 <b>FİYAT DEĞİŞTİ!</b>\n\n"
                                        f"🏪 <b>Kategori:</b> {magaza_adi}\n"
                                        f"📦 <b>Ürün:</b> {urun_adi}\n"
                                        f"💵 <b>Eski Fiyat:</b> {eski_fiyat:.2f} TL\n"
                                        f"🏷️ <b>Yeni Fiyat:</b> {guncel_fiyat:.2f} TL\n\n"
                                        f"🔗 <a href='{link_etiketi.get('href', url)}'>Ürüne Git</a>"
                                    )
                                    telegram_mesaj_gonder(mesaj)
                                    fiyat_hafizasi[hafiza_anahtari] = guncel_fiyat
                else:
                    print(f"Sayfa yüklenemedi, HTTP kod: {response.status_code}", flush=True)
            except Exception as e:
                print(f"{magaza_adi} tarama hatasi: {e}", flush=True)
            
            time.sleep(10)
        
        time.sleep(300)

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fiyat Botu Aktif!")

if __name__ == "__main__":
    print("Bot başlatılıyor...", flush=True)
    telegram_mesaj_gonder("🚀 Bot Arama Sayfası Modunda Başlatıldı!")
    
    threading.Thread(target=magazalari_tara, daemon=True).start()
    print("Tarama thread'i baslatildi!", flush=True)
    
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()
