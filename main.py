import os
import time
from playwright.sync_api import sync_playwright

MAGAZALAR = {
    "Teknosa": "https://www.n11.com/magaza/teknosa/tum-urunler",
}

def main():
    print("Anti-bot korumalı tarama başlatılıyor...")
    with sync_playwright() as p:
        # Bot algılamasını bypass etmek için özel argümanlar ekliyoruz
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--window-size=1920,1080"
            ]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="tr-TR"
        )
        
        page = context.new_page()

        # Otomasyon izlerini gizle
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        def handle_request(request):
            if any(k in request.url for k in ["product", "search", "merchant", "store", "get"]):
                if request.resource_type in ["fetch", "xhr"]:
                    print(f"API/XHR İsteği: {request.url}")

        page.on("request", handle_request)

        for magaza_adi, base_url in MAGAZALAR.items():
            print(f"\n{magaza_adi} sayfasına bağlanılıyor...")
            try:
                page.goto(base_url, timeout=30000, wait_until="domcontentloaded")
                print(f"{magaza_adi} sayfası başarıyla yüklendi!")
                time.sleep(3)

                for _ in range(3):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(2)
            except Exception as e:
                print(f"Bağlantı hatası: {e}")

        browser.close()

if __name__ == "__main__":
    main()
