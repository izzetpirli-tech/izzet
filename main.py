import os
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Response, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="Elfiga ERP")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ══════════════════════════════════════════
#  VERİTABANI
# ══════════════════════════════════════════
def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()

def db_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def hash_sifre(sifre: str) -> str:
    return hashlib.sha256(sifre.encode()).hexdigest()

# ══════════════════════════════════════════
#  SESSION (Cookie tabanlı basit auth)
# ══════════════════════════════════════════
SESSIONS = {}  # session_id -> {tenant_id, username, rol}

def session_olustur(tenant_id: int, username: str, rol: str) -> str:
    import secrets
    sid = secrets.token_hex(32)
    SESSIONS[sid] = {
        "tenant_id": tenant_id,
        "username": username,
        "rol": rol,
        "zaman": datetime.now()
    }
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

def giris_gerekli(request: Request):
    s = session_al(request)
    if not s:
        raise HTTPException(status_code=302, headers={"Location": "/giris"})
    return s

# ══════════════════════════════════════════
#  GİRİŞ
# ══════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def anasayfa(request: Request):
    s = session_al(request)
    if s:
        return RedirectResponse("/dashboard")
    return RedirectResponse("/giris")

@app.get("/giris", response_class=HTMLResponse)
async def giris_sayfasi(request: Request):
    s = session_al(request)
    if s:
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("giris.html", {"request": request, "hata": None})

@app.post("/giris", response_class=HTMLResponse)
async def giris_yap(request: Request, username: str = Form(...), sifre: str = Form(...)):
    conn = db_conn()
    cur = conn.cursor()
    
    # Superadmin kontrolü
    cur.execute("SELECT * FROM superadminler WHERE username=%s AND password_hash=%s", 
                (username, hash_sifre(sifre)))
    sadmin = cur.fetchone()
    if sadmin:
        sid = session_olustur(0, username, "superadmin")
        resp = RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie("session_id", sid, httponly=True, max_age=28800)
        conn.close()
        return resp
    
    # Normal kullanıcı
    cur.execute("""
        SELECT ku.*, t.firma_adi FROM tenant_kullanicilar ku
        JOIN tenants t ON t.id = ku.tenant_id
        WHERE ku.username=%s AND ku.password_hash=%s AND t.durum='aktif'
    """, (username, hash_sifre(sifre)))
    kullanici = cur.fetchone()
    
    if kullanici:
        sid = session_olustur(kullanici["tenant_id"], username, kullanici["rol"])
        resp = RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie("session_id", sid, httponly=True, max_age=28800)
        conn.close()
        return resp
    
    conn.close()
    return templates.TemplateResponse("giris.html", {"request": request, "hata": "Kullanıcı adı veya şifre yanlış!"})

@app.get("/cikis")
async def cikis(request: Request):
    sid = request.cookies.get("session_id")
    if sid and sid in SESSIONS:
        del SESSIONS[sid]
    resp = RedirectResponse("/giris", status_code=302)
    resp.delete_cookie("session_id")
    return resp

# ══════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    s = session_al(request)
    if not s:
        return RedirectResponse("/giris")
    
    conn = db_conn()
    cur = conn.cursor()
    
    # Tenant verilerini al
    tenant_id = s["tenant_id"]
    cur.execute("SELECT value FROM tenant_veriler WHERE tenant_id=%s AND key='veriler'", (tenant_id,))
    row = cur.fetchone()
    v = row["value"] if row else {}
    
    stoklar = v.get("stoklar", {})
    hareketler = v.get("hareketler", [])
    
    # KPI hesapla
    toplam_stok_kg = sum(stoklar.values())
    son_hareketler = hareketler[:5]
    kritik_stok = [m for m, k in stoklar.items() if 0 < k < 50]
    hazir_manti = v.get("hazir_manti_stok", 0)
    
    conn.close()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "session": s,
        "toplam_stok_kg": round(toplam_stok_kg, 1),
        "son_hareketler": son_hareketler,
        "kritik_stok": kritik_stok,
        "hazir_manti": hazir_manti,
        "stoklar": stoklar,
    })

# ══════════════════════════════════════════
#  API - STOK
# ══════════════════════════════════════════
@app.get("/api/stoklar")
async def stoklar_listele(request: Request):
    s = session_al(request)
    if not s:
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM tenant_veriler WHERE tenant_id=%s AND key='veriler'", (s["tenant_id"],))
    row = cur.fetchone()
    conn.close()
    
    v = row["value"] if row else {}
    return JSONResponse(v.get("stoklar", {}))

@app.get("/api/hareketler")
async def hareketler_listele(request: Request):
    s = session_al(request)
    if not s:
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM tenant_veriler WHERE tenant_id=%s AND key='veriler'", (s["tenant_id"],))
    row = cur.fetchone()
    conn.close()
    
    v = row["value"] if row else {}
    return JSONResponse(v.get("hareketler", []))

def tenant_veri_kaydet(tenant_id, v):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO tenant_veriler (tenant_id, key, value, updated_at)
        VALUES (%s, 'veriler', %s, NOW())
        ON CONFLICT (tenant_id, key) DO UPDATE SET value=%s, updated_at=NOW()
    """, (tenant_id, json.dumps(v, ensure_ascii=False, default=str),
          json.dumps(v, ensure_ascii=False, default=str)))
    conn.commit()
    conn.close()

@app.post("/api/stok/giris")
async def stok_giris(request: Request):
    s = session_al(request)
    if not s:
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    
    data = await request.json()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM tenant_veriler WHERE tenant_id=%s AND key='veriler'", (s["tenant_id"],))
    row = cur.fetchone()
    v = dict(row["value"]) if row else {"stoklar": {}, "hareketler": [], "detayli_stok": []}
    conn.close()
    
    malzeme = data["malzeme"]
    miktar = float(data["miktar"])
    fiyat = float(data.get("fiyat", 0))
    fatura = data.get("fatura", "-")
    parti = data.get("parti") or "PARTI-" + datetime.now().strftime("%y%m%d%H%M")
    tarih = data.get("tarih", datetime.now().strftime("%d.%m.%Y"))
    
    if malzeme not in v.get("stoklar", {}):
        v.setdefault("stoklar", {})[malzeme] = 0.0
    v["stoklar"][malzeme] = v["stoklar"].get(malzeme, 0) + miktar
    
    v.setdefault("detayli_stok", []).insert(0, {
        "malzeme": malzeme, "miktar": miktar, "kalan": miktar,
        "fatura": fatura, "parti": parti, "tarih": tarih
    })
    v.setdefault("hareketler", []).insert(0, {
        "tarih": tarih, "malzeme": malzeme, "miktar": miktar,
        "fiyat": fiyat, "parti": parti, "fatura": fatura, "islem": "Giriş"
    })
    
    tenant_veri_kaydet(s["tenant_id"], v)
    return JSONResponse({"ok": True, "parti": parti})

@app.delete("/api/stok/hareket/{index}")
async def hareket_sil(index: int, request: Request):
    s = session_al(request)
    if not s:
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM tenant_veriler WHERE tenant_id=%s AND key='veriler'", (s["tenant_id"],))
    row = cur.fetchone()
    v = dict(row["value"]) if row else {}
    conn.close()
    
    hareketler = v.get("hareketler", [])
    if index < 0 or index >= len(hareketler):
        return JSONResponse({"error": "Geçersiz index"}, status_code=400)
    
    h = hareketler[index]
    if h.get("islem") == "Giriş":
        malzeme = h.get("malzeme")
        miktar = h.get("miktar", 0)
        if malzeme in v.get("stoklar", {}):
            v["stoklar"][malzeme] = max(0, v["stoklar"][malzeme] - miktar)
        v["detayli_stok"] = [
            d for d in v.get("detayli_stok", [])
            if not (d.get("parti") == h.get("parti") and d.get("malzeme") == malzeme)
        ]
    
    v["hareketler"].pop(index)
    tenant_veri_kaydet(s["tenant_id"], v)
    return JSONResponse({"ok": True})

@app.put("/api/stok/hareket/{index}")
async def hareket_duzenle(index: int, request: Request):
    s = session_al(request)
    if not s:
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    
    data = await request.json()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM tenant_veriler WHERE tenant_id=%s AND key='veriler'", (s["tenant_id"],))
    row = cur.fetchone()
    v = dict(row["value"]) if row else {}
    conn.close()
    
    hareketler = v.get("hareketler", [])
    if index < 0 or index >= len(hareketler):
        return JSONResponse({"error": "Geçersiz index"}, status_code=400)
    
    h = hareketler[index]
    yeni_miktar = float(data.get("miktar", h.get("miktar", 0)))
    eski_miktar = float(h.get("miktar", 0))
    fark = yeni_miktar - eski_miktar
    
    if h.get("islem") == "Giriş":
        malzeme = h.get("malzeme")
        if malzeme in v.get("stoklar", {}):
            v["stoklar"][malzeme] = max(0, v["stoklar"][malzeme] + fark)
        for d in v.get("detayli_stok", []):
            if d.get("parti") == h.get("parti") and d.get("malzeme") == malzeme:
                d["miktar"] = yeni_miktar
                d["kalan"] = max(0, d["kalan"] + fark)
    
    v["hareketler"][index].update({
        "miktar": yeni_miktar,
        "fiyat": float(data.get("fiyat", h.get("fiyat", 0))),
        "fatura": data.get("fatura", h.get("fatura", "")),
        "parti": data.get("parti", h.get("parti", "")),
    })
    
    tenant_veri_kaydet(s["tenant_id"], v)
    return JSONResponse({"ok": True})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
