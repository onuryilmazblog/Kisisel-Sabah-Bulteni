"""Takip edilebilir Windows ürünleri ve ilgili Microsoft sayfaları.

`validated` alanı adresin nasıl doğrulandığını kaydeder. Geliştirme ortamı
Microsoft sitelerine doğrudan erişemediği için doğrulama arama motoru dizini
üzerinden yapıldı (2026-09-26); canlı kontrol için `bulten kaynak-dogrula`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

WRH_BASE = "https://learn.microsoft.com/en-us/windows/release-health/"


@dataclass(frozen=True)
class Product:
    id: str
    label: str
    family: str                      # client|server
    builds: tuple[str, ...]          # ana build numaraları (metinden ürün çıkarımı için)
    wrh_status: str | None           # release health durum sayfası (slug)
    wrh_resolved: str | None
    update_history: str | None
    aliases: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""


PRODUCTS: list[Product] = [
    Product("win11-26h1", "Windows 11, sürüm 26H1", "client", ("28000",),
            "status-windows-11-26h1", "resolved-issues-windows-11-26H1",
            "https://support.microsoft.com/en-us/topic/windows-11-version-26h1-update-history-253c73cd-cab1-4bfd-94dc-76c452273fc9",
            ("26h1",)),
    Product("win11-25h2", "Windows 11, sürüm 25H2", "client", ("26200",),
            "status-windows-11-25h2", "resolved-issues-windows-11-25h2",
            "https://support.microsoft.com/en-us/topic/windows-11-version-25h2-update-history-99c7f493-df2a-4832-bd2d-6706baa0dec0",
            ("25h2",)),
    Product("win11-24h2", "Windows 11, sürüm 24H2", "client", ("26100",),
            "status-windows-11-24h2", "resolved-issues-windows-11-24h2",
            "https://support.microsoft.com/en-us/topic/windows-11-version-24h2-update-history-0929c747-1815-4543-8461-0160d16f15e5",
            ("24h2",)),
    Product("win11-23h2", "Windows 11, sürüm 23H2", "client", ("22631", "22621"),
            "status-windows-11-23h2", "resolved-issues-windows-11-23h2",
            "https://support.microsoft.com/en-us/topic/windows-11-version-23h2-update-history-59875222-b990-4bd9-932f-91a5954de434",
            ("23h2",), "Home/Pro desteği sona erdi; Enterprise/Education için kontrol edin."),
    Product("win10-22h2", "Windows 10, sürüm 22H2 (ESU)", "client", ("19045",),
            "status-windows-10-22h2", "resolved-issues-windows-10-22h2",
            "https://support.microsoft.com/en-us/servicing/os/windows-10/2022/09/windows-10-update-history",
            ("windows 10 22h2", "19045")),
    Product("win10-ltsc2021", "Windows 10 Enterprise LTSC 2021", "client", ("19044",),
            "status-windows-10-21h2", "resolved-issues-windows-10-21h2",
            "https://support.microsoft.com/en-us/servicing/os/windows-10/2022/09/windows-10-update-history",
            ("ltsc 2021", "21h2")),
    Product("ws2025", "Windows Server 2025", "server", ("26100",),
            "status-windows-server-2025", "resolved-issues-windows-server-2025",
            "https://support.microsoft.com/en-us/topic/windows-server-2025-update-history-10f58da7-e57b-4a9d-9c16-9f1dcd72d7d7",
            ("server 2025",)),
    Product("ws2022", "Windows Server 2022", "server", ("20348",),
            "status-windows-server-2022", "resolved-issues-windows-server-2022",
            "https://support.microsoft.com/en-us/servicing/os/windows-server/2021/07/windows-server-2022-update-history",
            ("server 2022",)),
    Product("ws23h2", "Windows Server, sürüm 23H2", "server", ("25398",),
            None, None,
            "https://support.microsoft.com/en-us/servicing/os/windows-server/2023/09/windows-server-version-23h2-update-history",
            ("server 23h2", "server, version 23h2")),
    Product("ws2019", "Windows Server 2019 / Windows 10 1809", "server", ("17763",),
            "status-windows-10-1809-and-windows-server-2019",
            "resolved-issues-windows-10-1809-and-windows-server-2019",
            "https://support.microsoft.com/en-us/topic/windows-10-and-windows-server-2019-update-history-725fc2e1-4443-6831-a5ca-51ff5cbcb059",
            ("server 2019", "1809")),
    Product("ws2016", "Windows Server 2016 / Windows 10 1607", "server", ("14393",),
            "status-windows-10-1607-and-windows-server-2016", "resolved-issues-windows-10-1607",
            "https://support.microsoft.com/en-us/servicing/os/windows-10/2020/11/windows-10-and-windows-server-2016-update-history",
            ("server 2016", "1607")),
]

PRODUCT_BY_ID = {p.id: p for p in PRODUCTS}

# Build → ürünler (aynı build birden çok ürüne ait olabilir: 26100 = 24H2 ve Server 2025).
BUILD_TO_PRODUCTS: dict[str, list[str]] = {}
for _p in PRODUCTS:
    for _b in _p.builds:
        BUILD_TO_PRODUCTS.setdefault(_b, []).append(_p.id)


# Kullanıcının ortamındaki roller: risk ve "Beni neden ilgilendiriyor?" için kullanılır.
ROLES = {
    "dc": "Etki alanı denetleyicisi (AD DS)",
    "rds": "Uzak Masaüstü Hizmetleri (RDS/RDP)",
    "hyperv": "Hyper-V / küme",
    "wsus": "WSUS / güncelleme dağıtımı",
    "print": "Yazdırma sunucusu",
    "vpn": "VPN / RRAS / Always On VPN",
    "iis": "IIS / web sunucusu",
    "fileserver": "Dosya sunucusu (SMB/DFS)",
    "adcs": "Sertifika hizmetleri (AD CS)",
    "sql": "SQL Server",
    "avd": "Azure Virtual Desktop / FSLogix",
    "bitlocker": "BitLocker kullanan istemciler",
    "autopilot": "Windows Autopilot",
    "comanagement": "Co-management (ConfigMgr + Intune)",
}

INTUNE_PLATFORMS = {
    "windows": "Windows",
    "ios": "iOS/iPadOS",
    "macos": "macOS",
    "android": "Android",
    "linux": "Linux",
}

CONFIGMGR_VERSIONS = ["2603", "2509", "2503", "2409", "2403"]

NEWS_CATEGORIES = {
    "turkiye": "Türkiye",
    "dunya": "Dünya",
    "genel": "Genel",
    "teknoloji": "Teknoloji",
}


def wrh_url(slug: str | None) -> str | None:
    return WRH_BASE + slug if slug else None
