import os
import time
from playwright.sync_api import sync_playwright

MAGAZALAR = {
    "Teknosa": "https://www.n11.com/magaza/teknosa/tum-urunler",
}

def main():
    print("Ağ trafiği izleniyor...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Sayfanın yaptığı tüm ağ isteklerini yakalayalım
        def handle_request(request):
            if "product" in request.url or "search" in request.url or "merchant" in request.url or "store" in request.url:
                if request.resource_type in ["fetch", "xhr"]:
                    print(f"XHR/API İsteği Yakalandı: {request.url}")

        page.on("request", handle_request)

        for magaza_adi, base_url in MAGAZALAR.items():
            print(f"\n{magaza_adi} taranıyor...")
            page.goto(base_url, timeout=60000, wait_until="domcontentloaded")
            time.sleep(5)

            # Biraz aşağı kaydıralım ki istekler tetiklensin
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)

        browser.close()

if __name__ == "__main__":
    main()
