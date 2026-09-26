# Kabul testleri

Çalıştırma: `pip install -r requirements-dev.txt && pytest` (tamamı ~2 sn). Dış servisler sahte HTTP
katmanı (`tests/helpers.py: FakeFetcher`) ve sahte Telegram/SMTP/LLM sınıflarıyla taklit edilir. Saat,
`timeutil.set_clock` ile sabitlenir.

| # | Kabul maddesi | Test(ler) (`tests/test_acceptance.py`) | Neyi doğrular |
|---|---|---|---|
| 1 | Aynı olay beş kaynakta ve iki kategoride geçse de tek haber oluşur | `test_same_event_in_five_sources_and_two_categories_is_one_item`, `test_same_issue_across_five_sources_is_one_event` | Haber tarafında 5 yayındaki (Türkiye/Dünya/Genel kategorileri) aynı deprem haberi tek olay olur ve bültende tek kez, tek kategoride çıkar; farklı yerdeki deprem ayrı kalır. Teknik tarafta 2 Release health sayfası, r/sysadmin, BleepingComputer ve Born'daki aynı RDP sorunu tek olay olur. |
| 2 | Aynı KB'de iki ayrı sorun varsa iki olay korunur | `test_two_issues_same_kb_stay_separate`, `test_kb_article_issue_does_not_merge_into_other_issue_of_same_kb` | KB5999008'deki RDS ve Credential Guard sorunları ayrı olaydır. RDP belirtili saha raporu RDS olayına bağlanır; belirti belirtmeyen rapor iki sorundan birine değil, KB sürüm olayına iliştirilir. KB makalesinde yayımlanan ikinci sorun, yalnızca "kimlik doğrulama" gibi geniş bir etiketi paylaştığı için Release health'teki diğer soruna bağlanmaz. |
| 3 | Okunan saha raporu Microsoft tarafından doğrulanınca yeni gelişme bildirimi gelir | `test_read_field_report_then_ms_confirmation_notifies` | Teyitsiz VPN saha olayı bültende çıkar ve Telegram'dan okundu işaretlenir. Microsoft Known issues kaydı gelince aynı olay 2. sürüm olur (`ms_confirmed`, "Ne değişti?"), kritik alarm gönderilir ve okundu durumu otomatik yenilenmez. Sabah bülteninde yalnızca referans olarak geçer. |
| 4 | Düzeltme yayımlanınca bildirim gelir; yalnızca yazım değişince gelmez | `test_fix_notifies_but_typo_does_not` | Yazım düzeltmesi ve tarih değişikliği kanıt geçmişine kaydedilir ama sürüm oluşturmaz ve bültene girmez. "Resolved KB…" durumu `fix` değişikliğiyle 2. sürüm olur ve bültene girer. |
| 5 | Gönderilen içeriğe otomatik "okundu" konmaz; değişmeyen içerik yeniden gönderilmez | `test_sent_is_not_read_and_unchanged_is_not_resent` | Telegram'a gönderilen olay okunmamış kalır. Ertesi gün değişmediği için bültene girmez ama arşivde okunmamış durur. Aynı bülten ikinci kez kuyruğa alınamaz. |
| 6 | Günlük hava/piyasa verisi doğru zaman ve birimle gelir; eski veya eksik veri açıkça belirtilir | `test_daily_data_time_units_stale_and_missing` | Open-Meteo veri zamanı ve birimleri; TCMB referans kurunun 15:30 TSİ zamanı ve etiketi; piyasa kaynağından gram altın; bilezik verisi yoksa "doğrudan veri yok" (24 ayardan türetilmez); eski hava verisine "güncel değil"; değişim yalnızca aynı kaynak ve kalem için. |
| 7 | Kaynak kesintisi, worker yeniden başlatması ve gönderim tekrar denemeleri doğru yönetilir | `test_source_outage_is_not_reported_as_no_issues`, `test_worker_restart_and_job_idempotency`, `test_delivery_retries_without_duplicates` | Erişilemeyen kaynak olayı "çözüldü" yapmaz ve bültende kapsam uyarısı olarak görünür; tanınmayan sayfa yapısı "ayrıştırma uyarısı" olur. Yeniden başlatılan worker aynı günün bültenini tekrar oluşturmaz veya göndermez; çöken iş yeniden çalışır, bitmiş iş çalışmaz; "sending" durumunda kalan parça belirsiz sayılır ve tekrar gönderilmez. Geçici hata bekleme süresinden sonra yeniden denenir, her parça tam bir kez gönderilir; sonucu belirsiz gönderim otomatik tekrarlanmaz. |

## Diğer test grupları

| Dosya | Kapsam |
|---|---|
| `tests/test_real_pages.py` | Gerçek Microsoft sayfaları (2026-09-26): Release health durum/çözülen sorunlar ve message center; güncelleme geçmişinde ürün menü kategorisi seçimi, göreli bağlantılar, güvenlik/preview/OOB ayrımı; KB makalelerinde sorun başına ayrıştırma, kısmi düzeltme, kaynak KB; gerçek sayfalarla uçtan uca tekilleştirme (aynı sorun farklı ürün KB'lerinde tek olay) |
| `tests/test_parsers.py` | Release health (iki farklı HTML yapısı + tanınmayan sayfa), güncelleme türleri (güvenlik/preview/OOB/hotpatch), KB "Known issues" (elle hazırlanmış alternatif yapılar), Intune ve ConfigMgr (gerçek Microsoft belgeleri: MicrosoftDocs/memdocs), RSS süzme, Türkçe sayı biçimi, ICS, konum arama sıralaması (gerçek Open-Meteo yanıtı) |
| `tests/test_security.py` | SSRF (özel/yerel IP, port, şema, kullanıcı bilgisi, DNS çözümlemesi), robots.txt'nin sayfalara uygulanıp belgelenmiş API'lere uygulanmaması, yerleşik kaynak tanımlarının yenilenmesi (kullanıcı tercihi korunur, robots.txt'nin engellediği kaynak kapanır), topluluk sayfalarının resmî sayılmaması, sendikasyon kopyalarının bağımsız sayılmaması, kullanıcı kaynağının "resmî" etiket alamaması, Telegram düğmelerinin yalnızca yetkili sohbetten kabulü |
| `tests/test_llm.py` | Kanıtta olmayan KB içeren LLM çıktısının reddi, doğrulanamayan alıntının "AI çıkarımı"na düşürülmesi, günlük çağrı sınırı ve şablon yedeği, Türkçe–İngilizce haberin kanonik başlıkla tek olayda toplanması |
| `tests/test_email.py` | SMTP sonuç sınıflandırması (gönderildi / yeniden denenebilir / kalıcı / belirsiz) ve deterministik Message-ID |
| `tests/test_web.py` | Tüm sayfaların açılması, CSRF zorunluluğu, görüntülemenin "okundu" sayılmaması, e-posta bağlantısının onay gerektirmesi, ayar kaydı, özel ağ adreslerinin kaynak olarak reddi, parola modu, parolasız uzaktan erişim engeli |

## Canlı doğrulama

Otomatik testler canlı servislere bağlanmaz; gerçek sayfalardan alınmış örnekler kullanır. Kurulumdan sonra:

```bash
bulten kaynak-dogrula --hepsi   # tüm kaynakları ve hava/piyasa sağlayıcılarını sunucunuzun ağından dener, kayıt yazmaz
bulten telegram-test             # Telegram bot ve sohbet kimliğini doğrular
```

2026-09-26'daki canlı doğrulama sonucu (63 kaynaktan 59'u; kalan dördü robots.txt nedeniyle kapalı) için
bkz. KAYNAKLAR.md.
