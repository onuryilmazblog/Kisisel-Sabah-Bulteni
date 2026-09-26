"""Metin normalleştirme, KB/build/ürün çıkarımı, belirti etiketleri ve benzerlik.

Türkçe ve İngilizce metinler için dil bağımsız çalışacak şekilde tasarlandı:
- Türkçe büyük/küçük harf kuralları (I/ı, İ/i) ve aksan katlama,
- 5 karakterlik önek kökleme (Türkçe bilgi erişiminde yaygın, İngilizcede de yeterli),
- belirti etiketleri için İngilizce + Türkçe anahtar kelime sözlüğü.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from .catalog import BUILD_TO_PRODUCTS

_TR_UPPER = str.maketrans({"I": "ı", "İ": "i"})
_FOLD = str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c", "â": "a", "î": "i", "û": "u"})

STOPWORDS = set(
    """
    a an the and or of to in on for with without after before during is are was were be been being
    might may can could will would should some any all this that these those it its as at by from
    into about over under than then when where which who whom what how not no yes via per also
    more most less new now still only other such there their they them we you your our
    ve ile bir bu su da de ki icin gibi daha cok en ne mi mu olarak olan sonra once gore kadar ama
    fakat veya ya hem her tum bazi yeni son dedi oldu etti ise ile uzerine hakkinda icinde
    """.split()
)

# Teknik olay eşleştirmede ayırt edici olmayan (her kayıtta geçen) kelimeler.
DOMAIN_NOISE = set(
    """
    windows microsoft update updates updated updating install installed installing installation
    device devices user users experience experiencing issue issues problem problems known
    affected affect affects might occur occurs security preview release released version versions
    build builds kb os client server servers system systems customers organizations environment
    environments sorun sorunu sorunlar guncelleme guncellemesi guncellemeler cihaz cihazlar kullanici
    kullanicilar sistem hata yuklendikten yukledikten sonrasinda bazi
    """.split()
)

KB_RE = re.compile(r"\bKB\s?(\d{6,8})\b", re.I)
BUILD_RE = re.compile(r"\b(1\d{4}|2\d{4})\.(\d{2,5})\b")
CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)


def tr_lower(text: str) -> str:
    return (text or "").translate(_TR_UPPER).lower()


def fold(text: str) -> str:
    t = tr_lower(text).translate(_FOLD)
    t = unicodedata.normalize("NFKD", t)
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def norm_space(text: str) -> str:
    return " ".join((text or "").split())


def tokens(text: str, *, stem: int = 5, noise: set[str] | None = None) -> list[str]:
    out = []
    for tok in re.findall(r"[a-z0-9]+", fold(text)):
        if tok in STOPWORDS or (noise and tok in noise):
            continue
        if tok.isdigit():
            if len(tok) >= 3:
                out.append(tok)
            continue
        if len(tok) < 2:
            continue
        out.append(tok[:stem] if stem and len(tok) > stem else tok)
    return out


def token_set(text: str, *, noise: set[str] | None = None) -> frozenset[str]:
    return frozenset(tokens(text, noise=noise))


def jaccard(a: frozenset[str] | set[str], b: frozenset[str] | set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(a: frozenset[str] | set[str], b: frozenset[str] | set[str]) -> float:
    """Küçük kümenin büyük küme içinde kalma oranı."""
    if not a or not b:
        return 0.0
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    return len(small & big) / len(small)


def title_similarity(a: str, b: str, *, technical: bool = False) -> float:
    noise = DOMAIN_NOISE if technical else None
    ta, tb = token_set(a, noise=noise), token_set(b, noise=noise)
    return max(jaccard(ta, tb), 0.85 * containment(ta, tb) if min(len(ta), len(tb)) >= 3 else 0.0)


def shingles(text: str, k: int = 5) -> frozenset[str]:
    toks = tokens(text, stem=0)
    if len(toks) < k:
        return frozenset([" ".join(toks)]) if toks else frozenset()
    return frozenset(" ".join(toks[i:i + k]) for i in range(len(toks) - k + 1))


def near_duplicate_text(a: str, b: str, threshold: float = 0.6) -> bool:
    """Aynı haberin kopyası mı (sendikasyon)? Bağımsız kaynak sayımında kullanılır."""
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return False
    return jaccard(sa, sb) >= threshold or containment(sa, sb) >= 0.8


def extract_kbs(text: str) -> list[str]:
    return sorted({m.group(1) for m in KB_RE.finditer(text or "")})


def extract_builds(text: str) -> list[str]:
    return sorted({f"{m.group(1)}.{m.group(2)}" for m in BUILD_RE.finditer(text or "")
                   if m.group(1) in BUILD_TO_PRODUCTS})


def extract_cves(text: str) -> list[str]:
    return sorted({m.group(0).upper() for m in CVE_RE.finditer(text or "")})


_PRODUCT_PATTERNS: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"windows 11,?\s*(?:version\s*|sürüm\s*)?26h1", re.I), ["win11-26h1"]),
    (re.compile(r"windows 11,?\s*(?:version\s*|sürüm\s*)?25h2", re.I), ["win11-25h2"]),
    (re.compile(r"windows 11,?\s*(?:version\s*|sürüm\s*)?24h2", re.I), ["win11-24h2"]),
    (re.compile(r"windows 11,?\s*(?:version\s*|sürüm\s*)?(?:23h2|22h2)", re.I), ["win11-23h2"]),
    (re.compile(r"windows 10,?\s*(?:version\s*|sürüm\s*)?22h2", re.I), ["win10-22h2"]),
    (re.compile(r"windows 10 enterprise ltsc 2021|windows 10,?\s*(?:version\s*)?21h2", re.I), ["win10-ltsc2021"]),
    (re.compile(r"windows server 2025", re.I), ["ws2025"]),
    (re.compile(r"windows server 2022", re.I), ["ws2022"]),
    (re.compile(r"windows server,?\s*(?:version\s*)?23h2", re.I), ["ws23h2"]),
    (re.compile(r"windows server 2019|windows 10,?\s*(?:version\s*)?1809", re.I), ["ws2019"]),
    (re.compile(r"windows server 2016|windows 10,?\s*(?:version\s*)?1607", re.I), ["ws2016"]),
    (re.compile(r"microsoft server operating system,?\s*(?:version\s*)?24h2", re.I), ["ws2025"]),
]


def extract_products(text: str) -> list[str]:
    found: set[str] = set()
    for pat, ids in _PRODUCT_PATTERNS:
        if pat.search(text or ""):
            found.update(ids)
    for b in extract_builds(text):
        major = b.split(".")[0]
        # 26100 hem 24H2 hem Server 2025; metin açıkça belirtmediyse ikisini de ekle.
        found.update(BUILD_TO_PRODUCTS.get(major, []))
    return sorted(found)


# Belirti / etki etiketleri: (etiket, [anahtar kelimeler]) — katlanmış (fold) biçimde aranır.
SYMPTOM_TAGS: dict[str, list[str]] = {
    "rds": ["remote desktop", "rdp", "rds ", "rd gateway", "remoteapp", "session host", "terminal server",
            "uzak masaustu", "remote desktop services"],
    "dc": ["domain controller", "active directory", "ad ds", "lsass", "etki alani denetleyicisi",
           "domain controllers", "dcpromo", "netlogon"],
    "auth": ["kerberos", "ntlm", "authentication", "sign in", "sign-in", "signin", "logon", "log on",
             "credential guard", "secure channel", "smart card", "windows hello", "kimlik dogrulama",
             "oturum ac", "giris yapam", "credentials", "password"],
    "vpn": ["vpn", "always on vpn", "rras", "l2tp", "ikev2", "sstp", "directaccess"],
    "bitlocker": ["bitlocker", "recovery key", "kurtarma anahtar", "recovery screen"],
    "boot": ["boot", "startup", "start up", "fails to start", "blue screen", "bsod", "bugcheck", "stop error",
             "restart loop", "boot loop", "secure boot", "uefi", "acilis", "mavi ekran", "baslatilamiyor",
             "inaccessible_boot_device", "winre", "recovery environment", "desktop loading", "black screen"],
    "network": ["network", "networking", "wi-fi", "wifi", "ethernet", "dns", "dhcp", "smb", "tcp/ip",
                "internet connection", "wlan", "802.1x", "network adapter", "ag baglanti", "internet baglanti",
                "firewall", "proxy"],
    "update_install": ["fails to install", "failed to install", "install fail", "0x800f", "0x8007",
                       "installation failure", "update rolls back", "rolled back", "undoing changes",
                       "yuklenemiyor", "kurulum basarisiz",
                       "wsus", "windows update fails"],
    "printing": ["printer", "printing", "print spooler", "spooler", "yazici"],
    "hyperv": ["hyper-v", "virtual machine", "failover cluster", "cluster", "live migration", "vm "],
    "avd": ["azure virtual desktop", "fslogix", "avd", "windows 365", "cloud pc"],
    "performance": ["performance", "slow", "high cpu", "memory leak", "freeze", "hang", "unresponsive",
                    "yavas", "donma", "takil"],
    "audio": ["audio", "sound", "speaker", "microphone", "ses "],
    "display": ["display driver", "external display", "external monitor", "multiple monitors", "graphics driver",
                "gpu", "screen flicker", "flickering"],
    "storage": ["disk", "storage", "file system", "ntfs", "refs", "file explorer", "dosya gezgini"],
    "security": ["zero-day", "zero day", "exploited", "actively exploited", "security feature bypass",
                 "sifir gun", "istismar"],
    "configmgr": ["configmgr", "configuration manager", "sccm", "mecm", "software center", "ccmsetup",
                  "task sequence", "management point", "distribution point"],
    "intune": ["intune", "mdm enrollment", "company portal", "autopilot", "compliance policy"],
    "gpo": ["group policy", "gpo", "grup ilkesi"],
    "iis": ["iis ", "internet information services"],
    "adcs": ["certificate services", "ad cs", "certificate authority", "pki"],
    "apps": ["outlook", "office", "teams", "edge", "app crash", "application crash", "uygulama cok"],
}

HIGH_IMPACT_TAGS = {"rds", "dc", "auth", "vpn", "bitlocker", "network", "boot"}
# Birçok farklı sorunda ortak geçen geniş etiketler: tek başına ortak olmaları aynı sorun demek değildir.
BROAD_TAGS = {"auth", "network", "storage"}
# Genel/zayıf etiketler: iki olayı birbirinden ayırmak için tek başına yeterli değil.
WEAK_TAGS = {"update_install", "performance", "apps", "security"}

ROLE_TO_TAGS = {
    "dc": {"dc", "auth"},
    "rds": {"rds"},
    "hyperv": {"hyperv"},
    "wsus": {"update_install"},
    "print": {"printing"},
    "vpn": {"vpn"},
    "iis": {"iis"},
    "fileserver": {"storage", "network"},
    "adcs": {"adcs", "auth"},
    "avd": {"avd", "rds"},
    "bitlocker": {"bitlocker"},
    "autopilot": {"intune"},
    "comanagement": {"configmgr", "intune"},
}

TAG_LABELS_TR = {
    "rds": "Uzak Masaüstü (RDS/RDP)", "dc": "Etki alanı denetleyicisi", "auth": "Kimlik doğrulama",
    "vpn": "VPN", "bitlocker": "BitLocker", "boot": "Açılış/başlatma", "network": "Ağ",
    "update_install": "Güncelleme kurulumu", "printing": "Yazdırma", "hyperv": "Hyper-V/küme",
    "avd": "AVD/FSLogix", "performance": "Performans", "audio": "Ses", "display": "Görüntü",
    "storage": "Depolama/dosya", "security": "Güvenlik (istismar)", "configmgr": "ConfigMgr",
    "intune": "Intune", "gpo": "Grup İlkesi", "iis": "IIS", "adcs": "Sertifika hizmetleri", "apps": "Uygulamalar",
}


@lru_cache(maxsize=4096)
def _folded_padded(text: str) -> str:
    return " " + re.sub(r"\s+", " ", fold(text)) + " "


def symptom_tags(text: str) -> list[str]:
    t = _folded_padded(text or "")
    found = []
    for tag, keys in SYMPTOM_TAGS.items():
        for k in keys:
            kf = fold(k)
            if len(kf.strip()) <= 4:
                # kısa anahtarlar (rdp, vpn, dns, smb...) kelime sınırında aranır
                if re.search(r"(?<![a-z0-9])" + re.escape(kf.strip()) + r"(?![a-z0-9])", t):
                    found.append(tag)
                    break
            elif kf in t:
                found.append(tag)
                break
    return found


def specific_tags(tags: list[str] | set[str]) -> set[str]:
    return set(tags) - WEAK_TAGS


def first_sentences(text: str, n: int = 2, max_chars: int = 420) -> str:
    t = norm_space(text)
    if not t:
        return ""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ0-9\"'(])", t)
    out = " ".join(parts[:n]).strip()
    if len(out) > max_chars:
        out = out[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return out


def truncate(text: str, n: int) -> str:
    t = norm_space(text)
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "…"


ISSUE_WORDS_EN = ["issue", "bug", "broke", "broken", "breaks", "fail", "fails", "failing", "failure", "error",
                  "crash", "crashes", "problem", "not working", "stopped working", "can't", "cannot", "unable",
                  "bsod", "blue screen", "boot loop", "regression", "workaround", "pulled", "known issue"]
ISSUE_WORDS_TR = ["sorun", "hata", "cokme", "coktu", "calismiyor", "bozuldu", "acilmiyor", "basarisiz",
                  "mavi ekran", "gecici cozum"]


def looks_like_issue_report(text: str) -> bool:
    t = _folded_padded(text or "")
    return any(fold(w) in t for w in ISSUE_WORDS_EN + ISSUE_WORDS_TR)


def mentions_tracked_scope(text: str) -> bool:
    t = _folded_padded(text or "")
    keys = ["windows", "server 20", "intune", "configmgr", "configuration manager", "sccm", "mecm", "autopilot",
            "patch tuesday", "cumulative update", " kb5", " kb4"]
    return any(k in t for k in keys)
