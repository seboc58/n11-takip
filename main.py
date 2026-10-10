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
        except Exception as e:
            print(f"JSON okuma hatasi: {e}")
    return {}

def yeni_fiyatlari_kaydet(veri):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(veri, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"JSON kaydetme hatasi: {e}")

def main():
    print("Fiyat ve Kupon taraması başlatılıyor...")
    eski_veriler = eski_fiyatlari_yukle()
    guncel_veriler = dict(eski_veriler)

    for magaza_adi, url in MAGAZALAR.items():
        try:
            print(f"{magaza_adi} taranıyor...")
            response = requests.get(url, headers=HEADERS, timeout=20)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                
                # 1. KUPON TARAMASI
                kupon_elementleri = soup.find_all(class_=lambda x: x and any(c in x.lower() for c in ["coupon", "voucher", "indirim", "kampanya"]))
                for elem in kupon_elementleri:
                    metin = elem.text.strip().replace("\n", " ")
                    if len(metin) > 10 and ("TL" in metin or "%" in metin or "Kupon" in metin):
                        kupon_key = f"kupon_{magaza_adi}_{metin}"
                        if kupon_key not in eski_veriler:
                            guncel_veriler[kupon_key] = True
                            mesaj = (
                                f"🎟️ <b>YENİ KUPON / KAMPANYA!</b>\n\n"
                                f"🏪 <b>Mağaza:</b> {magaza_adi}\n"
                                f"🏷️ <b>Detay:</b> {metin}\n\n"
                                f"🔗 <a href='{url}'>Mağazaya Git</a>"
                            )
                            telegram_mesaj_gonder(mesaj)

                # 2. ÜRÜN VE FİYAT TARAMASI (Orijinal çalışan kutu seçicisine dönüldü)
                urun_kartlari = soup.find_all(["li", "div"], class_=lambda x: x and "column" in x.lower())
                print(f"{magaza_adi} - Bulunan ürün kutusu: {len(urun_kartlari)}")

                for kart in urun_kartlari:
                    # Kart içerisinden başlık, fiyat ve link elemanlarını esnek çekelim
                    link_elem = kart.find("a", href=True)
                    if not link_elem:
                        continue
                    
                    urun_link = link_elem["href"]
                    # n11 linklerinin başında domain yoksa ekleyelim
                    if urun_link.startswith("/"):
                        urun_link = "https://www.n11.com" + urun_link

                    # Ürün adı (h3, h4 veya title içeren etiketler)
                    baslik_elem = kart.find(["h3", "h4", "span"], class_=lambda x: x and any(c in x.lower() for c in ["title", "name"]))
                    urun_adi = baslik_elem.text.strip() if baslik_elem else "İsimsiz Ürün"

                    # Fiyat (ins, span veya price içeren etiketler)
                    fiyat_elem = kart.find(["ins", "span"], class_=lambda x: x and any(c in x.lower() for c in ["price", "new", "amount"]))
                    if not fiyat_elem:
                        # Fiyat etiketi bulunamazsa kartın tamamındaki metinlerden bulmaya çalış
                        fiyat_elem = kart.find(text=lambda t: t and "TL" in t)

                    if fiyat_elem:
                        fiyat_str = fiyat_elem.text.strip().replace(".", "").replace(",", ".").replace("TL", "").strip()
                        try:
                            fiyat = float(''.join(c for c in fiyat_str if c.isdigit() or c == '.'))
                        except ValueError:
                            continue

                        urun_id = urun_link.split("?")[0] # Sadece ana link ID'sini baz al
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
                        
                        guncel_veriler[urun_id] = fiyat

            else:
                print(f"{magaza_adi} sayfasına erişilemedi, HTTP kod: {response.status_code}")
        except Exception as e:
            print(f"{magaza_adi} tarama hatasi: {e}")

    yeni_fiyatlari_kaydet(guncel_veriler)

if __name__ == "__main__":
    main()
