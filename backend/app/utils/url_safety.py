"""URL safety validation — SSRF protection for user-submitted crawl targets.

Blocks localhost, loopback, private/reserved IPs (literal or via DNS),
non-http(s) schemes, and credentials in URLs. DNS is resolved at
validation time to defeat DNS-rebinding tricks.
"""
import ipaddress
import socket
from urllib.parse import urlparse


def validate_public_url(url: str) -> str | None:
    """Return an error message if the URL is unsafe to crawl, else None."""
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return "Malformed URL."
    if parsed.scheme not in ("http", "https"):
        return "Only http(s) URLs are allowed."
    if parsed.username or parsed.password:
        return "URLs with embedded credentials are not allowed."
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return "URL has no hostname."
    if host in ("localhost",):
        return "Local addresses are blocked."
    # Literal IP check
    try:
        ip = ipaddress.ip_address(host)
        if (ip.is_private or ip.is_loopback or ip.is_reserved
                or ip.is_link_local or ip.is_multicast or ip.is_unspecified):
            return "Private/internal IP addresses are blocked."
        return None
    except ValueError:
        pass  # hostname, resolve below
    # Block suspicious hostnames outright
    if host.endswith(".local") or host.endswith(".internal") or host.endswith(".lan"):
        return "Internal hostnames are blocked."
    # DNS resolution check: block only when NO public address exists
    # (dual-stack hosts may also return transition/private addresses;
    # blocking those outright breaks legitimate sites).
    try:
        infos = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC,
                                   type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return "Hostname does not resolve."
    except Exception:
        return "Could not verify hostname."
    any_public = False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not (ip.is_private or ip.is_loopback or ip.is_reserved
                or ip.is_link_local or ip.is_multicast or ip.is_unspecified):
            any_public = True
            break
    if not any_public:
        return "Hostname resolves only to private/internal addresses."
    return None
