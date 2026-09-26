# Test örnekleri

- `memdocs/`: Microsoft'un açık belge deposu [MicrosoftDocs/memdocs](https://github.com/MicrosoftDocs/memdocs)
  kaynağından (commit 4b5429d, 2026-09-02) alınmış gerçek markdown/YAML dosyalarıdır (CC BY 4.0).
  Intune ve ConfigMgr ayrıştırıcıları bu gerçek içerikle test edilir.
- `ms-real/`: learn.microsoft.com (Windows release health) ve support.microsoft.com (güncelleme geçmişi,
  KB makaleleri) sayfalarının **gerçek** HTML'idir; 2026-09-26'da indirildi. Boyutu küçültmek için yalnızca
  ana içerik bırakıldı (script/style/görsel ve öznitelikler kaldırıldı). Güncelleme geçmişi sayfalarında KB
  listesi sol menüde olduğu için menü korundu ve kategori başına ilk birkaç makaleyle sınırlandı; message
  center ilk 12 duyuruyla sınırlı. Her dosyanın başında kaynak adresi ve alınma tarihi yazılıdır. Küçültülmüş
  dosyaların orijinalleriyle aynı ayrıştırma sonucunu verdiği kontrol edildi.
- `geocode-kadikoy.json`: Open-Meteo konum arama API'sinin "Kadıköy" sorgusuna gerçek yanıtı (alanlar kısaltıldı).
- `ms/`: Release health ve support.microsoft.com için **elle hazırlanmış** örneklerdir (KB numaraları kurgusal,
  KB59990xx). Gerçek sayfalardan farklı yapıları (tablo biçimli "Known issues", ana içerikte KB listesi) ve
  kabul testlerindeki kurgusal senaryoları kapsamak için tutuldu.
