# Kurulum ve dağıtım

Uygulama iki süreçten oluşur: `web` ve `worker`. İkisi de aynı SQLite dosyasını kullanır. Tarayıcı
kapalıyken de çalışması için worker'ın sürekli açık olduğu bir makine gerekir: küçük bir VPS, ev sunucusu
veya NAS.

## Seçenek A: Docker Compose

> Not: Docker imajı geliştirme ortamında derlenemedi (Docker daemon yok). Dockerfile'daki kurulum
> adımları temiz bir Python sanal ortamında doğrulandı.

```bash
git clone <depo> bulten && cd bulten
cp .env.example .env
# .env: APP_PASSWORD, APP_SECRET_KEY, APP_BASE_URL (https://…), TELEGRAM_BOT_TOKEN, (isteğe bağlı) LLM/SMTP/REDDIT_*
docker compose up -d --build
docker compose exec web bulten kaynak-dogrula --hepsi   # kaynakları sunucunuzun ağından doğrulayın
```

- Web portu yalnızca `127.0.0.1:8000` adresine yayınlanır. İnternetten erişim için HTTPS ters proxy
  kullanın (aşağıya bakın).
- Konteynerin içinden gelen istekler "yerel" sayılmaz. Bu yüzden Docker ile kullanımda `APP_PASSWORD`
  gereklidir. Yalnızca kendi bilgisayarınızda deneyecekseniz `ALLOW_NO_AUTH=1` kullanılabilir;
  önerilmez.
- Veriler `bulten-data` volume'ündedir.

## Seçenek B: systemd (Ubuntu/Debian)

```bash
sudo useradd --system --create-home --home-dir /opt/bulten bulten
sudo -u bulten git clone <depo> /opt/bulten && cd /opt/bulten
sudo -u bulten python3 -m venv .venv
sudo -u bulten .venv/bin/pip install -r requirements.txt
sudo -u bulten .venv/bin/pip install --no-deps .
sudo -u bulten cp .env.example .env && sudo -u bulten nano .env   # DATA_DIR=/opt/bulten/data
sudo -u bulten .venv/bin/bulten init
sudo cp deploy/systemd/bulten-*.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now bulten-web bulten-worker
journalctl -u bulten-worker -f
```

## HTTPS (ters proxy)

`deploy/Caddyfile.example` dosyasındaki gibi bir Caddy yapılandırması alan adınız için otomatik sertifika
alır. `APP_BASE_URL` değerini `https://alanadiniz` olarak ayarlayın. Bu adres e-posta aksiyon
bağlantılarında ve Telegram'daki "Uygulamada aç" düğmesinde kullanılır.

## Telegram webhook (isteğe bağlı)

Varsayılan long polling modu genel adres gerektirmez ve çoğu kurulum için yeterlidir. Webhook için:

```bash
# .env: TELEGRAM_MODE=webhook, TELEGRAM_WEBHOOK_SECRET=<rastgele>, APP_BASE_URL=https://…
bulten telegram-webhook          # Telegram'a webhook adresini bildirir
bulten telegram-webhook --kaldir # polling'e dönmek için
```

## Yedekleme

SQLite dosyası tek parça yedeklenebilir. Çalışırken tutarlı yedek almak için:

```bash
sqlite3 /opt/bulten/data/bulten.db ".backup '/yedek/bulten-$(date +%F).db'"
```

`.env` dosyasını ayrıca ve güvenli biçimde yedekleyin; sırlar içerir.

## Güncelleme

```bash
cd /opt/bulten && sudo -u bulten git pull
sudo -u bulten .venv/bin/pip install -r requirements.txt && sudo -u bulten .venv/bin/pip install --no-deps .
sudo -u bulten .venv/bin/bulten init      # yeni migration'lar
sudo systemctl restart bulten-web bulten-worker
```

Olay hafızası veri tabanında olduğu için yeniden başlatmalarda kaybolmaz. Yarım kalan gönderimler
"belirsiz" olarak işaretlenir ve otomatik tekrarlanmaz.

## İzleme

- `GET /saglik` adresi worker'ın canlı olup olmadığını ve son başarılı kontrolü JSON olarak döner;
  harici bir izleme aracıyla kullanılabilir.
- Arayüzdeki **Sistem durumu** sayfası şunları gösterir:
  - worker nabzı
  - işler ve gönderimler (belirsizleri yeniden gönderme düğmesi)
  - günlük LLM ve arama bütçesi
  - eksik yapılandırmalar
- Arayüzdeki **Kaynaklar** sayfası her kaynağın son başarılı kontrolünü ve son hatasını gösterir; "Test et"
  düğmesi kaynağı anında canlı dener.

## Ağ gereksinimleri (giden HTTPS)

| Amaç | Alan adları |
|---|---|
| Microsoft resmî | learn.microsoft.com, support.microsoft.com, raw.githubusercontent.com (Intune/ConfigMgr belge kaynağı), techcommunity.microsoft.com (resmî bloglar, isteğe bağlı) |
| Telegram | api.telegram.org |
| LLM | api.anthropic.com (veya kendi uç noktanız) |
| Hava | api.open-meteo.com, geocoding-api.open-meteo.com |
| Piyasa | www.tcmb.gov.tr, finans.truncgil.com |
| Topluluk/haber | www.bleepingcomputer.com, borncity.com, www.windowslatest.com, www.askwoody.com, haber yayınlarının RSS adresleri |
| Reddit Data API (isteğe bağlı, `REDDIT_*`) | www.reddit.com (yalnızca `POST /api/v1/access_token`, OAuth token), oauth.reddit.com (`/r/<alt forum>/new`) |
| Web araması | api.search.brave.com veya kendi SearXNG örneğiniz |
