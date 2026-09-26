# Mimari

## Süreçler

```
┌──────────────┐        SQLite (WAL, tek dosya: data/bulten.db)        ┌──────────────┐
│  bulten web  │  ◀──────────────────────────────────────────────────▶ │ bulten worker│
│ FastAPI+HTML │   ayarlar, olaylar, bültenler, iş istekleri, gönderim │ zamanlayıcı  │
└──────────────┘                                                       │ + Telegram   │
                                                                       │ long polling │
                                                                       └──────────────┘
```

- Web süreci ağır iş yapmaz. "Şimdi kontrol et" gibi istekleri `job_requests` tablosuna yazar; worker
  bunları en fazla 30 saniye içinde alır.
- Worker her 30 saniyede bir tik atar:
  1. Elle istenen işler
  2. Periyodik toplama (`COLLECT_INTERVAL_MIN`)
  3. Kritik alarm kontrolü (ayarlardaki aralıkla)
  4. Bülten öncesi toplama (bülten saatinden 25 dk önce)
  5. Günlük bülten
  6. Gönderim kuyruğu
  7. Günlük temizlik
- Her iş `job_runs(job, slot)` ile benzersizdir, bu yüzden aynı gün iki bülten oluşmaz. Nabzı 30
  dakikadır duran bir iş, çökmüş sayılır ve yeniden çalıştırılır. Adımlar idempotent olduğu için bu
  güvenlidir.

## İşlem hattı (ayrı adımlar)

| Adım | Modül | Girdi → çıktı |
|---|---|---|
| 1. Toplama | `pipeline/collect.py`, `sources/*` | kaynak → `source_checks`, ham yanıt önbelleği (`http_cache`) |
| 2. Normalleştirme | adaptörler | → `observations` (yapılandırılmış alanlar) + `observation_snapshots` (kanıt geçmişi) |
| 2b. Kanonik başlık (isteğe bağlı) | `pipeline/canonical.py` | Türkçe haber/saha başlıkları → İngilizce kanonik başlık (LLM, toplu) |
| 3. Olay eşleştirme | `pipeline/match.py` | gözlem → `events` + `event_aliases` |
| 4. Değişiklik analizi | `pipeline/analyze.py` | olay durumu → yalnızca maddi değişiklikte `event_versions` |
| 5. Özetleme | `pipeline/summarize.py` | sürüm → Türkçe özet (LLM veya şablon), kanıt doğrulaması |
| 6. Derleme | `pipeline/bulletin.py` | sürümler → `bulletins` / kritik alarm seçimi |
| 7. Gönderim | `delivery/*` | `deliveries` + `delivery_parts` + `delivery_items` + `delivery_attempts` |

Günlük veriler (hava, piyasa, takvim) `daily/*` modüllerinde toplanır ve `daily_data` tablosunda
saklanır. Olay hafızasına ve tekrar filtresine girmezler.

## Eşleştirme kuralları

1. **Güçlü anahtar (alias):**
   - `wrh:<id>`: Release health sorun kimliği; aynı sorun birden çok sürüm sayfasında aynı kimlikle geçer
   - `kb:<numara>`: güncelleme sürümü
   - `intune:wi:<iş öğesi>` ve `intune:t:<başlık>`: Intune kaydı; markdown ve HTML kaynağı aynı olaya düşer
   - `cm:*`: ConfigMgr kayıtları
   - `url:<kanonik adres>`: haber, saha raporu ve içerikler
2. **Resmî bilinen sorun ↔ sorun olayı** (saha kaynaklı olanlar dahil): Ortak KB ile uyumlu belirti
   etiketleri ya da yüksek başlık benzerliği aranır. Özgül belirti etiketleri ayrışıyorsa eşleşme
   reddedilir; bu kural aynı KB'deki iki farklı sorunu ayrı tutar. İki farklı Release health kimliği
   yalnızca başlıklar neredeyse aynıysa birleşir. Gerçek verilerden gelen iki ek kural:
   - **Aynı resmî başlık:** Microsoft aynı sorunu her ürün için farklı KB numarasıyla ama aynı başlıkla
     yayımlar (ör. WSUS sorunu Server 2025'te KB5122871, Server 2022'de KB5122882). Resmî kayıtların
     başlıkları neredeyse aynıysa KB ve ürün farkına bakılmadan tek olay olur.
   - **Düzelten KB:** Microsoft açık sorunu, onu kısmen düzelten sonraki KB'lerin makalelerinde de (bazen
     farklı başlıkla) listeler. KB X makalesindeki sorun, Release health'in "X ile (kısmen) düzeltildi"
     dediği sorunla ayırt edici bir belirti paylaşıyorsa aynı olaya bağlanır. Bu turda açılmış bir olay
     böylece köprülenirse ikisi birleştirilir (sürümü veya kullanıcı durumu olan olay birleştirilmez).
3. **Saha raporu:** KB ve belirti örtüşüyorsa ya da başlık benzerliği güçlüyse eşleşir. KB anan ama
   belirti belirtmeyen rapor hangi soruna ait olduğu bilinemediği için KB sürüm olayına iliştirilir.
4. **Haber:** 48 saatlik pencerede olaydaki tüm başlıklarla karşılaştırılır (tekli bağlantı). Başlıktaki
   özel adlar ve sayılar tamamen ayrışıyorsa eşleşmez (ör. "Van'da deprem" ile "İstanbul'da deprem").
   İlk kaynağın kategorisi olayın tek kategorisi olur.

Metin karşılaştırması Türkçe büyük/küçük harf kurallarını ve aksan katlamayı uygular, 5 karakterlik
önek kökleme kullanır. Belirti sözlüğü İngilizce ve Türkçe anahtar kelimeler içerir.

## Maddi durum ve sürümleme

Sorunlar için maddi durum şu alanlardan oluşur: teyit düzeyi, durum, ürünler, belirti etiketleri,
tetikleyen KB'ler, düzelten KB'ler, kısmen düzelten KB'ler ("partially resolved"; tam düzeltme sayılmaz), geçici çözüm (var/yok + token imzası), KIR, düzeltme var mı, risk
ve saha kaynağı sayısı kovası (1 / 2 / 5+).

Yeni sürüm oluşturan değişiklikler:

| Tür | Ne zaman |
|---|---|
| `ms_confirmed` | Teyit düzeyi yükseldi (saha → resmî → Known issues) |
| `scope_expanded` | Yeni ürün, yeni özgül belirti veya yeni tetikleyen KB |
| `correction` | Ürün listesinden çıkarma, tür düzeltmesi |
| `workaround` / `workaround_updated` | Geçici çözüm/KIR yayımlandı; metin önemli ölçüde değişti (Jaccard < 0,5) |
| `fix` | Durum "çözüldü" oldu veya düzelten KB eklendi |
| `partial_fix` | Sorunu kısmen düzelten KB eklendi ("partially resolved"); durum açık kalır |
| `reopened` | Çözüldü → açık |
| `risk_changed` | Risk seviyesi değişti |
| `spread` | Teyitsiz olayda bağımsız saha kaynağı eşiği aşıldı |
| `stage_changed` | Intune aşaması değişti (in development → preview → GA) |
| `action_required` / `deprecation` | Yönetici aksiyonu veya kaldırma bilgisi eklendi |
| `support_ending` | ConfigMgr destek bitişi kovası değişti (≤180/90/30/7 gün, bitti) |
| `pulled` | Microsoft güncellemeyi geri çekti (EXPIRED) |

Yazım düzeltmesi, tarih ve "last updated" değişikliği ile sayfa düzeni değişikliği yeni sürüm
oluşturmaz, ama kanıt geçmişine kaydedilir.

## Teyit ve risk

- **Teyit:** `ms_known_issue` kaydı Release health, KB makalesindeki "Known issues" veya ConfigMgr sürüm
  notlarından gelir. `ms_official` diğer resmî Microsoft kaynaklarından gelir. `field` saha
  raporlarıdır. Microsoft alan adındaki topluluk sayfaları (Q&A, Tech Community tartışmaları,
  answers.microsoft.com) resmî sayılmaz.
- **Risk:** Etki alanına göre hesaplanır:
  - Kimlik doğrulama, DC, açılış ve BitLocker > RDS, VPN, ağ, Hyper-V > kurulum, yazdırma…
  - Sunucu ürünü etkileniyorsa risk artar.
  - Geçici çözüm varsa biraz, sorun çözüldüyse çok düşer.
  - Teyit düzeyi riski değiştirmez.
- **Bağımsız kaynak:** Birbirini kopyalayan yayınlar (metin benzerliği, "via …" atfı) ve aynı alan
  adındaki basın makaleleri tek kaynak sayılır.
- **İlgi (kullanıcıya göre):** Ürün, rol, ConfigMgr sürümü, Intune platformu, takip ve anahtar
  kelimelerden hesaplanır. Sürüm oluşturmaz; ayarlar değişince yeniden hesaplanır.

## Bülten ve bildirim kuralları

- Sıra şöyledir:
  1. Başlangıç özeti (yalnızca ilk bülten)
  2. Kritik ve ortamınızla ilgili gelişmeler
  3. Gece alarmla bildirilenlerin kısa referansı
  4. Windows / Intune / ConfigMgr
  5. Saha sinyalleri
  6. Haberler (kategori bazında)
  7. İçerikler
- Kategori sınırları ve toplam sınır (kısa/orta/uzun) uygulanır. Sığmayanlar arşivde okunmamış kalır.
- Bir bültende yer almış sürüm tekrar gönderilmez. Aynı olayın yeni sürümü gönderilir.
- Okunan veya susturulan olayların yeni sürümleri için davranış ayarlanabilir (`resurface`).
- Kritik alarmla bildirilen değişmemiş sürüm sabah bülteninde yalnızca referans olarak geçer.
- "Gönderildi" (`delivery_items`), "görüntülendi", "okundu" ve "susturuldu" (`user_event_state`) ayrı
  tutulur. Gönderim okundu sayılmaz.

## Gönderim güvenilirliği

- `deliveries.idempotency_key` benzersizdir. Örnekler:
  - `bulletin:daily:2026-09-26:telegram:<chat>`
  - `alert:telegram:<chat>:<sürüm özeti>`
- Parça durumları: `pending → sending → sent | failed | uncertain`. "sending" durumu ağ çağrısından
  önce kaydedilir. Worker çökerse bu parçalar başlangıçta "uncertain" yapılır.
- Sınıflandırma:
  - Bağlantı kurulamadı, 429 veya 5xx → yeniden denenir (1, 5, 15, 60, 180 dk; en fazla 6 deneme).
  - Yanıt alınamadı (okuma zaman aşımı, bağlantı koptu) → "belirsiz"; otomatik tekrar yok, arayüzden
    elle yeniden gönderilir.
  - 4xx → kalıcı hata.

## Veri tabanı tabloları (özet)

| Tablo | Amaç |
|---|---|
| `settings`, `kv` | Kullanıcı tercihleri; offset, nabız, `baseline_at` gibi sistem değerleri |
| `sources`, `source_checks`, `http_cache` | Kaynaklar, kontrol geçmişi, koşullu GET önbelleği |
| `observations`, `observation_snapshots` | Normalleştirilmiş kayıtlar ve kanıt geçmişi |
| `events`, `event_aliases`, `event_versions`, `event_version_evidence` | Olay hafızası |
| `user_event_state`, `user_actions` | Görüntülendi/okundu/takip/sustur ve eylem günlüğü |
| `bulletins`, `bulletin_items` | Oluşturulan bültenler |
| `deliveries`, `delivery_parts`, `delivery_items`, `delivery_attempts` | Gönderim kayıtları |
| `daily_data` | Hava, piyasa, takvim anlık görüntüleri |
| `job_runs`, `job_requests` | Zamanlayıcı ve elle istenen işler |
| `usage_log`, `llm_cache` | Günlük bütçe/kullanım ve LLM önbelleği |

Şema: `bulten/migrations/0001_initial.sql`. Yeni migration'lar `000N_*.sql` adıyla eklenir; `bulten init`
ve her süreç başlangıcı uygulanmamış olanları sırayla uygular.

## Dizin yapısı

```
bulten/
  config.py, settings_store.py, catalog.py, db.py, timeutil.py, textutil.py, usage.py, demo.py, cli.py
  migrations/         SQL şeması
  net/                güvenli HTTP okuyucu, SSRF kuralları
  sources/            adaptörler: wrh, ms_support, intune, configmgr, rss, reddit_api, websearch, youtube, registry
  pipeline/           collect, canonical, match, evidence, analyze, summarize, cards, bulletin, run, validate
  llm/                sağlayıcı arayüzü, Anthropic (resmî SDK), OpenAI uyumlu
  daily/              weather, markets, calendar_ics, service
  delivery/           actions, render, daily_render, telegram, email, dispatcher
  worker/             scheduler, main
  web/                app, auth, forms, queries, templates/, static/
tests/                kabul, ayrıştırıcı, güvenlik, LLM, e-posta ve web testleri; fixtures/
```
