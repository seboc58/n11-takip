import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
import requests
from bs4 import BeautifulSoup

# ==========================================
# AYARLAR (Kendi Bilgilerinizi Girin)
# ==========================================
TELEGRAM_TOKEN = "8848387261:AAHbWKc2-CLx2jXDBY91fAcOio3CTiWtTkw"
CHAT_ID = "485785856"

# Takip edilecek mağazalar (İstediğiniz kadar ekleyebilirsiniz)
MAGAZALAR = {
    "Teknosa": "https://www.n11.com/magaza/teknosa",
    "Mediamarkt": "https://www.n11.com/magaza/mediamarkt",
    "N11": "https://www.n11.com/magaza/n11",
    "Braunshop": "https://www.n11.com/magaza/braunshop",
    "Karaca": "https://www.n11.com/magaza/karaca",
    "Skechers": "https://www.n11.com/magaza/skechers"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Hafıza sözlükleri
fiyat_hafizasi = {}
kupon_hafizasi = {}

def telegram_mesaj_gonder(mesaj):
    try:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(api_url, data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"Telegram gönderme hatasi: {e}")

def kuponlari_tara(soup, magaza_adi, magaza_url):
    global kupon_hafizasi
    try:
        # n11 mağaza sayfalarındaki olası kupon sınıfları
        kupon_elementleri = soup.find_all(class_=["coupon-item", "seller-coupon", "voucher-item", "coupon"])
        
        for elem in kupon_elementleri:
            kupon_metni = elem.text.strip().replace("\n", " ")
            # Çok kısa veya anlamsız metinleri ele
            if len(kupon_metni) > 5:
                hafiza_anahtari = f"{magaza_adi}_{kupon_metni}"
                
                if hafiza_anahtari not in kupon_hafizasi:
                    kupon_hafizasi[hafiza_anahtari] = True
                    
                    mesaj = (
                        f"🎟️ <b>YENİ MAĞAZA KUPONU BULUNDU!</b>\n\n"
                        f"🏪 <b>Mağaza:</b> {magaza_adi}\n"
                        f"🏷️ <b>Kupon Detayı:</b> {kupon_metni}\n\n"
                        f"🔗 <a href='{magaza_url}'>Kuponu Almak İçin Mağazaya Git</a>"
                    )
                    telegram_mesaj_gonder(mesaj)
    except Exception as e:
        print(f"{magaza_adi} kupon tarama hatasi: {e}")

def magazalari_tara():
    global fiyat_hafizasi
    while True:
        for magaza_adi, url in MAGAZALAR.items():
            try:
                response = requests.get(url, headers=HEADERS, timeout=15)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")

                    # 1. KUPON TARAMASI
                    kuponlari_tara(soup, magaza_adi, url)

                    # 2. ÜRÜN FİYAT TARAMASI
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
            
            # Mağazalar arası 3 saniye bekle
            time.sleep(3)
        
        # Tüm mağazalar tarandıktan sonra 5 dakika (300 saniye) bekle
        time.sleep(300)

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fiyat ve Kupon Takip Botu Aktif!")

if __name__ == "__main__":
    telegram_mesaj_gonder("🚀 Fiyat ve Kupon Takip Botu Güncellendi ve Başlatıldı!")
    
    threading.Thread(target=magazalari_tara, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()
