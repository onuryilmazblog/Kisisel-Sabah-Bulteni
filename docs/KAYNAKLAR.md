# Kaynaklar ve doğrulama durumu

Kaynak adresleri veri tabanında saklanır ve **Kaynaklar** sayfasından açılıp kapatılabilir, test edilebilir;
yeni RSS/Atom kaynakları eklenebilir. Aşağıdaki liste yerleşik kaynaklardır.

**Canlı doğrulama (2026-09-26):** `bulten kaynak-dogrula --hepsi` ile 63 kaynaktan 59'u doğrulandı. Başarısız
olan dördü (3 Reddit beslemesi, Webrazzi) robots.txt nedeniyle okunamıyor ve varsayılan olarak kapalı. Kayıt
sayıları doğrulama anındaki değerlerdir; topluluk beslemeleri yalnızca izlenen ürünlerle ilgili sorun
bildirimlerini süzdüğü için 0 kayıt normaldir. Bu doğrulamadan sonra üç Reddit kaynağı RSS yerine Reddit
Data API (OAuth) adaptörüne geçirildi; bu adaptör henüz canlı doğrulanmadı (aşağıya bakın).

- ✅ **Canlı doğrulandı:** adaptör gerçek ağ üzerinden çalıştırıldı ve beklenen yapı bulundu.
- ⛔ **robots.txt engelliyor:** site otomatik erişime izin vermiyor. Uygulama robots.txt'ye uyar ve başka bir
  tarayıcı kimliğine bürünmez.
- 🔑 **Kimlik bilgisi gerekli:** kaynak `.env` ile yapılandırılmadıkça kapalıdır; `bulten kaynak-dogrula`
  onu "yapılandırılmadı" olarak raporlar.

\* Ürün bazlı Windows kaynakları kurulumda seçtiğiniz ürünlere göre otomatik açılır/kapanır.

| Modül | Kaynak | Tür | Güven | Varsayılan | Adres | Doğrulama |
|---|---|---|---|---|---|---|
| windows | Release health: Windows 11, sürüm 26H1 | Release health – bilinen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/status-windows-11-26h1> | ✅ Canlı doğrulandı (7 kayıt) |
| windows | Çözülen sorunlar: Windows 11, sürüm 26H1 | Release health – çözülen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/resolved-issues-windows-11-26H1> | ✅ Canlı doğrulandı (7 kayıt) |
| windows | Güncelleme geçmişi: Windows 11, sürüm 26H1 | Güncelleme geçmişi (KB listesi) | official | kapalı* | <https://support.microsoft.com/en-us/servicing/os/windows-11/2026/02/windows-11-version-26h1-update-history> | ✅ Canlı doğrulandı (10 kayıt) |
| windows | Release health: Windows 11, sürüm 25H2 | Release health – bilinen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/status-windows-11-25h2> | ✅ Canlı doğrulandı (10 kayıt) |
| windows | Çözülen sorunlar: Windows 11, sürüm 25H2 | Release health – çözülen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/resolved-issues-windows-11-25h2> | ✅ Canlı doğrulandı (22 kayıt) |
| windows | Güncelleme geçmişi: Windows 11, sürüm 25H2 | Güncelleme geçmişi (KB listesi) | official | kapalı* | <https://support.microsoft.com/en-us/servicing/os/windows-11/2025/07/windows-11-version-25h2-update-history> | ✅ Canlı doğrulandı (11 kayıt) |
| windows | Release health: Windows 11, sürüm 24H2 | Release health – bilinen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/status-windows-11-24h2> | ✅ Canlı doğrulandı (10 kayıt) |
| windows | Çözülen sorunlar: Windows 11, sürüm 24H2 | Release health – çözülen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/resolved-issues-windows-11-24h2> | ✅ Canlı doğrulandı (31 kayıt) |
| windows | Güncelleme geçmişi: Windows 11, sürüm 24H2 | Güncelleme geçmişi (KB listesi) | official | kapalı* | <https://support.microsoft.com/en-us/servicing/os/windows-11/2024/09/windows-11-version-24h2-update-history> | ✅ Canlı doğrulandı (11 kayıt) |
| windows | Release health: Windows 11, sürüm 23H2 | Release health – bilinen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/status-windows-11-23h2> | ✅ Canlı doğrulandı (4 kayıt) |
| windows | Çözülen sorunlar: Windows 11, sürüm 23H2 | Release health – çözülen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/resolved-issues-windows-11-23h2> | ✅ Canlı doğrulandı (12 kayıt) |
| windows | Güncelleme geçmişi: Windows 11, sürüm 23H2 | Güncelleme geçmişi (KB listesi) | official | kapalı* | <https://support.microsoft.com/en-us/servicing/os/windows-11/2023/09/windows-11-version-23h2-update-history> | ✅ Canlı doğrulandı (5 kayıt) |
| windows | Release health: Windows 10, sürüm 22H2 (ESU) | Release health – bilinen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/status-windows-10-22h2> | ✅ Canlı doğrulandı (4 kayıt) |
| windows | Çözülen sorunlar: Windows 10, sürüm 22H2 (ESU) | Release health – çözülen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/resolved-issues-windows-10-22h2> | ✅ Canlı doğrulandı (16 kayıt) |
| windows | Güncelleme geçmişi: Windows 10, sürüm 22H2 (ESU) | Güncelleme geçmişi (KB listesi) | official | kapalı* | <https://support.microsoft.com/en-us/servicing/os/windows-10/2022/09/windows-10-update-history> | ✅ Canlı doğrulandı (5 kayıt) |
| windows | Release health: Windows 10 Enterprise LTSC 2021 | Release health – bilinen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/status-windows-10-21h2> | ✅ Canlı doğrulandı (4 kayıt) |
| windows | Çözülen sorunlar: Windows 10 Enterprise LTSC 2021 | Release health – çözülen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/resolved-issues-windows-10-21h2> | ✅ Canlı doğrulandı (12 kayıt) |
| windows | Güncelleme geçmişi: Windows 10 Enterprise LTSC 2021 | Güncelleme geçmişi (KB listesi) | official | kapalı* | <https://support.microsoft.com/en-us/servicing/os/windows-10/2022/09/windows-10-update-history> | ✅ Canlı doğrulandı (5 kayıt) |
| windows | Release health: Windows Server 2025 | Release health – bilinen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/status-windows-server-2025> | ✅ Canlı doğrulandı (3 kayıt) |
| windows | Çözülen sorunlar: Windows Server 2025 | Release health – çözülen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/resolved-issues-windows-server-2025> | ✅ Canlı doğrulandı (15 kayıt) |
| windows | Güncelleme geçmişi: Windows Server 2025 | Güncelleme geçmişi (KB listesi) | official | kapalı* | <https://support.microsoft.com/en-us/servicing/os/windows-server/2024/10/windows-server-2025-update-history> | ✅ Canlı doğrulandı (5 kayıt) |
| windows | Release health: Windows Server 2022 | Release health – bilinen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/status-windows-server-2022> | ✅ Canlı doğrulandı (3 kayıt) |
| windows | Çözülen sorunlar: Windows Server 2022 | Release health – çözülen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/resolved-issues-windows-server-2022> | ✅ Canlı doğrulandı (12 kayıt) |
| windows | Güncelleme geçmişi: Windows Server 2022 | Güncelleme geçmişi (KB listesi) | official | kapalı* | <https://support.microsoft.com/en-us/servicing/os/windows-server/2021/07/windows-server-2022-update-history> | ✅ Canlı doğrulandı (5 kayıt) |
| windows | Güncelleme geçmişi: Windows Server, sürüm 23H2 | Güncelleme geçmişi (KB listesi) | official | kapalı* | <https://support.microsoft.com/en-us/servicing/os/windows-server/2023/09/windows-server-version-23h2-update-history> | ✅ Canlı doğrulandı (0 kayıt) — Son 4 ayda yayımlanmış KB bağlantısı yok. |
| windows | Release health: Windows Server 2019 / Windows 10 1809 | Release health – bilinen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/status-windows-10-1809-and-windows-server-2019> | ✅ Canlı doğrulandı (3 kayıt) |
| windows | Çözülen sorunlar: Windows Server 2019 / Windows 10 1809 | Release health – çözülen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/resolved-issues-windows-10-1809-and-windows-server-2019> | ✅ Canlı doğrulandı (13 kayıt) |
| windows | Güncelleme geçmişi: Windows Server 2019 / Windows 10 1809 | Güncelleme geçmişi (KB listesi) | official | kapalı* | <https://support.microsoft.com/en-us/servicing/os/windows-10/2020/11/windows-10-and-windows-server-2019-update-history> | ✅ Canlı doğrulandı (5 kayıt) |
| windows | Release health: Windows Server 2016 / Windows 10 1607 | Release health – bilinen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/status-windows-10-1607-and-windows-server-2016> | ✅ Canlı doğrulandı (3 kayıt) |
| windows | Çözülen sorunlar: Windows Server 2016 / Windows 10 1607 | Release health – çözülen sorunlar | official | kapalı* | <https://learn.microsoft.com/en-us/windows/release-health/resolved-issues-windows-10-1607> | ✅ Canlı doğrulandı (11 kayıt) |
| windows | Güncelleme geçmişi: Windows Server 2016 / Windows 10 1607 | Güncelleme geçmişi (KB listesi) | official | kapalı* | <https://support.microsoft.com/en-us/servicing/os/windows-10/2020/11/windows-10-and-windows-server-2016-update-history> | ✅ Canlı doğrulandı (4 kayıt) |
| windows | KB makaleleri (Known issues bölümleri) | KB makaleleri – Known issues bölümü | official | açık | <https://support.microsoft.com/> | ✅ Canlı doğrulandı (10 kayıt) |
| windows | Windows message center | Windows message center | official | açık | <https://learn.microsoft.com/en-us/windows/release-health/windows-message-center> | ✅ Canlı doğrulandı (88 kayıt) |
| intune | Intune: What's new | Intune belgeleri | official | açık | <https://learn.microsoft.com/en-us/intune/whats-new/> | ✅ Canlı doğrulandı (58 kayıt) |
| intune | Intune: In development | Intune belgeleri | official | açık | <https://learn.microsoft.com/en-us/intune/whats-new/in-development> | ✅ Canlı doğrulandı (23 kayıt) |
| intune | Intune: Important notices | Intune belgeleri | official | açık | <https://learn.microsoft.com/en-us/intune/whats-new/#notices> | ✅ Canlı doğrulandı (14 kayıt) |
| configmgr | ConfigMgr: desteklenen sürümler | ConfigMgr desteklenen sürümler | official | açık | <https://learn.microsoft.com/en-us/intune/configmgr/core/servers/manage/updates> | ✅ Canlı doğrulandı (3 kayıt) |
| configmgr | ConfigMgr: hotfix ve update rollup'lar | ConfigMgr hotfix/rollup | official | açık | <https://learn.microsoft.com/en-us/intune/configmgr/hotfix/> | ✅ Canlı doğrulandı (27 kayıt) |
| configmgr | ConfigMgr: sürüm notları (bilinen sorunlar) | ConfigMgr sürüm notları | official | açık | <https://learn.microsoft.com/en-us/intune/configmgr/core/servers/deploy/install/release-notes> | ✅ Canlı doğrulandı (10 kayıt) |
| configmgr | ConfigMgr: Technical Preview | ConfigMgr Technical Preview | official | açık | <https://learn.microsoft.com/en-us/intune/configmgr/core/get-started/technical-preview> | ✅ Canlı doğrulandı (3 kayıt) |
| intune | Intune Customer Success blogu | RSS/Atom beslemesi | official | açık | <https://techcommunity.microsoft.com/t5/s/gxcuf89792/rss/board?board.id=IntuneCustomerSuccess> | ✅ Canlı doğrulandı (2 kayıt) |
| windows | Windows IT Pro blogu | RSS/Atom beslemesi | official | açık | <https://techcommunity.microsoft.com/t5/s/gxcuf89792/rss/board?board.id=Windows-ITPro-blog> | ✅ Canlı doğrulandı (4 kayıt) |
| configmgr | Configuration Manager blogu | RSS/Atom beslemesi | official | açık | <https://techcommunity.microsoft.com/t5/s/gxcuf89792/rss/board?board.id=ConfigurationManagerBlog> | ✅ Canlı doğrulandı (0 kayıt) |
| community | r/sysadmin | Reddit Data API (OAuth) | community | kimlik bilgisiyle açık | <https://www.reddit.com/r/sysadmin/new/> (okuma: `oauth.reddit.com/r/sysadmin/new`) | 🔑 Canlı doğrulanmadı (kimlik bilgisi yok). RSS beslemesi ⛔ robots.txt |
| community | r/Intune | Reddit Data API (OAuth) | community | kimlik bilgisiyle açık | <https://www.reddit.com/r/Intune/new/> (okuma: `oauth.reddit.com/r/Intune/new`) | 🔑 Canlı doğrulanmadı (kimlik bilgisi yok). RSS beslemesi ⛔ robots.txt |
| community | r/SCCM | Reddit Data API (OAuth) | community | kimlik bilgisiyle açık | <https://www.reddit.com/r/SCCM/new/> (okuma: `oauth.reddit.com/r/SCCM/new`) | 🔑 Canlı doğrulanmadı (kimlik bilgisi yok). RSS beslemesi ⛔ robots.txt |
| community | BleepingComputer | RSS/Atom beslemesi | press | açık | <https://www.bleepingcomputer.com/feed/> | ✅ Canlı doğrulandı (1 kayıt) |
| community | Born's Tech and Windows World | RSS/Atom beslemesi | press | açık | <https://borncity.com/win/feed/> | ✅ Canlı doğrulandı (0 kayıt) |
| community | Windows Latest | RSS/Atom beslemesi | press | açık | <https://www.windowslatest.com/feed/> | ✅ Canlı doğrulandı (2 kayıt) |
| community | AskWoody | RSS/Atom beslemesi | press | açık | <https://www.askwoody.com/feed/> | ✅ Canlı doğrulandı (1 kayıt) |
| community | Web araması (yeni raporları keşif) | Web araması | unknown | açık | (yapılandırılabilir) | — Sağlayıcıya bağlı (Brave/SearXNG); yapılandırılmadığı için denenmedi |
| news | Anadolu Ajansı – Güncel | RSS/Atom beslemesi | press | açık | <https://www.aa.com.tr/tr/rss/default?cat=guncel> | ✅ Canlı doğrulandı (30 kayıt) |
| news | NTV – Türkiye | RSS/Atom beslemesi | press | açık | <https://www.ntv.com.tr/turkiye.rss> | ✅ Canlı doğrulandı (20 kayıt) |
| news | BBC Türkçe | RSS/Atom beslemesi | press | açık | <https://feeds.bbci.co.uk/turkce/rss.xml> | ✅ Canlı doğrulandı (16 kayıt) |
| news | DW Türkçe | RSS/Atom beslemesi | press | açık | <https://rss.dw.com/rdf/rss-tur-all> | ✅ Canlı doğrulandı (15 kayıt) |
| news | BBC News – World | RSS/Atom beslemesi | press | açık | <https://feeds.bbci.co.uk/news/world/rss.xml> | ✅ Canlı doğrulandı (32 kayıt) |
| news | Euronews Türkçe | RSS/Atom beslemesi | press | açık | <https://tr.euronews.com/rss> | ✅ Canlı doğrulandı (50 kayıt) |
| news | Webrazzi | RSS/Atom beslemesi | press | kapalı | <https://webrazzi.com/feed/> | ⛔ robots.txt otomatik erişime izin vermiyor; kapalı |
| news | The Verge | RSS/Atom beslemesi | press | açık | <https://www.theverge.com/rss/index.xml> | ✅ Canlı doğrulandı (10 kayıt) |
| news | Ars Technica | RSS/Atom beslemesi | press | açık | <https://feeds.arstechnica.com/arstechnica/index> | ✅ Canlı doğrulandı (20 kayıt) |

## Günlük veri sağlayıcıları

Bu sağlayıcılar kaynak tablosunda değil, `.env` ile yapılandırılır. `bulten kaynak-dogrula` bunları da dener.
Konum seçilmemişse hava tahmini yalnızca bağlantı testi olarak Ankara koordinatıyla denenir; bu, kullanıcının
konumu olarak kaydedilmez.

| Modül | Sağlayıcı | Adres | Doğrulama |
|---|---|---|---|
| Hava durumu | Open-Meteo (tahmin + konum arama) | <https://api.open-meteo.com> | ✅ Canlı doğrulandı (1 kalem) |
| Piyasa | TCMB gösterge kurları (referans) | <https://www.tcmb.gov.tr/kurlar/today.xml> | ✅ Canlı doğrulandı (2 kalem) |
| Piyasa | Truncgil Finans (serbest piyasa: döviz, gram altın, 22 ayar bilezik) | <https://finans.truncgil.com/today.json> | ✅ Canlı doğrulandı (4 kalem) |

## Kaynak seçimine ilişkin notlar

- **Windows release health:** Microsoft'un resmî RSS beslemesi bulunmadığından HTML ayrıştırılır. Microsoft Graph'taki Windows updates API'si (bilinen sorunlar) tenant uygulama izni gerektirir. Graph, daha yapılandırılmış bir alternatif olarak sonraki sürüm için not edildi.
- **Güncelleme geçmişi:** KB listesi sayfanın ana içeriğinde değil, tüm ürün ailesini içeren sol menüdedir. Her ürün kendi menü kategorisinden okunur (ör. 25H2 sayfasının menüsündeki 26H1 ve 23H2 KB'leri alınmaz). support.microsoft.com'un eski `/topic/…` adresleri `/servicing/os/…` adreslerine yönlendirildiği için kanonik adresler kullanılır.
- **KB makaleleri:** Her bilinen sorun ayrı bir `<details>` bloğudur. "Partially resolved" (kısmen çözüldü) ifadesindeki KB tam düzeltme sayılmaz. Microsoft açık sorunu sonraki KB makalelerinde de listeler; bu KB'ler sorunun kaynağı sayılmaz ve aynı olaya bağlanır.
- **Windows Server, sürüm 23H2:** Güncellemeleri Mayıs 2026'da sona erdi ("End of updates statement"); son 4 ayda KB olmaması beklenir.
- **Intune / ConfigMgr:** Learn sayfalarının kaynağı olan açık MicrosoftDocs/memdocs deposu birincil okuma kaynağıdır; iş öğesi kimlikleri böylece korunur. Learn HTML sayfası yedektir. Kullanıcıya her zaman learn.microsoft.com bağlantısı gösterilir.
- **"whats-new-incremental-versions" sayfası** sürüm listesini içermez; "Supported versions" tablosunun bulunduğu *Updates and servicing* sayfasına yönlendirir. Sürüm ve destek sonu bilgisi o sayfadan okunur.
- **Technical Preview:** Microsoft'un belgesine göre son TP sürümü 2411'dir (Kasım 2024). Yeni TP yayımlanırsa aynı sayfadan algılanır.
- **Topluluk sayfaları resmî sayılmaz:** learn.microsoft.com/answers, answers.microsoft.com ve Tech Community tartışmaları "topluluk" olarak sınıflandırılır. Yalnızca resmî blog panoları (Intune Customer Success, Windows IT Pro, Configuration Manager vb.) resmî kabul edilir.
- **Reddit:** robots.txt tüm otomatik erişimi yasaklıyor (`User-agent: *` / `Disallow: /`, 2026-09-26'da kontrol edildi); RSS beslemeleri bu yüzden okunmaz. r/sysadmin, r/Intune ve r/SCCM resmî Reddit Data API ile okunur (`reddit_api` adaptörü):
  - **Kurulum:** Reddit'te <https://www.reddit.com/prefs/apps> adresinden "script" türünde bir uygulama oluşturun (Reddit'in güncel Data API koşullarını ve kayıt sürecini kontrol edin). `.env` dosyasına `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` ve `REDDIT_USER_AGENT` yazın. User-Agent Reddit'in istediği biçimde olmalıdır: `<platform>:<uygulama kimliği>:<sürüm> (by /u/<kullanıcı adı>)`. `REDDIT_USER_AGENT` boşsa `REDDIT_USERNAME` ile bu biçimde oluşturulur. Yeniden başlattığınızda üç kaynak açılır. Kimlik bilgileri kaldırılırsa kapanır; aradaki süreçte kapattığınız kaynak kapalı kalır.
  - **Erişim türü:** Yalnızca uygulama erişimi (client credentials) kullanılır. Reddit parolanız istenmez, hiçbir kullanıcı adına işlem yapılmaz. Token `www.reddit.com/api/v1/access_token` adresinden alınır ve yalnızca bellekte tutulur; veri tabanına veya günlüğe yazılmaz. Gönderiler `oauth.reddit.com/r/<alt forum>/new` adresinden okunur. Bunlar belgelenmiş API çağrıları olduğu için robots.txt'ye değil Reddit'in API koşullarına tabidir.
  - **Hız sınırı:** OAuth istemcisi başına dakikada 100 istek. Her toplama turunda alt forum başına 1–2 istek yapılır. `X-Ratelimit-Remaining` / `X-Ratelimit-Reset` başlıkları izlenir; sınır dolmak üzereyse sıfırlanma zamanına kadar istek yapılmaz. HTTP 429 yanıtı hemen yeniden denenmez.
  - **Filtreleme:** RSS adaptörüyle aynıdır. Yalnızca izlenen kapsamdan (Windows/Intune/ConfigMgr) söz eden ve sorun bildirimi gibi görünen gönderiler "saha raporu" olur. Silinen ve moderatörce kaldırılan gönderiler alınmaz. Güven düzeyi her zaman "topluluk"tur; gönderiler asla Microsoft teyidi sayılmaz.
  - **Dürüst raporlama:** Kimlik bilgileri yoksa kaynak kapalıdır. Elle açılırsa her kontrol "hata" olarak kaydedilir ve bültende kapsam uyarısı çıkar; "yeni sorun yok" diye yorumlanmaz. `bulten kaynak-dogrula --slug reddit-sysadmin` bu durumda `[YAPILANDIRILMADI]` yazar ve hata koduyla çıkar.
  - **Doğrulama durumu:** Adaptör, Reddit API belgelerindeki yapıya göre elle hazırlanmış Listing JSON'u ile test edildi. Geliştirme ortamında Reddit kimlik bilgisi yoktu ve `oauth.reddit.com` ağ politikasıyla engelliydi. Token uç noktasına yapılan gerçek bir istekte geçersiz kimlik bilgisinin açık bir hata (HTTP 401) verdiği görüldü. Gönderi okuma canlı çalıştırılmadı; kurulumdan sonra `bulten kaynak-dogrula --slug reddit-sysadmin` ile doğrulayın.
- **Haberler:** NTV'nin `gundem.rss` adresi kalıcı olarak `turkiye.rss` adresine yönlendiriliyor. Webrazzi `/feed/` yolunu genel ajanlara kapattığı için Türkçe teknoloji haberi için kendi RSS kaynağınızı ekleyebilirsiniz.
- **Hava uyarıları:** MGM MeteoUyarı için belgelenmiş bir API bulunamadı; ayrıntı için bkz. PLAN.md.
- **Piyasa:** TCMB gösterge kuru *referans* kurdur ve piyasa kuruyla karıştırılmaz. Bilezik fiyatı 24 ayardan hesaplanmaz; Truncgil işçilik bilgisi vermediği için "kaynak belirtmiyor" yazılır.
