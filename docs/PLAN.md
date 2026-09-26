# Uygulama Planı ve Varsayımlar

Bu belge geliştirmeye başlamadan önce yazıldı. Durum bilgisi README'deki
"Aşama durumu" tablosunda güncel tutulur.

## Teknoloji kararı (kısa gerekçe)

| Katman | Seçim | Neden |
|---|---|---|
| Dil | Python 3.11+ | HTML/RSS ayrıştırma (BeautifulSoup, feedparser) ve metin işleme için olgun kütüphaneler; tek dil. |
| Web | FastAPI + Jinja2 (sunucu tarafı HTML), minimal vanilla JS | Derleme adımı yok, mobilde hızlı, bakım kolay. |
| Veri tabanı | SQLite (WAL) + düz SQL migration dosyaları | Tek kullanıcı için ayrı DB sunucusu gereksiz; tek dosya, kolay yedek; web ve worker aynı dosyayı paylaşır. |
| Zamanlayıcı/worker | Ayrı `worker` süreci, DB tabanlı iş kayıtları (`job_runs`) | Tarayıcı kapalıyken çalışır; yeniden başlatmada kaldığı yerden devam; Redis/Celery gerekmez. |
| HTTP | httpx + kendi SSRF korumalı fetcher'ı | Koşullu GET (ETag), zaman aşımı, yeniden deneme, özel ağ engeli. |
| LLM | Değiştirilebilir sağlayıcı: Anthropic Claude (resmî SDK), OpenAI uyumlu uç nokta, "yok" (şablon) | Anahtar yoksa uygulama çalışmaya devam eder; LLM kaynak yerine konmaz. |
| Bildirim | Telegram Bot API (long polling), SMTP e-posta | Genel URL gerektirmez; e-posta her sağlayıcıyla çalışır. |
| Dağıtım | Docker Compose (web + worker + ortak volume) veya systemd | Küçük bir VPS ya da ev sunucusu yeterli. |

## Mimari (ayrı adımlar)

1. **Toplama** – her kaynak için adaptör; ham yanıtın özeti ve kontrol kaydı (`source_checks`).
2. **Normalleştirme** – adaptör çıktısı → `observations` (KB, ürün, build, durum, geçici çözüm vb. yapılandırılmış alanlar) + kanıt anlık görüntüsü.
3. **Olay eşleştirme** – güçlü anahtarlar (Release health kimliği, KB, Intune iş öğesi) + KB/belirti etiketi/benzerlik ile kaynaklar ve diller arası ilişkilendirme. Aynı KB'deki farklı belirtiler ayrı olay kalır.
4. **Değişiklik analizi** – olayın "maddi durumu" (teyit, durum, kapsam, risk, geçici çözüm, düzeltme) hesaplanır; yalnızca maddi değişiklikte yeni `event_version` oluşur. Yazım/tarih/düzen değişiklikleri sayılmaz.
5. **Özetleme** – yeni sürümler için Türkçe başlık, 2–3 cümle özet, "Beni neden ilgilendiriyor?", aksiyonlar (kaynaklı / AI çıkarımı ayrı), "Ne değişti?". LLM çıktısı şemayla doğrulanır; kaynaklı denilen aksiyonun alıntısı kanıtta yoksa "AI çıkarımı"na düşürülür.
6. **Gönderim** – bülten ve kritik alarm; idempotency anahtarlı `deliveries`, parça bazlı yeniden deneme, belirsiz gönderimlerde otomatik tekrar yok.

Hava, piyasa ve takvim `daily_data` tablosunda, olay hafızasından ayrı işlenir.

## Varsayımlar (rutin kararlar)

1. Tek kullanıcı, kendi sunucusunda çalışır. İnternete açılırsa `APP_PASSWORD` ve HTTPS (reverse proxy) zorunlu kabul edilir.
2. Windows release health için resmî RSS yok; Microsoft Graph "Windows updates" API'si tenant uygulama izni gerektirir. İlk sürümde Learn HTML sayfaları ayrıştırılır; Graph sonraki aşama seçeneğidir.
3. Intune ve ConfigMgr sayfalarının kaynağı Microsoft'un açık belge deposu (MicrosoftDocs/memdocs). Birincil okuma bu markdown kaynağından yapılır (iş öğesi kimlikleri korunur), Learn HTML yedektir; kullanıcıya gösterilen bağlantı her zaman Learn adresidir.
4. Hava için Open-Meteo (anahtarsız). MGM MeteoUyarı'nın belgelenmiş bir API'si bulunamadı: resmî uyarılar otomatik okunmaz, bültende bu açıkça yazılır ve MGM bağlantısı verilir. İsteğe bağlı CAP/Atom uyarı beslemesi yapılandırılabilir.
5. Piyasa: TCMB gösterge kuru (referans) ile piyasa kuru ayrı kaynaklardan ve ayrı etiketle gelir. Altın/bilezik için ücretsiz Truncgil Finans veya kullanıcı tanımlı JSON kaynağı. Bilezik fiyatı hiçbir zaman 24 ayardan oranlanmaz; işçilik bilgisi kaynakta yoksa "kaynak belirtmiyor" yazılır.
6. LLM varsayılanı Anthropic `claude-opus-5`; model `.env` ile değiştirilebilir. Anahtar yoksa AI'sız şablon özet kullanılır ve "AI özeti yok" diye etiketlenir.
7. Web araması (yeni saha raporlarını keşfetmek için) Brave Search API veya kendi SearXNG örneğiyle; yapılandırılmazsa kapalıdır ve kapsam ekranında belirtilir.
8. Telegram long polling kullanır (genel URL gerekmez). E-posta SMTP ile; e-postadaki aksiyon bağlantıları uygulamada onay sayfası açar (bağlantıyı açmak tek başına durum değiştirmez; e-posta tarayıcıları linkleri önceden açabilir).
9. Takvim, kullanıcının verdiği salt okunur ICS adresiyle okunur (OAuth yok, yazma izni yok).
10. YouTube: kanal RSS'i. Transkript erişimi isteğe bağlıdır; yoksa özet "yalnızca başlık/açıklama" etiketi taşır.
11. Konum, ürün sürümleri, ConfigMgr sürümü tahmin edilmez; kurulum sihirbazında kullanıcı seçer. Seçim yapılmayan alanlar "belirtilmedi" olarak kalır.
12. Saat dilimi `Europe/Istanbul`, bülten 08.00 varsayılan; değiştirilebilir.

## Aşamalar

| Aşama | Kapsam |
|---|---|
| 1 | Windows Client/Server, Intune, ConfigMgr toplama; olay hafızası; değişiklik analizi; Telegram bülteni + kritik alarm + Okudum/Takip et/Sustur; temel web ekranları; worker/zamanlayıcı. |
| 2 | Hava, piyasalar, haberler (kategori tekilleştirme), topluluk/saha sinyalleri ve web araması, e-posta. |
| 3 | Blog/RSS, YouTube, takvim; ek ince ayarlar. |

## Canlı doğrulama durumu

İlk geliştirme turunda bulut konteynerinin ağ politikası Microsoft ve diğer dış siteleri engellediği için
Windows release health ve support.microsoft.com ayrıştırıcıları elle hazırlanmış örneklerle yazılmıştı.
Ağ erişimi açıldıktan sonra (2026-09-26):

- `bulten kaynak-dogrula --hepsi` ile 63 kaynak/sağlayıcı canlı denendi; 59'u doğrulandı. Kalan dördü (Reddit
  ×3, Webrazzi) robots.txt nedeniyle okunamıyor ve varsayılan olarak kapatıldı. Ayrıntı: KAYNAKLAR.md.
- Release health (21 durum/çözülen sorunlar sayfası + message center) ve support.microsoft.com (11 güncelleme
  geçmişi sayfası, KB makaleleri) ayrıştırıcıları gerçek sayfalara karşı test edildi. Bulunan hatalar
  düzeltildi ve gerçek sayfalardan küçültülmüş örnekler `tests/fixtures/ms-real/` altına eklendi:
  - Güncelleme geçmişi KB listesi ana içerikte değil, tüm ürün ailesini içeren sol menüde; eski ayrıştırıcı
    hiç KB bulamıyordu. Artık ürünün menü kategorisi okunuyor.
  - KB makalelerinde bilinen sorunlar `<details>` blokları; eski ayrıştırıcı hepsini tek kayıtta birleştiriyordu.
  - Release health'te sorun kuyruğu iç içe div'lerde; "affected platforms listed below" cümlesi etiket sanılıyordu.
  - "Partially resolved" ifadesindeki KB tam düzeltme sayılıyordu; artık ayrı (`partial_fix_kbs`).
  - Open-Meteo API alan adının robots.txt'si tarayıcılara `Disallow: /` döndürüyor; belgelenmiş API
    çağrıları robots.txt denetiminden ayrıldı (sayfa/besleme okumalarında robots.txt uygulanmaya devam ediyor).
- Gerçek verilerle uçtan uca tur (toplama → eşleştirme → analiz → bülten → web arayüzü) çalıştırıldı. Aynı
  sorunun ürün başına farklı KB numarasıyla yayımlanması tekrar eden olaylar üretiyordu; eşleştirme buna göre
  düzeltildi ve gerçek sayfalarla regresyon testi eklendi. Değişmeyen içerikle ikinci toplama 0 yeni sürüm üretti.
- Canlı çalıştırılmayanlar: Telegram, SMTP, Anthropic API (anahtar/sunucu yok), Brave/SearXNG web araması
  (yapılandırılmadı), YouTube transkripti.
