
# ══════════════════════════════════════════
#  ETİKET SAYFASI
# ══════════════════════════════════════════
@app.get("/etiket", response_class=HTMLResponse)
async def etiket_sayfa(request: Request, parti: str = "", urun: str = "", miktar: float = 5, tarih: str = ""):
    s = session_al(request)
    if not s: return RedirectResponse("/giris")

    from datetime import datetime, timedelta

    # Tarih işle
    if not tarih:
        tarih = bugun()
    try:
        p = tarih.split(".")
        uretim_dt = datetime(int(p[2]), int(p[1]), int(p[0]))
    except:
        uretim_dt = datetime.now()

    # SKT = +6 ay
    ay = uretim_dt.month + 6
    yil = uretim_dt.year
    if ay > 12:
        ay -= 12
        yil += 1
    skt = f"{uretim_dt.day:02d}.{ay:02d}.{yil}"

    # Gramaj ayrıştır - "5 KG", "500 gr", "1 KG"
    import re
    eslesme = re.match(r"([0-9,.]+)\s*(.*)", str(miktar))
    if eslesme:
        gramaj_sayi = eslesme.group(1).replace(".0", "")
        gramaj_birim = "KG"
    else:
        gramaj_sayi = str(miktar)
        gramaj_birim = "KG"

    return templates.TemplateResponse("etiket.html", {
        "request": request,
        "skt": skt,
        "parti": parti or "URT-" + datetime.now().strftime("%y%m%d-%H%M"),
        "gramaj_sayi": gramaj_sayi,
        "gramaj_birim": gramaj_birim,
        "urun": urun,
    })
