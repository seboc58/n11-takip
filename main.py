name: N11 Fiyat Takip Botu

on:
  schedule:
    # Her 30 dakikada bir çalışır (UTC).
    - cron: '*/30 * * * *'
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: n11-fiyat-takip
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - name: Depoyu Kopyala
        uses: actions/checkout@v4
        with:
          ref: ${{ github.ref_name }}
          fetch-depth: 0

      - name: Python Kurulumu
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Gerekli Paketleri Yükle
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Botu Çalıştır
        run: python main.py
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          CHAT_ID: ${{ secrets.CHAT_ID }}

      - name: Fiyat Dosyasını Depoya Kaydet
        if: success()
        run: |
          if [ ! -f fiyatlar.json ]; then
            echo "fiyatlar.json oluşturulmadı; kaydedilecek dosya yok."
            exit 0
          fi

          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add fiyatlar.json

          if git diff --cached --quiet; then
            echo "Fiyat dosyasında değişiklik yok; commit gerekmiyor."
          else
            git commit -m "Fiyat takip verilerini güncelle"
            git push origin HEAD:${GITHUB_REF_NAME}
          fi
