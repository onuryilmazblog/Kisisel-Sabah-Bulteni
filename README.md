# Kişisel Sabah Bülteni

Windows istemci/sunucu, Microsoft Intune ve Configuration Manager (SCCM) yöneten bir BT uzmanı için
tek kullanıcılı, kendi sunucunuzda çalışan bir sabah bülteni. Resmî Microsoft kaynaklarını ve saha
sinyallerini izler, aynı olayı kaynaklar arasında tek kayıtta birleştirir, yalnızca maddi değişiklikte
tekrar bildirir ve Telegram/e-posta ile gönderir. Hava durumu, piyasalar, haberler, RSS/YouTube ve
takvim isteğe bağlı modüllerdir.

- **Plan ve varsayımlar:** [docs/PLAN.md](docs/PLAN.md)
- **Mimari ve veri modeli:** [docs/MIMARI.md](docs/MIMARI.md)
- **Kurulum ve dağıtım:** [docs/DAGITIM.md](docs/DAGITIM.md)
- **Servisler ve maliyet:** [docs/MALIYET.md](docs/MALIYET.md)
- **Kaynak listesi ve doğrulama durumu:** [docs/KAYNAKLAR.md](docs/KAYNAKLAR.md)
- **Kabul testleri:** [docs/KABUL-TESTLERI.md](docs/KABUL-TESTLERI.md)

## Aşama durumu

"Kod + test" otomatik testlerle doğrulanmış kodu anlatır. "Canlı" sütunu, entegrasyonun gerçek dış servise
karşı çalıştırılıp çalıştırılmadığını gösterir. Geliştirme ortamının ağ politikası çoğu dış adresi
engellediğinden canlı doğrulama sınırlı kaldı; ayrıntılar aşağıdaki "Bilinen sınırlamalar" bölümünde.

| Aşama | Modül | Kod + test | Canlı |
|---|---|---|---|
| 1 | Intune (What's new, In development, Notices) | ✅ Gerçek Microsoft belgeleriyle | ✅ GitHub kaynağından canlı okundu |
| 1 | ConfigMgr (sürümler/destek sonu, hotfix/rollup, early ring, sürüm notları, TP) | ✅ Gerçek Microsoft belgeleriyle | ✅ GitHub kaynağından canlı okundu |
| 1 | Windows release health (bilinen/çözülen sorunlar) | ✅ Elle hazırlanmış örnek HTML ile | ❌ learn.microsoft.com erişilemedi |
| 1 | Güncelleme geçmişi (KB, güvenlik/preview/OOB/hotpatch ayrımı) + KB "Known issues" | ✅ Örnek HTML ile | ❌ support.microsoft.com erişilemedi |
| 1 | Olay hafızası, eşleştirme, değişiklik analizi, teyit/risk | ✅ 7 kabul maddesi dahil | ✅ Gerçek Intune/ConfigMgr verisiyle uçtan uca çalıştı |
| 1 | Bülten, kritik alarm, gönderim kuyruğu (idempotency, yeniden deneme) | ✅ | Kanal hariç ✅ |
| 1 | Telegram (bülten, alarm, Okudum/Takip et/Sustur, long polling) | ✅ Sahte Bot API ile | ❌ api.telegram.org erişilemedi |
| 1 | Worker/zamanlayıcı | ✅ | ✅ Gerçek süreç olarak çalıştırıldı |
| 1 | Web arayüzü (Türkçe, mobil) | ✅ | ✅ Tarayıcıda (masaüstü/mobil/karanlık) kontrol edildi |
| 1 | LLM özetleri (Claude, resmî SDK) + AI'sız şablon | ✅ Sahte sağlayıcı ile | ❌ API anahtarı yok |
| 2 | Topluluk/basın RSS (r/sysadmin, r/Intune, r/SCCM, BleepingComputer, Born…) | ✅ | ❌ Adresler engelli |
| 2 | Web araması (Brave / SearXNG) | ✅ Kod | ❌ Anahtar/uç nokta yok |
| 2 | Hava durumu (Open-Meteo) | ✅ | ❌ Engelli |
| 2 | Piyasalar (TCMB referans + piyasa, bilezik ayrı) | ✅ | ❌ Engelli |
| 2 | Haberler (kategori, tekilleştirme, diller arası kanonik başlık) | ✅ | ❌ Engelli |
| 2 | E-posta (SMTP, güvenli aksiyon bağlantıları) | ✅ Sahte SMTP ile | ❌ SMTP sunucusu yok |
| 3 | Blog/RSS, YouTube (isteğe bağlı transkript), ICS takvim | ✅ (transkript hariç) | ❌ |

İlk canlı kullanımda `bulten kaynak-dogrula --hepsi` komutuyla kaynakları kendi ağınızdan doğrulayın.

## Hızlı başlangıç (yerel)

Gerekenler: Python 3.11+.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && pip install -e .
cp .env.example .env            # APP_SECRET_KEY ve gerekiyorsa diğer anahtarları doldurun
bulten init                     # veri tabanı + yerleşik kaynaklar
bulten demo-yukle               # isteğe bağlı: açıkça "Demo" etiketli kurgusal veri
bulten web                      # http://127.0.0.1:8000
bulten worker                   # ayrı bir terminalde: zamanlayıcı, toplama, gönderim, Telegram
```

İlk açılışta kurulum sihirbazı gelir. Ürün sürümlerinizi, rollerinizi, ConfigMgr sürümünüzü, konumunuzu ve
bildirim kanalınızı seçin. Uygulama bunları tahmin etmez. Kaydettiğinizde ilk kontrol sıraya alınır. İlk
taramada eski arşiv gönderilmez; ilk bülten yalnızca açık kritik sorunlardan bir "başlangıç özeti" içerir.

### Telegram

1. @BotFather ile bir bot oluşturun ve token'ı `.env` dosyasındaki `TELEGRAM_BOT_TOKEN` alanına yazın.
2. `bulten worker` çalışırken bota `/start` yazın; bot sohbet kimliğinizi yanıtlar.
3. Bu kimliği Ayarlar → Bildirimler bölümüne girin, ardından "Telegram test" düğmesine basın.
4. Kartlardaki **Okudum / Takip et / Sustur** düğmeleri yalnızca bu sohbetten kabul edilir.
   Bot komutları: `/durum`, `/kontrol`, `/bulten`, `/kimlik`.

Varsayılan mod long polling'dir ve genel bir adres gerektirmez. Webhook için `bulten telegram-webhook`
komutunu kullanın.

## Komutlar

| Komut | Ne yapar |
|---|---|
| `bulten init` | Migration'ları uygular, yerleşik kaynakları ekler |
| `bulten web [--host --port]` | Web arayüzü |
| `bulten worker` | Zamanlayıcı + worker + Telegram long polling |
| `bulten kontrol [--kritik]` | Hemen topla → eşleştir → analiz et → özetle |
| `bulten bulten [--gonder] [--manuel]` | Bülteni şimdi oluştur (ve gönder) |
| `bulten kaynak-dogrula [--slug X] [--hepsi]` | Kaynakları canlı test eder, kayıt yazmaz |
| `bulten demo-yukle` / `demo-sil` | Demo verisi |
| `bulten telegram-test` / `telegram-webhook` | Telegram testi / webhook kurulumu |
| `bulten durum` | Worker nabzı, son başarılı kontroller, kullanım |

## Nasıl çalışır (özet)

1. **Toplama:** Her kaynak kendi adaptörüyle okunur (koşullu GET, robots.txt, SSRF koruması).
   Erişilemeyen kaynak "hata" olarak kaydedilir ve "yeni sorun yok" diye yorumlanmaz.
2. **Normalleştirme:** KB, build, ürün, durum, geçici çözüm, belirti etiketleri ve Intune aşaması
   çıkarılır. Her içerik değişikliği kanıt geçmişine kaydedilir.
3. **Eşleştirme:** Önce güçlü anahtarlar kullanılır (Release health kimliği, KB, Intune iş öğesi); sonra
   KB ve belirti uyumu ile benzerliğe bakılır. Aynı KB'deki farklı sorunlar birleştirilmez. Haberler 48
   saatlik pencerede kümelenir ve her olay tek kategoride görünür.
4. **Değişiklik analizi:** Yeni sürüm yalnızca maddi değişiklikte oluşur: Microsoft teyidi, kapsam,
   risk, geçici çözüm, düzeltme, yeniden açılma, düzeltilmiş bilgi. Yazım, tarih ve düzen
   değişiklikleri sayılmaz.
5. **Özetleme:** Türkçe başlık, özet, "Beni neden ilgilendiriyor?" ve aksiyonlar üretilir; aksiyonlar
   "kaynaklı" ve "AI çıkarımı" olarak ayrılır. LLM çıktısı kanıtla doğrulanır. Anahtar yoksa şablon
   özet kullanılır ve "AI özeti yok" etiketi taşır.
6. **Gönderim:** Her gönderimin idempotency anahtarı vardır. Parçalar ayrı ayrı yeniden denenir.
   Sonucu belirsiz gönderimler otomatik tekrarlanmaz.

Teyit etiketleri: **Microsoft doğruladı — Known issues**, **Microsoft resmî açıklaması**,
**Saha bildirimi — Microsoft teyidi bulunamadı**. Risk seviyesi bunlardan ayrı hesaplanır.

## Güvenlik

- Tüm sırlar sunucudaki `.env` dosyasındadır; arayüz yalnızca "tanımlı / tanımlı değil" bilgisini gösterir.
- `APP_PASSWORD` yoksa arayüze yalnızca aynı makineden erişilebilir. İnternete açacaksanız parola ve HTTPS
  (ters proxy) kullanın; bkz. DAGITIM.md.
- Arayüzden eklenen kaynaklarda yalnızca http/https ve 80/443 portları kabul edilir. Yerel ve özel ağ
  adresleri reddedilir; yönlendirmeler ve bağlanılan IP de kontrol edilir.
- Dış içerikteki talimatlar uygulanmaz: LLM'e yalnızca veri olarak verilir, çıktı şemayla ve kanıtla doğrulanır.
- E-postadaki aksiyon bağlantıları bir onay sayfası açar. Bağlantıyı açmak tek başına durum değiştirmez.
- Uygulama hiçbir yama kaldırma ya da ortam değişikliği yapmaz.

## Testler

```bash
pip install -r requirements-dev.txt
pytest
```

54 test var: 7 kabul maddesi, gerçek Microsoft belgeleriyle ayrıştırıcılar, güvenlik (SSRF, güven
sınıflandırması, Telegram yetkisi), LLM doğrulaması, e-posta ve web arayüzü.

## Bilinen sınırlamalar

- **Windows release health ve support.microsoft.com ayrıştırıcıları canlı sayfaya karşı test edilmedi.**
  Belgelenmiş/gözlemlenen kalıplara göre yazıldılar ve yapıya toleranslılar. Beklenen yapı bulunamazsa
  kaynak "yapı tanınmadı" uyarısıyla işaretlenir. İlk kurulumda `bulten kaynak-dogrula` çalıştırın.
- MGM MeteoUyarı'nın belgelenmiş bir API'si bulunamadı. Resmî hava uyarıları otomatik okunmaz; bültende
  bağlantı verilir. İsterseniz bir CAP/Atom besleme adresi yapılandırabilirsiniz.
- Truncgil Finans ücretsiz ve resmî olmayan bir piyasa kaynağıdır; bilezik için işçilik bilgisi vermez.
  Kendi JSON kaynağınızı `MARKET_JSON_URL` / `MARKET_JSON_MAPPING` ile ekleyebilirsiniz.
- Diller arası haber eşleştirmesi LLM yapılandırıldığında güçlüdür. LLM yoksa aynı dildeki haberler
  kümelenir; Türkçe–İngilizce eşleşme sınırlı kalır.
- Docker imajı bu ortamda derlenemedi (Docker daemon yok). Kurulum adımları temiz bir sanal ortamda
  doğrulandı.
