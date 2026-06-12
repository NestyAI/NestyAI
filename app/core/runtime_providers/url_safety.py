from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


_BLOCKED_HOSTNAMES = {
    "localhost",
    "0.0.0.0",
    "::1",
    "metadata.google.internal",
    "169.254.169.254",
}

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
]


def _is_private_or_blocked_ip(ip_text: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    for network in _BLOCKED_NETWORKS:
        if ip_obj in network:
            return True
    return ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local


def validate_base_url_host(
    url: str,
    *,
    allow_http: bool,
    allow_private: bool,
    resolve_dns: bool = False,
) -> tuple[bool, str | None]:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False, "runtime_provider_invalid: base_url must use http or https"
    if parsed.scheme == "http" and not allow_http:
        return False, "runtime_provider_invalid: http base_url is not allowed"
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "runtime_provider_invalid: base_url hostname is required"
    if hostname in _BLOCKED_HOSTNAMES and not allow_private:
        return False, "runtime_provider_invalid: base_url host is blocked"
    try:
        ipaddress.ip_address(hostname)
        if _is_private_or_blocked_ip(hostname) and not allow_private:
            return False, "runtime_provider_invalid: base_url host is blocked"
    except ValueError:
        pass
    if resolve_dns and not allow_private:
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return False, "runtime_provider_invalid: base_url host could not be resolved"
        for entry in addresses:
            ip_text = entry[4][0]
            if _is_private_or_blocked_ip(ip_text):
                return False, "runtime_provider_invalid: base_url resolves to a blocked address"
    return True, None
