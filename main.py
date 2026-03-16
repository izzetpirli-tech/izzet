import os
import json
import hashlib
import secrets
import re as _re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="Elfiga ERP")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SESSIONS = {}

def db_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def hash_sifre(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def bugun() -> str:
    return datetime.now().strftime("%d.%m.%Y")

def session_olustur(tenant_id, username, rol) -> str:
    sid = secrets.token_hex(32)
    SESSIONS[sid] = {"tenant_id": tenant_id, "username": username, "rol": rol, "zaman": datetime.now()}
    return sid

def session_al(request: Request) -> Optional[dict]:
    sid = request.cookies.get("session_id")
    if not sid or sid not in SESSIONS:
        return None
    s = SESSIONS[sid]
    if datetime.now() - s["zaman"] > timedelta(hours=8):
        del SESSIONS[sid]
        return None
    return s

def veri_al(tenant_id: int) -> dict:
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM tenant_veriler WHERE tenant_id=%s AND key='veriler'", (tenant_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"stoklar": {}, "hareketler": [], "detayli_stok": [], "hazir_manti_stok": 0.0, "birim_fiyatlar": {}, "coklu_receteler": {}}
    v = row["value"]
    return dict(v) if not isinstance(v, dict) else v

def veri_kaydet(tenant_id: int, v: dict):
    conn = db_conn()
    cur = conn.cursor()
    vstr = json.dumps(v, ensure_ascii=False, default=str)
    cur.execute("""
        INSERT INTO tenant_veriler (tenant_id, key, value, updated_at)
        VALUES (%s, 'veriler', %s, NOW())
        ON CONFLICT (tenant_id, key) DO UPDATE SET value=%s, updated_at=NOW()
    """, (tenant_id, vstr, vstr))
    conn.commit()
    conn.close()

# AUTH
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    s = session_al(request)
    return RedirectResponse("/dashboard" if s else "/giris")

@app.get("/giris", response_class=HTMLResponse)
async def giris_get(request: Request):
    if session_al(request):
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("giris.html", {"request": request, "hata": None})

@app.post("/giris", response_class=HTMLResponse)
async def giris_post(request: Request, username: str = Form(...), sifre: str = Form(...)):
    conn = db_conn()
    cur = conn.cursor()
    h = hash_sifre(sifre)
    cur.execute("SELECT * FROM superadminler WHERE username=%s AND password_hash=%s", (username, h))
    if cur.fetchone():
        conn.close()
        sid = session_olustur(0, username, "superadmin")
        resp = RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie("session_id", sid, httponly=True, max_age=28800)
        return resp
    cur.execute("""
        SELECT ku.*, t.firma_adi FROM tenant_kullanicilar ku
        JOIN tenants t ON t.id=ku.tenant_id
        WHERE ku.username=%s AND ku.password_hash=%s AND t.durum='aktif'
    """, (username, h))
    k = cur.fetchone()
    conn.close()
    if k:
        sid = session_olustur(k["tenant_id"], username, k["rol"])
        resp = RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie("session_id", sid, httponly=True, max_age=28800)
        return resp
    return templates.TemplateResponse("giris.html", {"request": request, "hata": "Kullanıcı adı veya şifre yanlış!"})

@app.get("/cikis")
async def cikis(request: Request):
    sid = request.cookies.get("session_id")
    if sid and sid in SESSIONS:
        del SESSIONS[sid]
    resp = RedirectResponse("/giris", status_code=302)
    resp.delete_cookie("session_id")
    return resp

# SAYFALAR
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    s = session_al(request)
    if not s: return RedirectResponse("/giris")
    v = veri_al(s["tenant_id"])
    stoklar = v.get("stoklar", {})
    hareketler = v.get("hareketler", [])
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "session": s, "aktif": "dashboard",
        "toplam_stok_kg": round(sum(stoklar.values()), 1),
        "son_hareketler": hareketler[:5],
        "kritik_stok": [m for m, k in stoklar.items() if 0 < k < 50],
        "hazir_manti": v.get("hazir_manti_stok", 0),
        "stoklar": stoklar,
    })

@app.get("/patron", response_class=HTMLResponse)
async def patron(request: Request):
    s = session_al(request)
    if not s: return RedirectResponse("/giris")
    return templates.TemplateResponse("patron.html", {"request": request, "session": s, "aktif": "patron"})

@app.get("/uretim", response_class=HTMLResponse)
async def uretim(request: Request):
    s = session_al(request)
    if not s: return RedirectResponse("/giris")
    v = veri_al(s["tenant_id"])
    receteler = list(v.get("coklu_receteler", {}).keys())
    return templates.TemplateResponse("uretim.html", {
        "request": request, "session": s, "aktif": "uretim", "receteler": receteler
    })

@app.get("/uretim-hatti", response_class=HTMLResponse)
async def uretim_hatti(request: Request):
    s = session_al(request)
    if not s: return RedirectResponse("/giris")
    return templates.TemplateResponse("uretim_hatti.html", {"request": request, "session": s, "aktif": "uretim-hatti"})

@app.get("/depo", response_class=HTMLResponse)
async def depo(request: Request):
    s = session_al(request)
    if not s: return RedirectResponse("/giris")
    return templates.TemplateResponse("depo.html", {"request": request, "session": s, "aktif": "depo"})

@app.get("/stok-giris", response_class=HTMLResponse)
async def stok_giris_sayfa(request: Request):
    s = session_al(request)
    if not s: return RedirectResponse("/giris")
    v = veri_al(s["tenant_id"])
    malzemeler = sorted(v.get("stoklar", {}).keys())
    return templates.TemplateResponse("stok_giris.html", {
        "request": request, "session": s, "aktif": "stok-giris", "malzemeler": malzemeler
    })

@app.get("/hareketler", response_class=HTMLResponse)
async def hareketler_sayfa(request: Request):
    s = session_al(request)
    if not s: return RedirectResponse("/giris")
    return templates.TemplateResponse("hareketler.html", {"request": request, "session": s, "aktif": "hareketler"})

@app.get("/sicaklik", response_class=HTMLResponse)
async def sicaklik_sayfa(request: Request):
    s = session_al(request)
    if not s: return RedirectResponse("/giris")
    conn = db_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM sicaklik_sensorler WHERE tenant_id=%s AND aktif=true", (s["tenant_id"],))
        sensorler = list(cur.fetchall())
    except:
        sensorler = []
    conn.close()
    return templates.TemplateResponse("sicaklik.html", {
        "request": request, "session": s, "aktif": "sicaklik", "sensorler": sensorler
    })

@app.get("/ayarlar", response_class=HTMLResponse)
async def ayarlar_sayfa(request: Request):
    s = session_al(request)
    if not s: return RedirectResponse("/giris")
    return templates.TemplateResponse("ayarlar.html", {"request": request, "session": s, "aktif": "ayarlar"})

@app.get("/etiket", response_class=HTMLResponse)
async def etiket_sayfa(request: Request, parti: str = "", urun: str = "", miktar: str = "5 KG", tarih: str = ""):
    s = session_al(request)
    if not s: return RedirectResponse("/giris")
    if not tarih:
        tarih = bugun()
    try:
        p = tarih.split(".")
        uretim_dt = datetime(int(p[2]), int(p[1]), int(p[0]))
    except:
        uretim_dt = datetime.now()
    ay = uretim_dt.month + 6
    yil = uretim_dt.year
    if ay > 12:
        ay -= 12
        yil += 1
    skt = f"{uretim_dt.day:02d}.{ay:02d}.{yil}"
    m = _re.match(r"([0-9,.]+)\s*(.*)", str(miktar).strip())
    gramaj_sayi = m.group(1).rstrip("0").rstrip(".") if m else str(miktar)
    gramaj_birim = m.group(2).strip() if m and m.group(2).strip() else "KG"
    return templates.TemplateResponse("etiket.html", {
        "request": request,
        "skt": skt,
        "parti": parti or "URT-" + datetime.now().strftime("%y%m%d-%H%M"),
        "gramaj_sayi": gramaj_sayi,
        "gramaj_birim": gramaj_birim,
        "urun": urun,
    })

# API - STOK
@app.get("/api/stoklar")
async def api_stoklar(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    return JSONResponse(veri_al(s["tenant_id"]).get("stoklar", {}))

@app.get("/api/hareketler")
async def api_hareketler(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    return JSONResponse(veri_al(s["tenant_id"]).get("hareketler", []))

@app.get("/api/hazir-manti")
async def api_hazir_manti(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    return JSONResponse({"miktar": veri_al(s["tenant_id"]).get("hazir_manti_stok", 0)})

@app.get("/api/receteler")
async def api_receteler(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    return JSONResponse(veri_al(s["tenant_id"]).get("coklu_receteler", {}))

@app.post("/api/stok/giris")
async def api_stok_giris(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    data = await request.json()
    v = veri_al(s["tenant_id"])
    malzeme = data.get("malzeme", "").strip()
    miktar = float(data.get("miktar", 0))
    fiyat = float(data.get("fiyat", 0))
    fatura = data.get("fatura", "-") or "-"
    parti = data.get("parti", "").strip() or "PARTI-" + datetime.now().strftime("%y%m%d%H%M")
    tarih = data.get("tarih") or bugun()
    if not malzeme or miktar <= 0:
        return JSONResponse({"error": "Geçersiz veri"}, status_code=400)
    v.setdefault("stoklar", {})[malzeme] = v["stoklar"].get(malzeme, 0) + miktar
    v.setdefault("birim_fiyatlar", {})[malzeme] = fiyat
    v.setdefault("detayli_stok", []).insert(0, {"malzeme": malzeme, "miktar": miktar, "kalan": miktar, "fatura": fatura, "parti": parti, "tarih": tarih})
    v.setdefault("hareketler", []).insert(0, {"tarih": tarih, "malzeme": malzeme, "miktar": miktar, "fiyat": fiyat, "parti": parti, "fatura": fatura, "islem": "Giriş"})
    veri_kaydet(s["tenant_id"], v)
    return JSONResponse({"ok": True, "parti": parti})

@app.delete("/api/stok/hareket/{idx}")
async def api_hareket_sil(idx: int, request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    v = veri_al(s["tenant_id"])
    hareketler = v.get("hareketler", [])
    if idx < 0 or idx >= len(hareketler):
        return JSONResponse({"error": "Geçersiz index"}, status_code=400)
    h = hareketler[idx]
    if h.get("islem") == "Giriş":
        m = h.get("malzeme")
        if m in v.get("stoklar", {}):
            v["stoklar"][m] = max(0, v["stoklar"][m] - h.get("miktar", 0))
        v["detayli_stok"] = [d for d in v.get("detayli_stok", []) if not (d.get("parti") == h.get("parti") and d.get("malzeme") == m)]
    v["hareketler"].pop(idx)
    veri_kaydet(s["tenant_id"], v)
    return JSONResponse({"ok": True})

@app.put("/api/stok/hareket/{idx}")
async def api_hareket_duzenle(idx: int, request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    data = await request.json()
    v = veri_al(s["tenant_id"])
    hareketler = v.get("hareketler", [])
    if idx < 0 or idx >= len(hareketler):
        return JSONResponse({"error": "Geçersiz index"}, status_code=400)
    h = hareketler[idx]
    yeni_kg = float(data.get("miktar", h.get("miktar", 0)))
    fark = yeni_kg - float(h.get("miktar", 0))
    if h.get("islem") == "Giriş":
        m = h.get("malzeme")
        if m in v.get("stoklar", {}):
            v["stoklar"][m] = max(0, v["stoklar"][m] + fark)
        for d in v.get("detayli_stok", []):
            if d.get("parti") == h.get("parti") and d.get("malzeme") == m:
                d["miktar"] = yeni_kg
                d["kalan"] = max(0, d["kalan"] + fark)
    v["hareketler"][idx].update({"miktar": yeni_kg, "fiyat": float(data.get("fiyat", h.get("fiyat", 0))), "fatura": data.get("fatura", h.get("fatura", "")), "parti": data.get("parti", h.get("parti", ""))})
    veri_kaydet(s["tenant_id"], v)
    return JSONResponse({"ok": True})

# API - ÜRETİM & SATIŞ
@app.post("/api/uretim")
async def api_uretim(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    data = await request.json()
    v = veri_al(s["tenant_id"])
    recete_adi = data.get("recete")
    kg = float(data.get("miktar", 0))
    tarih = data.get("tarih") or bugun()
    recete = v.get("coklu_receteler", {}).get(recete_adi)
    if not recete: return JSONResponse({"error": "Reçete bulunamadı"}, status_code=400)
    oranlar = recete.get("oranlar", {})
    yetersiz = [m for m, oran in oranlar.items() if oran > 0 and v.get("stoklar", {}).get(m, 0) < kg * oran - 0.001]
    if yetersiz: return JSONResponse({"error": f"Yetersiz stok: {', '.join(yetersiz)}"}, status_code=400)
    parti = "URT-" + datetime.now().strftime("%y%m%d-%H%M")
    for m, oran in oranlar.items():
        if oran > 0:
            v["stoklar"][m] = max(0, v["stoklar"].get(m, 0) - kg * oran)
    v["hazir_manti_stok"] = v.get("hazir_manti_stok", 0) + kg
    v.setdefault("hareketler", []).insert(0, {"tarih": tarih, "malzeme": recete_adi, "miktar": kg, "fiyat": 0, "parti": parti, "fatura": "-", "islem": "Üretim"})
    veri_kaydet(s["tenant_id"], v)
    return JSONResponse({"ok": True, "parti": parti})

@app.post("/api/satis")
async def api_satis(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    data = await request.json()
    v = veri_al(s["tenant_id"])
    kg = float(data.get("miktar", 0))
    fiyat = float(data.get("fiyat", 0))
    hazir = v.get("hazir_manti_stok", 0)
    if kg <= 0: return JSONResponse({"error": "Geçersiz miktar"}, status_code=400)
    if kg > hazir: return JSONResponse({"error": f"Yetersiz stok! Mevcut: {hazir:.1f} KG"}, status_code=400)
    v["hazir_manti_stok"] = hazir - kg
    v.setdefault("hareketler", []).insert(0, {"tarih": bugun(), "malzeme": "Hazır Mantı", "miktar": kg, "fiyat": fiyat, "parti": "-", "fatura": "-", "islem": "Satış"})
    veri_kaydet(s["tenant_id"], v)
    return JSONResponse({"ok": True})

# API - REÇETE
@app.post("/api/recete")
async def api_recete_kaydet(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    data = await request.json()
    v = veri_al(s["tenant_id"])
    adi = data.get("adi", "").strip()
    if not adi: return JSONResponse({"error": "Reçete adı boş"}, status_code=400)
    v.setdefault("coklu_receteler", {})[adi] = {"oranlar": data.get("oranlar", {}), "aciklama": data.get("aciklama", "")}
    veri_kaydet(s["tenant_id"], v)
    return JSONResponse({"ok": True})

@app.delete("/api/recete/{adi}")
async def api_recete_sil(adi: str, request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    from urllib.parse import unquote
    adi = unquote(adi)
    v = veri_al(s["tenant_id"])
    v.get("coklu_receteler", {}).pop(adi, None)
    veri_kaydet(s["tenant_id"], v)
    return JSONResponse({"ok": True})

# API - SICAKLIK
@app.get("/api/sicaklik/sensorler")
async def api_sensorler(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    conn = db_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT ss.*,
               (SELECT sicaklik FROM sicaklik_olcumler WHERE tenant_id=ss.tenant_id AND sensor_id=ss.sensor_id ORDER BY id DESC LIMIT 1) as son_olcum,
               (SELECT kayit_zamani FROM sicaklik_olcumler WHERE tenant_id=ss.tenant_id AND sensor_id=ss.sensor_id ORDER BY id DESC LIMIT 1) as son_zaman
            FROM sicaklik_sensorler ss WHERE ss.tenant_id=%s AND ss.aktif=true
        """, (s["tenant_id"],))
        sensorler = [dict(r) for r in cur.fetchall()]
    except:
        sensorler = []
    conn.close()
    for r in sensorler:
        if r.get("son_zaman"): r["son_zaman"] = str(r["son_zaman"])[:16]
    return JSONResponse(sensorler)

@app.get("/api/sicaklik/gecmis/{sensor_id}")
async def api_sicaklik_gecmis(sensor_id: str, request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    conn = db_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT sicaklik, kayit_zamani FROM sicaklik_olcumler WHERE tenant_id=%s AND sensor_id=%s ORDER BY id DESC LIMIT 100", (s["tenant_id"], sensor_id))
        rows = [dict(r) for r in cur.fetchall()]
    except:
        rows = []
    conn.close()
    for r in rows:
        if r.get("kayit_zamani"): r["kayit_zamani"] = str(r["kayit_zamani"])[:16]
    return JSONResponse(rows)

@app.post("/api/sicaklik/sensor-ekle")
async def api_sensor_ekle(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    data = await request.json()
    api_key = "SK-" + secrets.token_hex(16)
    conn = db_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO sicaklik_sensorler (tenant_id, sensor_id, sensor_adi, min_alarm, max_alarm, aktif, api_key)
            VALUES (%s,%s,%s,%s,%s,true,%s)
            ON CONFLICT (tenant_id, sensor_id) DO UPDATE SET sensor_adi=%s, min_alarm=%s, max_alarm=%s
        """, (s["tenant_id"], data["sensor_id"], data["sensor_adi"], data.get("min_alarm",-25), data.get("max_alarm",5), api_key, data["sensor_adi"], data.get("min_alarm",-25), data.get("max_alarm",5)))
        conn.commit()
        conn.close()
        return JSONResponse({"ok": True, "api_key": api_key})
    except Exception as e:
        conn.close()
        return JSONResponse({"error": str(e)}, status_code=400)

# API - AYARLAR
@app.post("/api/sifre-degistir")
async def api_sifre(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    data = await request.json()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT password_hash FROM tenant_kullanicilar WHERE tenant_id=%s AND username=%s", (s["tenant_id"], s["username"]))
    row = cur.fetchone()
    if not row or row["password_hash"] != hash_sifre(data.get("eski_sifre", "")):
        conn.close()
        return JSONResponse({"error": "Mevcut şifre yanlış!"}, status_code=400)
    cur.execute("UPDATE tenant_kullanicilar SET password_hash=%s WHERE tenant_id=%s AND username=%s", (hash_sifre(data["yeni_sifre"]), s["tenant_id"], s["username"]))
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True})

@app.get("/api/yedek")
async def api_yedek(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    return JSONResponse(veri_al(s["tenant_id"]))

@app.post("/api/yedek-yukle")
async def api_yedek_yukle(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    data = await request.json()
    veri_kaydet(s["tenant_id"], data)
    return JSONResponse({"ok": True})

# API - MAKİNELER
def makine_tablosu_olustur():
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS uretim_makineleri (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL,
            adi TEXT NOT NULL,
            ikon TEXT DEFAULT '⚙️',
            grup TEXT DEFAULT '',
            durum TEXT DEFAULT 'aktif',
            x INTEGER DEFAULT 40,
            y INTEGER DEFAULT 40,
            guncelleme TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()

@app.get("/api/makineler")
async def api_makineler_listele(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    try:
        makine_tablosu_olustur()
        conn = db_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM uretim_makineleri WHERE tenant_id=%s ORDER BY id", (s["tenant_id"],))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return JSONResponse(rows)
    except:
        return JSONResponse([])

@app.post("/api/makineler")
async def api_makine_ekle(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    data = await request.json()
    makine_tablosu_olustur()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO uretim_makineleri (tenant_id, adi, ikon, grup, durum, x, y, guncelleme) VALUES (%s,%s,%s,%s,'aktif',%s,%s,%s)",
        (s["tenant_id"], data["adi"], data.get("ikon","⚙️"), data.get("grup",""), data.get("x",40), data.get("y",40), bugun()))
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True})

@app.put("/api/makineler/{mid}")
async def api_makine_guncelle(mid: int, request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    data = await request.json()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("UPDATE uretim_makineleri SET durum=%s, guncelleme=%s WHERE id=%s AND tenant_id=%s",
        (data.get("durum","aktif"), datetime.now().strftime("%d.%m.%Y %H:%M"), mid, s["tenant_id"]))
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True})

@app.delete("/api/makineler/{mid}")
async def api_makine_sil(mid: int, request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM uretim_makineleri WHERE id=%s AND tenant_id=%s", (mid, s["tenant_id"]))
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True})



# ══════════════════════════════════════════
#  API — ÜRÜN ETİKETLERİ
# ══════════════════════════════════════════
def etiket_tablosu_olustur():
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS urun_etiketleri (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL,
            urun_adi TEXT NOT NULL,
            etiket_html TEXT NOT NULL,
            olusturma TIMESTAMP DEFAULT NOW(),
            UNIQUE(tenant_id, urun_adi)
        )
    """)
    conn.commit()
    conn.close()

@app.post("/api/etiket/kaydet")
async def api_etiket_kaydet(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    data = await request.json()
    urun_adi = data.get("urun_adi", "").strip()
    etiket_html = data.get("etiket_html", "").strip()
    if not urun_adi or not etiket_html:
        return JSONResponse({"error": "Ürün adı ve etiket zorunlu"}, status_code=400)
    etiket_tablosu_olustur()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO urun_etiketleri (tenant_id, urun_adi, etiket_html)
        VALUES (%s, %s, %s)
        ON CONFLICT (tenant_id, urun_adi) DO UPDATE SET etiket_html=%s, olusturma=NOW()
    """, (s["tenant_id"], urun_adi, etiket_html, etiket_html))
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True})

@app.get("/api/etiket/listele")
async def api_etiket_listele(request: Request):
    s = session_al(request)
    if not s: return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    etiket_tablosu_olustur()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT urun_adi FROM urun_etiketleri WHERE tenant_id=%s ORDER BY urun_adi", (s["tenant_id"],))
    rows = [r["urun_adi"] for r in cur.fetchall()]
    conn.close()
    return JSONResponse(rows)

@app.get("/etiket/yazdir/{urun_adi}")
async def etiket_yazdir(urun_adi: str, request: Request, parti: str = "", tarih: str = "", gramaj: str = "5 KG"):
    s = session_al(request)
    if not s: return RedirectResponse("/giris")
    from urllib.parse import unquote
    urun_adi = unquote(urun_adi)
    etiket_tablosu_olustur()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT etiket_html FROM urun_etiketleri WHERE tenant_id=%s AND urun_adi=%s", (s["tenant_id"], urun_adi))
    row = cur.fetchone()
    conn.close()
    if not row:
        return HTMLResponse("<h3>Bu ürün için etiket tanımlanmamış.</h3>")
    
    # Parti ve SKT hesapla
    if not tarih: tarih = bugun()
    try:
        p = tarih.split(".")
        uretim_dt = datetime(int(p[2]), int(p[1]), int(p[0]))
    except:
        uretim_dt = datetime.now()
    ay = uretim_dt.month + 6
    yil = uretim_dt.year
    if ay > 12: ay -= 12; yil += 1
    skt = f"{uretim_dt.day:02d}.{ay:02d}.{yil}"
    if not parti: parti = "URT-" + datetime.now().strftime("%y%m%d-%H%M")
    
    # HTML içinde parti ve SKT değerlerini değiştir
    html = row["etiket_html"]
    html = html.replace("15.09.2026", skt)
    html = html.replace("URT-260316-0611", parti)
    # Gramaj değiştir
    import re as _re2
    html = _re2.sub(r'<div class="kgsayi"[^>]*>\d+</div>\s*<div class="kgbirim"[^>]*>\w+</div>', lambda m: m.group(0), html)
    m2 = _re.match(r"([0-9,.]+)\s*(.*)", gramaj.strip())
    if m2:
        sayi = m2.group(1)
        birim = m2.group(2).strip() or "KG"
        html = _re.sub(r'(<div class="kgsayi"[^>]*>)[^<]*(</div>)', f'\\g<1>{sayi}\\g<2>', html)
        html = _re.sub(r'(<div class="kgbirim"[^>]*>)[^<]*(</div>)', f'\\g<1>{birim}\\g<2>', html)
    
    return HTMLResponse(html)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
