# Gerekli servisler ve maliyet kalemleri

Fiyatlar değişebilir. Aşağıdaki tahminler Eylül 2026 itibarıyla bilinen liste fiyatlarına ve varsayılan
ayarlara dayanır. Kendi kullanımınızı **Sistem durumu** sayfasındaki günlük kullanım tablosundan izleyin.

## Zorunlu

| Kalem | Seçenek | Tahmini maliyet |
|---|---|---|
| Sürekli açık bir makine | Küçük bir VPS (1 vCPU, 1–2 GB RAM) veya mevcut ev sunucusu/NAS | VPS için aylık yaklaşık 4–8 € / ev sunucusunda ek maliyet yok |
| Telegram botu | @BotFather | Ücretsiz |

## İsteğe bağlı

| Kalem | Seçenek | Tahmini maliyet |
|---|---|---|
| Alan adı + HTTPS | Herhangi bir kayıt firması + Caddy (Let's Encrypt) | Alan adı yıllık ~10–15 €; sertifika ücretsiz |
| LLM özetleri | Anthropic Claude (varsayılan `claude-opus-5`) | Aşağıdaki tabloya bakın |
| E-posta | Mevcut e-posta hesabınızın SMTP'si veya bir işlem e-postası servisi | Genellikle ücretsiz katman yeterli |
| Web araması | Brave Search API veya kendi SearXNG örneğiniz | Brave: güncel planı kontrol edin; SearXNG: sunucunuzda ücretsiz |
| Hava durumu | Open-Meteo | Ticari olmayan kişisel kullanımda ücretsiz (günlük çağrı sınırı içinde) |
| Piyasa | TCMB (referans, ücretsiz), Truncgil Finans (ücretsiz, resmî değil) veya kendi kaynağınız | Ücretsiz / kaynağa bağlı |
| Takvim | Google/Outlook "gizli ICS" bağlantısı | Ücretsiz |

## LLM maliyet tahmini

Varsayım: günde ~25 özet çağrısı; her çağrı ~2.500 giriş ve ~700 çıkış tokeni. Düşünme tokenleri çıkışa
dahil sayıldı ve `LLM_EFFORT=medium` kabul edildi. Buna, diller arası haber eşleştirmesi için günde 1–3
toplu başlık çağrısı eklenir; bu kalem küçüktür.

| Model | Fiyat (1M token, giriş/çıkış) | Günlük | Aylık (~30 gün) |
|---|---|---|---|
| `claude-opus-5` (varsayılan) | $5 / $25 | ~$0,75 | ~$22 |
| `claude-sonnet-5` | $2 / $10 | ~$0,30 | ~$9 |
| `claude-haiku-4-5` | $1 / $5 | ~$0,15 | ~$4,5 |

- Model seçimi sizin kararınızdır: `.env` dosyasında `LLM_MODEL` değerini ayarlayın ve maliyet tahmininin
  doğru olması için `LLM_PRICE_IN_PER_MTOK` / `LLM_PRICE_OUT_PER_MTOK` değerlerini seçtiğiniz modele göre
  güncelleyin.
- **Bütçe koruması:** `LLM_DAILY_BUDGET_USD` (varsayılan $1) ve `LLM_MAX_CALLS_PER_DAY` (varsayılan 60)
  aşılırsa özetler o gün şablona düşer ve "AI özeti yok — günlük bütçe doldu" diye etiketlenir.
- Aynı kanıt için tekrar çağrı yapılmaz (`llm_cache`).
- İlk taramadaki arşiv kayıtları için LLM yalnızca başlangıç özetine girecek yüksek/kritik
  sorunlarda kullanılır.
- LLM hiç kullanılmazsa uygulama tam çalışır. Özetler kaynak metinden şablonla üretilir (başlıklar özgün
  dilde kalır).
