"""Security helpers for the public endpoint: rate limiting, URL validation (SSRF
guard), and the real client IP behind Cloudflare. Kept dependency-free."""
import os
import time
import ipaddress
from collections import defaultdict
from urllib.parse import urlparse

# ── config (tunable via env) ──────────────────────────────────────────────────
RATE_PER_MIN = int(os.getenv("RATE_PER_MIN", "6"))
RATE_PER_HOUR = int(os.getenv("RATE_PER_HOUR", "40"))

# Only reels/shorts from these platforms are accepted. This is the SSRF guard:
# an attacker can't make the server fetch internal URLs (169.254.x, localhost, …).
ALLOWED_HOSTS = (
    "instagram.com", "youtube.com", "youtu.be", "m.youtube.com",
    "facebook.com", "fb.watch", "x.com", "twitter.com", "tiktok.com",
)

_req_log = defaultdict(list)   # ip -> [timestamps]


def client_ip(request):
    """Real client IP. Behind Cloudflare it's in CF-Connecting-IP."""
    return (request.headers.get("cf-connecting-ip")
            or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown"))


def rate_ok(ip):
    """Sliding-window limiter: caps requests per IP per minute and per hour."""
    now = time.time()
    hits = [t for t in _req_log[ip] if now - t < 3600]
    if len(_req_log) > 5000:          # keep memory bounded
        _prune(now)
    if sum(1 for t in hits if now - t < 60) >= RATE_PER_MIN:
        _req_log[ip] = hits
        return False
    if len(hits) >= RATE_PER_HOUR:
        _req_log[ip] = hits
        return False
    hits.append(now)
    _req_log[ip] = hits
    return True


def _prune(now):
    for ip in list(_req_log):
        fresh = [t for t in _req_log[ip] if now - t < 3600]
        if fresh:
            _req_log[ip] = fresh
        else:
            del _req_log[ip]


def url_ok(url):
    """Validate the submitted link. Returns (ok, reason)."""
    try:
        p = urlparse(url)
    except Exception:
        return False, "That doesn't look like a valid link."
    if p.scheme not in ("http", "https"):
        return False, "Only http(s) links are supported."
    host = (p.hostname or "").lower()
    if not host:
        return False, "That doesn't look like a valid link."
    # Block raw IPs and internal/loopback addresses (SSRF protection).
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
            return False, "That address isn't allowed."
        return False, "Please paste a reel/short link, not an IP address."
    except ValueError:
        pass
    if host == "localhost" or host.endswith(".local") or host.endswith(".internal"):
        return False, "That address isn't allowed."
    if not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        return False, "Supported links: Instagram, YouTube, Facebook, X, or TikTok."
    return True, ""


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' https: data:; "
        "script-src 'self' 'unsafe-inline' https://snapwidget.com; "
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; frame-src https://snapwidget.com; "
        "base-uri 'self'; frame-ancestors 'self'"
    ),
}
