import os
import json
import time
from playwright.sync_api import sync_playwright

MAGAZALAR = {
    "Teknosa": "https://www.n11.com/magaza/teknosa/tum-urunler",
}

def main():
    print("Debug taraması başlatılıyor...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for magaza_adi, base_url in MAGAZALAR.items():
            print(f"\n{magaza_adi} taranıyor -> {base_url}")
            page.goto(base_url, timeout=60000, wait_until="domcontentloaded")
            time.sleep(3)

            # Sayfayı biraz kaydıralım
            for step in range(1, 5):
                page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * ({step} / 5));")
                time.sleep(1)

            # Sayfadaki tüm ürün bağlantılarını sayalım
            links = page.locator("a[href*='/urun/']").all_inner_texts()
            print(f"Bulunan /urun/ içeren link sayısı: {len(links)}")
            
            # İlk 3 linkin başlığını ve adresini yazdır
            all_links_elements = page.locator("a[href*='urun']")
            for i in range(min(5, all_links_elements.count())):
                el = all_links_elements.nth(i)
                print(f"Örnek Link {i+1}: {el.get_attribute('href')}")

        browser.close()

if __name__ == "__main__":
    main()
