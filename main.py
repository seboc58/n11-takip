
def urun_adi_bul(kart, link, urun_url=None):
    # Fiyat metinlerini ürün adı olarak kabul etme.
    def gecerli_ad(metin):
        metin = " ".join(str(metin).split()).strip()
        if len(metin) < 4:
            return None
        if re.search(r"\bTL\b|₺", metin, re.IGNORECASE):
            return None
        if re.fullmatch(r"[\d.,\s]+", metin):
            return None
        if fiyat_metnini_temizle(metin) is not None:
            # Örneğin "5.339,53 TL" gibi metinleri ele.
            if re.search(r"\d", metin) and len(metin) < 35:
                return None
        return metin[:180]

    # Önce ürün adına özel HTML alanlarını dene.
    seciciler = [
        ("a", {"class": re.compile(r"(product.?name|product.?title|title)", re.I)}),
        ("h3", {"class": re.compile(r"(product.?name|product.?title|title)", re.I)}),
        ("h2", {"class": re.compile(r"(product.?name|product.?title|title)", re.I)}),
        ("img", {"alt": True}),
    ]

    for etiket, attrs in seciciler:
        eleman = kart.find(etiket, attrs=attrs)
        if eleman:
            if etiket == "img":
                metin = eleman.get("alt", "")
            else:
                metin = eleman.get("title") or metin_al(eleman)

            ad = gecerli_ad(metin)
            if ad:
                return ad

    # Son çare: ürün URL'sindeki isim bölümünü kullan.
    if urun_url:
        slug = urlsplit(urun_url).path.rstrip("/").split("/")[-1]
        slug = re.sub(r"-\d+(?:-\d+)*$", "", slug)
        slug = slug.replace("-", " ").strip()

        if slug:
            return slug[:180].title()

    # Güvenilir isim bulunamadıysa fiyatı isim diye kaydetme.
    return "Ürün adı bulunamadı"
