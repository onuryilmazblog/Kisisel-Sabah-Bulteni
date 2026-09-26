"""Kaynak ekleme özelliğinin özel ağlara erişim için kullanılmasını engeller.

Kurallar:
- Yalnızca http/https, kullanıcı adı/parola içeren adres yok.
- Port yalnızca 80/443 (güvenilen operatör uç noktaları hariç).
- Ana bilgisayar adının çözümlendiği TÜM adresler genel (global) olmalı;
  loopback, özel, link-local, CGNAT, multicast, ayrılmış adresler reddedilir.
- Yönlendirmelerin her adımı ve (proxy yoksa) gerçekten bağlanılan IP yeniden kontrol edilir.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

BLOCKED_HOST_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet")


class UnsafeURL(ValueError):
    pass


def ip_is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return bool(
        addr.is_global
        and not addr.is_multicast
        and not addr.is_reserved
        and not addr.is_loopback
        and not addr.is_link_local
        and not addr.is_private
    )


def validate_url_syntax(url: str, *, allow_any_port: bool = False) -> tuple[str, str, int]:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL("Yalnızca http ve https adresleri kabul edilir.")
    if parts.username or parts.password:
        raise UnsafeURL("Adreste kullanıcı adı/parola bulunamaz.")
    host = (parts.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise UnsafeURL("Adreste ana bilgisayar adı yok.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeURL("Geçersiz port.") from exc
    if not allow_any_port and port not in (80, 443):
        raise UnsafeURL("Yalnızca 80 ve 443 portlarına izin verilir.")
    if host == "localhost" or host.endswith(BLOCKED_HOST_SUFFIXES) or "." not in host and not _looks_like_ip(host):
        raise UnsafeURL("Yerel/iç ağ adlarına izin verilmez.")
    if _looks_like_ip(host) and not ip_is_public(host):
        raise UnsafeURL("Özel veya ayrılmış IP adreslerine izin verilmez.")
    return parts.scheme, host, port


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def resolve_public(host: str, port: int) -> list[str]:
    """Ana bilgisayarı çözer; genel olmayan tek bir adres bile varsa reddeder.

    DNS çözülemezse socket.gaierror yükseltir (çağıran karar verir).
    """
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips = sorted({info[4][0] for info in infos})
    if not ips:
        raise UnsafeURL("Adres çözümlenemedi.")
    bad = [ip for ip in ips if not ip_is_public(ip)]
    if bad:
        raise UnsafeURL(f"Adres özel/ayrılmış bir IP'ye çözümleniyor ({bad[0]}).")
    return ips
