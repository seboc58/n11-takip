import os
import json
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

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

def telegram_mesaj_gonder(mesaj, page_client):
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

def main():
    print("Fiyat ve Kupon taraması başlatılıyor (Tüm Sayfalar Modu)...")
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
            sayfa = 1
            toplam_urun = 0
            gorulen_urunler = set()
            bos_sayfa_sayaci = 0

            # Büyük mağazalar için sayfa sınırını artırıyoruz (örn: 30 sayfa)
            while sayfa <= 30:
                url = f"{base_url}?pg={sayfa}"
                try:
                    page.goto(url, timeout=60000, wait_until="domcontentloaded")
                    time.sleep(2.5)
                    
                    html_content = page.content()
                    soup = BeautifulSoup(html_content, "html.parser")
                    
                    urun_linkleri = soup.find_all("a", href=True)
                    sayfa_yeni_urun = 0

                    for a in urun_linkleri:
                        href = a["href"]
                        if "/urun/" not in href:
                            continue

                        urun_link = href
                        if urun_link.startswith("/"):
                            urun_link = "https://www.n11.com" + urun_link

                        urun_id = urun_link.split("?")[0]
                        if urun_id in gorulen_urunler:
                            continue

                        kutu = a.find_parent(["li", "div", "article"])
                        if not kutu:
                            kutu = a

                        urun_adi = "Ürün"
                        title_elem = kutu.find(["h3", "h4", "span", "p"], class_=lambda x: x and any(c in str(x).lower() for c in ["title", "name", "desc"]))
                        if title_elem:
                            urun_adi = title_elem.text.strip()
                        elif a.text.strip():
                            urun_adi = a.text.strip()

                        fiyat = 0.0
                        fiyat_elem = kutu.find(["ins", "span", "div", "p"], class_=lambda x: x and any(c in str(x).lower() for c in ["price", "new", "amount", "discount"]))
                        
                        if fiyat_elem:
                            fiyat_metni = fiyat_elem.text.replace(".", "").replace(",", ".").replace("TL", "").strip()
                            try:
                                fiyat = float(''.join(c for c in fiyat_metni if c.isdigit() or c == '.'))
                            except:
                                pass
                        
                        if fiyat <= 0:
                            import re
                            kutu_metni = kutu.get_text()
                            fiyat_bulunanlar = re.findall(r'([\d\.]+,\d{2})\s*TL', kutu_metni)
                            if fiyat_bulunanlar:
                                temiz_fiyat = fiyat_bulunanlar[0].replace(".", "").replace(",", ".")
                                try:
                                    fiyat = float(temiz_fiyat)
                                except:
                                    pass

                        if fiyat <= 0:
                            continue

                        gorulen_urunler.add(urun_id)
                        sayfa_yeni_urun += 1
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

                    print(f"-> Sayfa {sayfa} tarandı. Yeni ürün: {sayfa_yeni_urun} (Toplam: {toplam_urun})")

                    # Eğer bu sayfada hiç yeni ürün bulunamadıysa mağazanın sonuna gelmişizdir
                    if sayfa_yeni_urun == 0:
                        bos_sayfa_sayaci += 1
                        if bos_sayfa_sayaci >= 2: # Üst üste 2 boş sayfa gelirse döngüyü bitir
                            break
                    else:
                        bos_sayfa_sayaci = 0

                    sayfa += 1
                except Exception as e:
                    print(f"{magaza_adi} sayfa {sayfa} hata: {e}")
                    break

            print(f"==> {magaza_adi} Tamamlandı - Toplam taranan ürün: {toplam_urun}")

        browser.close()

    yeni_fiyatlari_kaydet(guncel_veriler)
    print("\nTüm tarama tamamlandı ve fiyatlar kaydedildi.")

if __name__ == "__main__":
    main()
