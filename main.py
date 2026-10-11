import os
import json
import time
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
DATA_FILE = "fiyatlar.json"

# Mağazaların doğrudan tüm ürünler listeleme linkleri
MAGAZALAR = {
    "Teknosa": "https://www.n11.com/magaza/teknosa/tum-urunler",
    "Mediamarkt": "https://www.n11.com/magaza/mediamarkt/tum-urunler",
    "Braunshop": "https://www.n11.com/magaza/braunshop/tum-urunler",
    "Korayspor": "https://www.n11.com/magaza/korayspor/tum-urunler",
    "Skechers": "https://www.n11.com/magaza/skechers/tum-urunler",
    "Karaca": "https://www.n11.com/magaza/karaca/tum-urunler",
    "Tefal": "https://www.n11.com/magaza/tefal/tum-urunler",
}

def telegram_mesaj_gonder(mesaj, page_client):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    try:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        page_client.request.post(api_url, data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "HTML"})
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

def fiyat_temizle(metin):
    if not metin:
        return 0.0
    
    # Watt veya teknik ölçü birimi içeren metinleri ele
    if re.search(r'\d+\s*(w|watt|ml|lt|gb|mah|cm|parça)\b', metin.lower()):
        return 0.0

    m = re.search(r'([\d\.\,]+)', metin.replace("TL", "").replace("TL.", "").strip())
    if not m:
        return 0.0
    
    val = m.group(1)
    if "." in val and "," in val:
        val = val.replace(".", "").replace(",", ".")
    elif "," in val:
        val = val.replace(",", ".")
    else:
        if val.count(".") == 1 and len(val.split(".")[1]) == 2:
            pass 
        elif "." in val:
            val = val.replace(".", "")

    try:
        f = float(val)
        return f if 15.0 <= f <= 300000.0 else 0.0
    except:
        return 0.0

def main():
    print("Fiyat ve Kupon taraması başlatılıyor (Kademeli Yükleme & Derin Tarama Modu)...")
    eski_veriler = eski_fiyatlari_yukle()
    guncel_veriler = dict(eski_veriler)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        for magaza_adi, base_url in MAGAZALAR.items():
            print(f"\n{magaza_adi} taranıyor...")
            gorulen_urunler = set()

            try:
                page.goto(base_url, timeout=60000, wait_until="domcontentloaded")
                time.sleep(2)

                # Kademeli kaydırma: Yavaş yavaş aşağı inerek lazy-load görselleri/ürünleri tetikle
                for step in range(1, 8):
                    page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * ({step} / 7));")
                    time.sleep(1)

                html_content = page.content()
                soup = BeautifulSoup(html_content, "html.parser")
                
                # N11 ürün kartlarını kapsayan tüm olası sınıflar
                kartlar = soup.select("li.column, div.column, div.pro, div.productItem, li.pro")
                if not kartlar:
                    kartlar = soup.find_all(["li", "div"], class_=lambda x: x and any(c in str(x).lower() for c in ["column", "pro", "product"]))

                toplam_urun = 0

                for kart in kartlar:
                    link_elem = kart.find("a", href=True)
                    if not link_elem or "/urun/" not in link_elem["href"]:
                        continue

                    urun_link = link_elem["href"]
                    if urun_link.startswith("/"):
                        urun_link = "https://www.n11.com" + urun_link

                    urun_id = urun_link.split("?")[0]
                    if urun_id in gorulen_urunler:
                        continue

                    # Ürün adı alma
                    baslik_elem = kart.find(["h3", "h4", "span", "p"], class_=lambda x: x and any(c in str(x).lower() for c in ["title", "name", "desc"]))
                    urun_adi = baslik_elem.text.strip() if baslik_elem else (link_elem.text.strip() or "Ürün")

                    # Fiyat alma
                    fiyat_etiketleri = kart.select("ins, span.newPrice, div.price, span.price, p.price")
                    fiyatlar = []
                    
                    for etiket in fiyat_etiketleri:
                        f = fiyat_temizle(etiket.text)
                        if f > 0:
                            fiyatlar.append(f)

                    if not fiyatlar:
                        f = fiyat_temizle(kart.get_text())
                        if f > 0:
                            fiyatlar.append(f)

                    if not fiyatlar:
                        continue

                    fiyat = min(fiyatlar)
                    if fiyat <= 0:
                        continue

                    gorulen_urunler.add(urun_id)
                    toplam_urun += 1

                    eski_fiyat = eski_veriler.get(urun_id)
                    if eski_fiyat is not None and fiyat < eski_fiyat:
                        mesaj = (
                            f"🔥 <b>FİYAT DÜŞTÜ!</b>\n\n"
                            f"🏪 <b>Mağaza:</b> {magaza_adi}\n"
                            f"📦 <b>Ürün:</b> {urun_adi[:60]}...\n"
                            f"📉 <b>Eski Fiyat:</b> {eski_fiyat:.2f} TL\n"
                            f"🏷️ <b>Yeni Fiyat:</b> {fiyat:.2f} TL\n\n"
                            f"🔗 <a href='{urun_link}'>Ürüne Git</a>"
                        )
                        telegram_mesaj_gonder(mesaj, page)

                    guncel_veriler[str(urun_id)] = fiyat

                print(f"==> {magaza_adi} Tamamlandı - Toplam taranan ürün: {toplam_urun}")

            except Exception as e:
                print(f"{magaza_adi} taranırken hata: {e}")

        browser.close()

    yeni_fiyatlari_kaydet(guncel_veriler)
    print("\nTüm tarama tamamlandı ve fiyatlar kaydedildi.")

if __name__ == "__main__":
    main()
