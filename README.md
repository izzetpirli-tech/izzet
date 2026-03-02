# 🥟 ELFİGA MANTI - Web Uygulaması

## Railway'e Deploy Talimatları (Adım Adım)

### 1. GitHub'a Yükle
```bash
git init
git add .
git commit -m "İlk commit - ELFİGA web uygulaması"
git remote add origin https://github.com/KULLANICI_ADINIZ/elfiga-manti.git
git push -u origin main
```

### 2. Railway Hesabı Aç
- https://railway.app adresine git
- GitHub ile giriş yap (ücretsiz)

### 3. Yeni Proje Oluştur
- "New Project" → "Deploy from GitHub repo" tıkla
- elfiga-manti reposunu seç

### 4. PostgreSQL Ekle
- Proje içinde "+ New" → "Database" → "PostgreSQL" seç
- Railway otomatik olarak DATABASE_URL environment variable'ını atar

### 5. Environment Variables Ekle
Proje → Settings → Environment Variables:
```
ADMIN_PASSWORD = elfiga2024    ← İlk giriş parolası (değiştir!)
```

### 6. Deploy!
Railway otomatik deploy eder. Birkaç dakika sonra URL alırsın.

---

## 🔐 İlk Giriş
- **Kullanıcı:** admin
- **Parola:** elfiga2024 (veya ADMIN_PASSWORD olarak ayarladığın değer)

⚠️ İlk girişten sonra parolayı değiştirmeyi unutma!

---

## 📁 Dosya Yapısı
```
elfiga_web/
├── app.py              ← Ana uygulama
├── requirements.txt    ← Python paketleri
├── Procfile           ← Railway başlatma komutu
├── railway.toml       ← Railway yapılandırması
└── .gitignore
```

## 🔄 Güncelleme
Değişiklik yapınca:
```bash
git add .
git commit -m "güncelleme açıklaması"
git push
```
Railway otomatik yeniden deploy eder.
# izzet
