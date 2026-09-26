# Test örnekleri

- `memdocs/`: Microsoft'un açık belge deposu [MicrosoftDocs/memdocs](https://github.com/MicrosoftDocs/memdocs)
  kaynağından (commit 4b5429d, 2026-09-02) alınmış gerçek markdown/YAML dosyalarıdır (CC BY 4.0).
  Intune ve ConfigMgr ayrıştırıcıları bu gerçek içerikle test edilir.
- `ms/`: Windows release health ve support.microsoft.com sayfaları için **elle hazırlanmış** örneklerdir.
  Geliştirme ortamı bu sitelere erişemediğinden gerçek HTML alınamadı; örnekler, bu sayfaların
  bilinen başlık ve tablo kalıplarına (Summary / Originating update / Status / Last updated,
  "…msgdesc" çapaları, "Known issues in this update" bölümü, "Tarih—KBxxxxxxx (OS Build …)" bağlantı
  metinleri) göre yazılmıştır. KB numaraları kurgusaldır (KB59990xx). Canlı sayfaya karşı doğrulama
  için: `bulten kaynak-dogrula`.
