import streamlit as st
import psycopg2
import psycopg2.extras
import json
import os
import hashlib
from datetime import datetime, timedelta
import pandas as pd

st.set_page_config(
    page_title="SaaS Admin Paneli",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0F0F13; color: white; }
    section[data-testid="stSidebar"] { background-color: #1A1A24; }
    
    .admin-card {
        background: #1E1E2E;
        border-radius: 14px;
        padding: 20px 24px;
        border: 1px solid #2A2A3E;
        margin-bottom: 12px;
    }
    .admin-card.green { border-left: 4px solid #34C759; }
    .admin-card.blue  { border-left: 4px solid #007AFF; }
    .admin-card.red   { border-left: 4px solid #FF3B30; }
    .admin-card.orange{ border-left: 4px solid #FF9500; }

    .kpi-label { font-size: 11px; color: #8E8E93; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }
    .kpi-value { font-size: 32px; font-weight: 800; color: white; margin-top: 4px; }

    .tenant-row {
        background: #1E1E2E;
        border: 1px solid #2A2A3E;
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .badge-aktif   { background:#1a3a2a; color:#34C759; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; }
    .badge-pasif   { background:#3a1a1a; color:#FF3B30; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; }
    .badge-deneme  { background:#3a2a1a; color:#FF9500; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; }

    div[data-testid="metric-container"] {
        background: #1E1E2E;
        border-radius: 12px;
        padding: 16px;
        border: 1px solid #2A2A3E;
    }
    div[data-testid="metric-container"] label { color: #8E8E93 !important; }
    div[data-testid="metric-container"] div[data-testid="metric-value"] { color: white !important; }

    .stButton > button { border-radius: 8px !important; font-weight: 600 !important; }
    .stTextInput > div > input, .stSelectbox > div { background: #2A2A3E !important; color: white !important; border: 1px solid #3A3A4E !important; }
    h1,h2,h3,h4 { color: white !important; }
    p, label, .stMarkdown { color: #C0C0C0; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# VERİTABANI
# ─────────────────────────────────────────────
@st.cache_resource
def get_db():
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    return conn

def init_admin_db():
    conn = get_db()
    cur = conn.cursor()

    # Tenant (müşteri) tablosu
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id SERIAL PRIMARY KEY,
            firma_adi TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            yetkili_adi TEXT,
            email TEXT,
            telefon TEXT,
            plan TEXT DEFAULT 'deneme',
            durum TEXT DEFAULT 'aktif',
            baslangic_tarihi DATE DEFAULT CURRENT_DATE,
            bitis_tarihi DATE DEFAULT (CURRENT_DATE + INTERVAL '30 days'),
            aylik_ucret NUMERIC DEFAULT 0,
            notlar TEXT DEFAULT '',
            olusturma_tarihi TIMESTAMP DEFAULT NOW()
        )
    """)

    # Her tenant için veri tablosu (schema: tenant_<slug>)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tenant_veriler (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value JSONB NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(tenant_id, key)
        )
    """)

    # Tenant kullanıcıları
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tenant_kullanicilar (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            rol TEXT DEFAULT 'user',
            olusturma_tarihi TIMESTAMP DEFAULT NOW(),
            UNIQUE(tenant_id, username)
        )
    """)

    # Süperadmin tablosu
    cur.execute("""
        CREATE TABLE IF NOT EXISTS superadminler (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            olusturma_tarihi TIMESTAMP DEFAULT NOW()
        )
    """)

    # Varsayılan süperadmin oluştur
    admin_pass = os.environ.get("SUPERADMIN_PASSWORD", "superadmin2024")
    cur.execute("SELECT COUNT(*) FROM superadminler WHERE username = 'superadmin'")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO superadminler (username, password_hash) VALUES (%s, %s)",
            ("superadmin", hashlib.sha256(admin_pass.encode()).hexdigest())
        )

    cur.close()

def hash_pw(p):
    return hashlib.sha256(p.encode()).hexdigest()

# ─────────────────────────────────────────────
# VERİ FONKSİYONLARI
# ─────────────────────────────────────────────
def tum_tenantlari_getir():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM tenants ORDER BY olusturma_tarihi DESC")
    rows = cur.fetchall()
    cur.close()
    return [dict(r) for r in rows]

def tenant_getir(tenant_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM tenants WHERE id = %s", (tenant_id,))
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None

def tenant_olustur(firma_adi, slug, yetkili, email, telefon, plan, ucret, gun):
    conn = get_db()
    cur = conn.cursor()
    bitis = datetime.now().date() + timedelta(days=gun)
    cur.execute("""
        INSERT INTO tenants (firma_adi, slug, yetkili_adi, email, telefon, plan, aylik_ucret, bitis_tarihi)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
    """, (firma_adi, slug, yetkili, email, telefon, plan, ucret, bitis))
    tenant_id = cur.fetchone()[0]
    cur.close()
    return tenant_id

def tenant_admin_olustur(tenant_id, username, password):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO tenant_kullanicilar (tenant_id, username, password_hash, rol)
        VALUES (%s, %s, %s, 'admin')
        ON CONFLICT (tenant_id, username) DO UPDATE SET password_hash = %s
    """, (tenant_id, username, hash_pw(password), hash_pw(password)))
    cur.close()

def tenant_varsayilan_veri_yukle(tenant_id):
    """Yeni müşteriye boş başlangıç verisi yükle"""
    varsayilan = {
        "stoklar": {"Un": 0.0, "Soğan": 0.0, "Kıyma": 0.0, "Yağ": 0.0,
                    "Soya": 0.0, "İrmik": 0.0, "Baharat": 0.0, "Tuz": 0.0},
        "detayli_stok": [],
        "hazir_manti_stok": 0.0,
        "hareketler": [],
        "birim_fiyatlar": {"Un": 0.0, "Soğan": 0.0, "Kıyma": 0.0, "Yağ": 0.0,
                           "Soya": 0.0, "İrmik": 0.0, "Baharat": 0.0, "Tuz": 0.0},
        "coklu_receteler": {
            "Standart Soyalı": {
                "oranlar": {"Un": 0.6475, "Soğan": 0.100, "Kıyma": 0.046,
                            "Yağ": 0.046, "Soya": 0.046, "İrmik": 0.046,
                            "Baharat": 0.015, "Tuz": 0.003},
                "etiket_tipi": "Soyalı"
            }
        },
        "aktif_recete_adi": "Standart Soyalı"
    }
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO tenant_veriler (tenant_id, key, value)
        VALUES (%s, 'ana_veri', %s)
        ON CONFLICT (tenant_id, key) DO NOTHING
    """, (tenant_id, json.dumps(varsayilan, ensure_ascii=False)))
    cur.close()

def tenant_guncelle(tenant_id, alan, deger):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"UPDATE tenants SET {alan} = %s WHERE id = %s", (deger, tenant_id))
    cur.close()

def tenant_sil(tenant_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
    cur.close()

def tenant_istatistik(tenant_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT value FROM tenant_veriler WHERE tenant_id = %s AND key = 'ana_veri'", (tenant_id,))
    row = cur.fetchone()
    cur.close()
    if not row:
        return {"hareket": 0, "uretim": 0, "stok_deger": 0}
    v = row['value']
    if isinstance(v, str):
        v = json.loads(v)
    uretimler = [h for h in v.get("hareketler", []) if h.get("islem") == "Üretim"]
    stok_deger = sum(
        v["stoklar"].get(m, 0) * v["birim_fiyatlar"].get(m, 0)
        for m in v.get("stoklar", {})
    )
    return {
        "hareket": len(v.get("hareketler", [])),
        "uretim": len(uretimler),
        "stok_deger": round(stok_deger, 2)
    }

def superadmin_dogrula(username, password):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM superadminler WHERE username = %s AND password_hash = %s",
                (username, hash_pw(password)))
    row = cur.fetchone()
    cur.close()
    return row is not None

# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────
def login_sayfasi():
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("""
        <div style='text-align:center;padding:50px 0 30px 0'>
            <div style='font-size:56px'>⚙️</div>
            <h1 style='color:white;font-size:24px;margin:10px 0 4px 0'>SaaS Admin Paneli</h1>
            <p style='color:#8E8E93;font-size:13px'>Yetkisiz erişim yasaktır</p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("admin_login"):
            username = st.text_input("Kullanıcı Adı", placeholder="superadmin")
            password = st.text_input("Parola", type="password")
            if st.form_submit_button("Giriş Yap", use_container_width=True, type="primary"):
                if superadmin_dogrula(username, password):
                    st.session_state.admin_logged_in = True
                    st.session_state.admin_user = username
                    st.rerun()
                else:
                    st.error("❌ Hatalı giriş!")

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
def admin_sidebar():
    with st.sidebar:
        st.markdown("""
        <div style='text-align:center;padding:20px 0 10px 0'>
            <div style='font-size:36px'>⚙️</div>
            <h3 style='color:white;margin:6px 0 2px 0;font-size:15px'>SaaS Admin</h3>
            <p style='color:#8E8E93;font-size:11px;margin:0'>Süperadmin Paneli</p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("---")

        menu = st.radio("Menü", [
            "📊 Genel Bakış",
            "🏢 Müşteriler",
            "➕ Yeni Müşteri",
            "🔑 Parola Sıfırla",
            "⚙️ Sistem"
        ], label_visibility="collapsed")

        st.markdown("---")
        st.markdown(f"<p style='color:#8E8E93;font-size:12px'>👤 {st.session_state.get('admin_user','')}</p>", unsafe_allow_html=True)
        if st.button("🚪 Çıkış", use_container_width=True):
            st.session_state.admin_logged_in = False
            st.rerun()
    return menu

# ─────────────────────────────────────────────
# GENEL BAKIŞ
# ─────────────────────────────────────────────
def genel_bakis():
    st.markdown("## 📊 Genel Bakış")
    tenantlar = tum_tenantlari_getir()

    aktif = sum(1 for t in tenantlar if t["durum"] == "aktif")
    pasif = sum(1 for t in tenantlar if t["durum"] == "pasif")
    deneme = sum(1 for t in tenantlar if t["plan"] == "deneme")
    aylik_gelir = sum(float(t["aylik_ucret"] or 0) for t in tenantlar if t["durum"] == "aktif")

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric("🏢 Toplam Müşteri", len(tenantlar))
    with k2:
        st.metric("✅ Aktif", aktif)
    with k3:
        st.metric("🆓 Deneme", deneme)
    with k4:
        st.metric("💰 Aylık Gelir", f"{aylik_gelir:,.0f} TL")

    st.markdown("---")

    # Yakında biten abonelikler
    bugun = datetime.now().date()
    yakin_biten = []
    for t in tenantlar:
        if t["bitis_tarihi"] and t["durum"] == "aktif":
            kalan = (t["bitis_tarihi"] - bugun).days
            if kalan <= 10:
                yakin_biten.append({
                    "Firma": t["firma_adi"],
                    "Bitiş": str(t["bitis_tarihi"]),
                    "Kalan Gün": kalan,
                    "Plan": t["plan"]
                })

    if yakin_biten:
        st.markdown("### ⚠️ Yakında Biten Abonelikler")
        df = pd.DataFrame(yakin_biten)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.markdown("---")

    # Son eklenen müşteriler
    st.markdown("### 🕐 Son Eklenen Müşteriler")
    if tenantlar:
        df_son = pd.DataFrame([{
            "Firma": t["firma_adi"],
            "Plan": t["plan"],
            "Durum": "✅ Aktif" if t["durum"] == "aktif" else "🔴 Pasif",
            "Aylık (TL)": t["aylik_ucret"],
            "Bitiş": str(t["bitis_tarihi"]),
            "Kayıt": str(t["olusturma_tarihi"])[:10]
        } for t in tenantlar[:10]])
        st.dataframe(df_son, use_container_width=True, hide_index=True)
    else:
        st.info("Henüz müşteri yok.")

# ─────────────────────────────────────────────
# MÜŞTERİLER
# ─────────────────────────────────────────────
def musteriler_sayfasi():
    st.markdown("## 🏢 Müşteri Yönetimi")

    tenantlar = tum_tenantlari_getir()
    if not tenantlar:
        st.info("Henüz müşteri yok. 'Yeni Müşteri' ekranından ekleyin.")
        return

    # Filtrele
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        filtre_durum = st.selectbox("Durum Filtresi", ["Tümü", "aktif", "pasif", "deneme"])
    with col_f2:
        ara = st.text_input("Firma Ara", "")

    liste = tenantlar
    if filtre_durum != "Tümü":
        liste = [t for t in liste if t["durum"] == filtre_durum or t["plan"] == filtre_durum]
    if ara:
        liste = [t for t in liste if ara.lower() in t["firma_adi"].lower()]

    st.markdown(f"**{len(liste)} müşteri**")
    st.markdown("---")

    for t in liste:
        bugun = datetime.now().date()
        kalan_gun = (t["bitis_tarihi"] - bugun).days if t["bitis_tarihi"] else 0

        durum_renk = {"aktif": "#34C759", "pasif": "#FF3B30"}.get(t["durum"], "#FF9500")
        plan_emoji = {"deneme": "🆓", "temel": "🥈", "pro": "🥇", "kurumsal": "💎"}.get(t["plan"], "📦")

        with st.expander(f"{plan_emoji} **{t['firma_adi']}** — {t['slug']} | {t['durum'].upper()} | {kalan_gun} gün kaldı"):
            col1, col2, col3 = st.columns(3)

            with col1:
                st.markdown("**📋 Firma Bilgileri**")
                st.write(f"👤 Yetkili: {t['yetkili_adi'] or '-'}")
                st.write(f"📧 Email: {t['email'] or '-'}")
                st.write(f"📞 Telefon: {t['telefon'] or '-'}")
                st.write(f"📦 Plan: {t['plan']}")
                st.write(f"💰 Aylık: {t['aylik_ucret']} TL")

            with col2:
                st.markdown("**📊 Kullanım İstatistikleri**")
                try:
                    ist = tenant_istatistik(t["id"])
                    st.write(f"📝 Toplam Hareket: {ist['hareket']}")
                    st.write(f"🏭 Üretim Sayısı: {ist['uretim']}")
                    st.write(f"💵 Stok Değeri: {ist['stok_deger']:,.2f} TL")
                except:
                    st.write("İstatistik yüklenemedi")

            with col3:
                st.markdown("**⚙️ İşlemler**")

                # Durum değiştir
                yeni_durum = st.selectbox("Durum", ["aktif", "pasif"],
                                          index=0 if t["durum"] == "aktif" else 1,
                                          key=f"durum_{t['id']}")
                if st.button("Durumu Güncelle", key=f"durum_btn_{t['id']}"):
                    tenant_guncelle(t["id"], "durum", yeni_durum)
                    st.success("✅ Güncellendi!")
                    st.rerun()

                # Abonelik uzat
                uzat_gun = st.number_input("Gün Uzat", min_value=1, value=30, key=f"uzat_{t['id']}")
                if st.button("📅 Aboneliği Uzat", key=f"uzat_btn_{t['id']}"):
                    mevcut_bitis = t["bitis_tarihi"]
                    yeni_bitis = mevcut_bitis + timedelta(days=int(uzat_gun))
                    tenant_guncelle(t["id"], "bitis_tarihi", str(yeni_bitis))
                    st.success(f"✅ {yeni_bitis} tarihine uzatıldı!")
                    st.rerun()

                # Sil
                if st.button("🗑️ Müşteriyi Sil", key=f"sil_{t['id']}", type="secondary"):
                    tenant_sil(t["id"])
                    st.success("✅ Silindi!")
                    st.rerun()

# ─────────────────────────────────────────────
# YENİ MÜŞTERİ
# ─────────────────────────────────────────────
def yeni_musteri_sayfasi():
    st.markdown("## ➕ Yeni Müşteri Ekle")

    with st.form("yeni_tenant_form"):
        st.markdown("#### 🏢 Firma Bilgileri")
        col1, col2 = st.columns(2)
        with col1:
            firma_adi = st.text_input("Firma Adı *", placeholder="ABC Manti Fabrikası")
            yetkili = st.text_input("Yetkili Adı", placeholder="Ahmet Yılmaz")
            email = st.text_input("E-posta", placeholder="ahmet@abc.com")
        with col2:
            slug = st.text_input("Slug (URL kısmı) *", placeholder="abc-manti",
                                 help="Küçük harf, tire ile ayrılmış. Örn: elfiga-manti")
            telefon = st.text_input("Telefon", placeholder="0532 000 00 00")
            notlar = st.text_area("Notlar", height=68)

        st.markdown("#### 💰 Abonelik Bilgileri")
        col3, col4, col5 = st.columns(3)
        with col3:
            plan = st.selectbox("Plan", ["deneme", "temel", "pro", "kurumsal"])
        with col4:
            ucret = st.number_input("Aylık Ücret (TL)", min_value=0, value=0,
                                    help="Deneme için 0 bırakın")
        with col5:
            gun = st.number_input("Kaç Gün Erişim", min_value=1, value=30)

        st.markdown("#### 🔐 Admin Kullanıcı Bilgileri")
        col6, col7 = st.columns(2)
        with col6:
            admin_user = st.text_input("Admin Kullanıcı Adı", value="admin")
        with col7:
            admin_pass = st.text_input("Admin Parolası", type="password",
                                       placeholder="En az 6 karakter")

        submit = st.form_submit_button("✅ Müşteriyi Oluştur", type="primary", use_container_width=True)

        if submit:
            if not firma_adi or not slug:
                st.error("❌ Firma adı ve slug zorunludur!")
            elif len(admin_pass) < 6:
                st.error("❌ Parola en az 6 karakter olmalı!")
            elif " " in slug or slug != slug.lower():
                st.error("❌ Slug küçük harf ve tire içermeli, boşluk olmaz! Örn: abc-manti")
            else:
                try:
                    tenant_id = tenant_olustur(firma_adi, slug, yetkili, email, telefon, plan, ucret, gun)
                    tenant_admin_olustur(tenant_id, admin_user, admin_pass)
                    tenant_varsayilan_veri_yukle(tenant_id)

                    st.success(f"""
                    ✅ **{firma_adi}** başarıyla oluşturuldu!
                    
                    📋 **Giriş Bilgileri:**
                    - Kullanıcı: `{admin_user}`
                    - Parola: `{admin_pass}`
                    - Tenant ID: `{tenant_id}`
                    - Slug: `{slug}`
                    """)
                except Exception as e:
                    if "unique" in str(e).lower():
                        st.error(f"❌ Bu slug zaten kullanımda: `{slug}`")
                    else:
                        st.error(f"❌ Hata: {e}")

# ─────────────────────────────────────────────
# PAROLA SIFIRLA
# ─────────────────────────────────────────────
def parola_sifirla_sayfasi():
    st.markdown("## 🔑 Müşteri Parolası Sıfırla")

    tenantlar = tum_tenantlari_getir()
    if not tenantlar:
        st.info("Henüz müşteri yok.")
        return

    secenekler = {f"{t['firma_adi']} ({t['slug']})": t["id"] for t in tenantlar}
    secim = st.selectbox("Müşteri Seç", list(secenekler.keys()))
    tenant_id = secenekler[secim]

    # O tenant'ın kullanıcıları
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT username, rol FROM tenant_kullanicilar WHERE tenant_id = %s", (tenant_id,))
    kullanicilar = cur.fetchall()
    cur.close()

    if not kullanicilar:
        st.warning("Bu müşterinin kullanıcısı yok.")
        return

    k_secenekler = [k["username"] for k in kullanicilar]
    secili_k = st.selectbox("Kullanıcı", k_secenekler)

    with st.form("parola_reset_form"):
        yeni_parola = st.text_input("Yeni Parola", type="password")
        yeni_tekrar = st.text_input("Tekrar", type="password")
        if st.form_submit_button("🔑 Parolayı Sıfırla", type="primary"):
            if yeni_parola != yeni_tekrar:
                st.error("❌ Parolalar eşleşmiyor!")
            elif len(yeni_parola) < 6:
                st.error("❌ En az 6 karakter!")
            else:
                conn = get_db()
                cur = conn.cursor()
                cur.execute("""
                    UPDATE tenant_kullanicilar SET password_hash = %s
                    WHERE tenant_id = %s AND username = %s
                """, (hash_pw(yeni_parola), tenant_id, secili_k))
                cur.close()
                st.success(f"✅ {secili_k} parolası sıfırlandı!")

# ─────────────────────────────────────────────
# SİSTEM
# ─────────────────────────────────────────────
def sistem_sayfasi():
    st.markdown("## ⚙️ Sistem")

    tenantlar = tum_tenantlari_getir()

    st.markdown("### 📊 Özet İstatistikler")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Toplam Tenant", len(tenantlar))
    with col2:
        toplam_gelir = sum(float(t["aylik_ucret"] or 0) for t in tenantlar if t["durum"] == "aktif")
        st.metric("Toplam Aylık Gelir", f"{toplam_gelir:,.0f} TL")
    with col3:
        bugun = datetime.now().date()
        biten = sum(1 for t in tenantlar if t["bitis_tarihi"] and t["bitis_tarihi"] < bugun)
        st.metric("Süresi Dolmuş", biten)

    st.markdown("---")
    st.markdown("### 🔐 Süperadmin Parola Değiştir")
    with st.form("super_parola"):
        eski = st.text_input("Mevcut Parola", type="password")
        yeni = st.text_input("Yeni Parola", type="password")
        tekrar = st.text_input("Tekrar", type="password")
        if st.form_submit_button("Değiştir", type="primary"):
            if not superadmin_dogrula(st.session_state.admin_user, eski):
                st.error("❌ Mevcut parola hatalı!")
            elif yeni != tekrar:
                st.error("❌ Parolalar eşleşmiyor!")
            elif len(yeni) < 6:
                st.error("❌ En az 6 karakter!")
            else:
                conn = get_db()
                cur = conn.cursor()
                cur.execute("UPDATE superadminler SET password_hash = %s WHERE username = %s",
                            (hash_pw(yeni), st.session_state.admin_user))
                cur.close()
                st.success("✅ Parola değiştirildi!")

    st.markdown("---")
    st.markdown("### 📋 Tüm Tenantlar (Ham)")
    if tenantlar:
        df = pd.DataFrame([{
            "ID": t["id"], "Firma": t["firma_adi"], "Slug": t["slug"],
            "Plan": t["plan"], "Durum": t["durum"],
            "Aylık TL": t["aylik_ucret"], "Bitiş": str(t["bitis_tarihi"])
        } for t in tenantlar])
        st.dataframe(df, use_container_width=True, hide_index=True)

# ─────────────────────────────────────────────
# ANA AKIŞ
# ─────────────────────────────────────────────
def main():
    init_admin_db()

    if "admin_logged_in" not in st.session_state:
        st.session_state.admin_logged_in = False

    if not st.session_state.admin_logged_in:
        login_sayfasi()
        return

    menu = admin_sidebar()

    if menu == "📊 Genel Bakış":
        genel_bakis()
    elif menu == "🏢 Müşteriler":
        musteriler_sayfasi()
    elif menu == "➕ Yeni Müşteri":
        yeni_musteri_sayfasi()
    elif menu == "🔑 Parola Sıfırla":
        parola_sifirla_sayfasi()
    elif menu == "⚙️ Sistem":
        sistem_sayfasi()

if __name__ == "__main__":
    main()
