"""
Sıcaklık API - ESP32/Arduino'dan HTTP POST ile veri alır
Bu dosya ayrı bir Railway servisi olarak çalışır (Flask)

ESP32 şu şekilde veri gönderir:
POST /api/sicaklik
Headers: X-API-Key: <api_key>
Body: {"sensor_id": "don_odasi", "sicaklik": -18.5, "nem": 65.2}
"""

from flask import Flask, request, jsonify
import psycopg2
import psycopg2.extras
import os
import json
from datetime import datetime
import hashlib

app = Flask(__name__)

# ─────────────────────────────────────────────
# VERİTABANI
# ─────────────────────────────────────────────
def get_db():
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(db_url)

def init_sicaklik_db():
    conn = get_db()
    cur = conn.cursor()
    
    # Sensör tablosu
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sicaklik_sensorler (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER,
            sensor_id TEXT NOT NULL,
            sensor_adi TEXT DEFAULT '',
            konum TEXT DEFAULT '',
            min_alarm NUMERIC DEFAULT -25.0,
            max_alarm NUMERIC DEFAULT 5.0,
            aktif BOOLEAN DEFAULT TRUE,
            api_key TEXT,
            olusturma_tarihi TIMESTAMP DEFAULT NOW(),
            UNIQUE(tenant_id, sensor_id)
        )
    """)
    
    # Sıcaklık ölçüm tablosu
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sicaklik_olcumler (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER,
            sensor_id TEXT NOT NULL,
            sicaklik NUMERIC NOT NULL,
            nem NUMERIC,
            kayit_zamani TIMESTAMP DEFAULT NOW()
        )
    """)
    
    # İndeks — hızlı sorgu için
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_sicaklik_tenant_sensor 
        ON sicaklik_olcumler(tenant_id, sensor_id, kayit_zamani DESC)
    """)
    
    # Alarm log tablosu
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sicaklik_alarmlar (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER,
            sensor_id TEXT,
            sicaklik NUMERIC,
            alarm_tipi TEXT,
            mesaj TEXT,
            goruldu BOOLEAN DEFAULT FALSE,
            kayit_zamani TIMESTAMP DEFAULT NOW()
        )
    """)
    
    conn.commit()
    cur.close()
    conn.close()

def api_key_dogrula(api_key, tenant_id=None):
    """API key ile sensörü doğrula"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if tenant_id:
        cur.execute("SELECT * FROM sicaklik_sensorler WHERE api_key = %s AND tenant_id = %s AND aktif = TRUE",
                    (api_key, tenant_id))
    else:
        cur.execute("SELECT * FROM sicaklik_sensorler WHERE api_key = %s AND aktif = TRUE", (api_key,))
    sensor = cur.fetchone()
    cur.close()
    conn.close()
    return dict(sensor) if sensor else None

def alarm_kontrol(tenant_id, sensor_id, sicaklik, min_alarm, max_alarm):
    """Alarm sınırlarını kontrol et ve kaydet"""
    conn = get_db()
    cur = conn.cursor()
    
    alarm_tipi = None
    mesaj = None
    
    if sicaklik < min_alarm:
        alarm_tipi = "DUSUK"
        mesaj = f"⬇️ DÜŞÜK SICAKLIK! {sicaklik}°C (min: {min_alarm}°C)"
    elif sicaklik > max_alarm:
        alarm_tipi = "YUKSEK"
        mesaj = f"⬆️ YÜKSEK SICAKLIK! {sicaklik}°C (max: {max_alarm}°C)"
    
    if alarm_tipi:
        cur.execute("""
            INSERT INTO sicaklik_alarmlar (tenant_id, sensor_id, sicaklik, alarm_tipi, mesaj)
            VALUES (%s, %s, %s, %s, %s)
        """, (tenant_id, sensor_id, sicaklik, alarm_tipi, mesaj))
        conn.commit()
    
    cur.close()
    conn.close()
    return mesaj

# ─────────────────────────────────────────────
# API ENDPOINT'LERİ
# ─────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

@app.route("/api/sicaklik", methods=["POST"])
def sicaklik_al():
    """ESP32'den sıcaklık verisi al"""
    api_key = request.headers.get("X-API-Key", "")
    if not api_key:
        return jsonify({"error": "API key gerekli"}), 401
    
    sensor = api_key_dogrula(api_key)
    if not sensor:
        return jsonify({"error": "Geçersiz API key"}), 403
    
    data = request.get_json()
    if not data or "sicaklik" not in data:
        return jsonify({"error": "sicaklik alanı gerekli"}), 400
    
    sicaklik = float(data["sicaklik"])
    nem = float(data.get("nem", 0)) if data.get("nem") else None
    
    # Ölçümü kaydet
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sicaklik_olcumler (tenant_id, sensor_id, sicaklik, nem)
        VALUES (%s, %s, %s, %s)
    """, (sensor["tenant_id"], sensor["sensor_id"], sicaklik, nem))
    conn.commit()
    cur.close()
    conn.close()
    
    # Alarm kontrol
    alarm = alarm_kontrol(
        sensor["tenant_id"], sensor["sensor_id"],
        sicaklik, sensor["min_alarm"], sensor["max_alarm"]
    )
    
    response = {
        "status": "ok",
        "sensor_id": sensor["sensor_id"],
        "sicaklik": sicaklik,
        "nem": nem,
        "timestamp": datetime.now().isoformat()
    }
    if alarm:
        response["alarm"] = alarm
    
    return jsonify(response), 200

@app.route("/api/son_olcum/<int:tenant_id>/<sensor_id>", methods=["GET"])
def son_olcum(tenant_id, sensor_id):
    """Web arayüzü için son ölçümü getir"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT sicaklik, nem, kayit_zamani 
        FROM sicaklik_olcumler 
        WHERE tenant_id = %s AND sensor_id = %s 
        ORDER BY kayit_zamani DESC LIMIT 1
    """, (tenant_id, sensor_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return jsonify({
            "sicaklik": float(row["sicaklik"]),
            "nem": float(row["nem"]) if row["nem"] else None,
            "zaman": row["kayit_zamani"].isoformat()
        })
    return jsonify({"error": "Veri yok"}), 404

@app.route("/api/gecmis/<int:tenant_id>/<sensor_id>", methods=["GET"])
def gecmis_olcumler(tenant_id, sensor_id):
    """Son 100 ölçümü getir"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT sicaklik, nem, kayit_zamani 
        FROM sicaklik_olcumler 
        WHERE tenant_id = %s AND sensor_id = %s 
        ORDER BY kayit_zamani DESC LIMIT 100
    """, (tenant_id, sensor_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{
        "sicaklik": float(r["sicaklik"]),
        "nem": float(r["nem"]) if r["nem"] else None,
        "zaman": r["kayit_zamani"].isoformat()
    } for r in rows])

# Tablo oluştur - her zaman
init_sicaklik_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
