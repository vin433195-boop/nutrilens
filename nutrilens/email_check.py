"""Kiểm tra email trước khi cho đăng ký: đúng định dạng, tên miền nhận được thư, không phải email dùng một lần.

Đây chỉ là lớp lọc đầu. Bằng chứng chắc chắn email có thật và thuộc về người đăng ký
là việc họ bấm được link xác thực gửi tới hộp thư đó.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# Phần trước @: chữ, số và . _ % + - (không bắt đầu/kết thúc bằng dấu chấm, không có '..')
_LOCAL = r"[A-Za-z0-9_%+\-]+(?:\.[A-Za-z0-9_%+\-]+)*"
# Tên miền: các nhãn chữ/số/gạch nối, đuôi ít nhất 2 chữ cái
_DOMAIN = r"(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}"
EMAIL_RE = re.compile(rf"^{_LOCAL}@{_DOMAIN}$")

# Dịch vụ email tạm thời, dùng một lần rồi bỏ
DISPOSABLE = {
    "mailinator.com", "yopmail.com", "10minutemail.com", "guerrillamail.com", "guerrillamail.net",
    "sharklasers.com", "temp-mail.org", "tempmail.com", "tempmail.net", "temp-mail.io", "tempmailo.com",
    "throwawaymail.com", "trashmail.com", "getnada.com", "nada.email", "maildrop.cc", "dispostable.com",
    "fakeinbox.com", "mintemail.com", "mohmal.com", "emailondeck.com", "mailnesia.com", "moakt.com",
    "spamgourmet.com", "mytemp.email", "tmpmail.org", "tmail.ws", "1secmail.com", "dropmail.me",
    "mail.tm", "mailpoof.com", "burnermail.io", "inboxkitten.com", "trashmail.de", "discard.email",
}

# Lỗi gõ thường gặp ở tên miền phổ biến
TYPOS = {
    "gmial.com": "gmail.com", "gmai.com": "gmail.com", "gmal.com": "gmail.com", "gamil.com": "gmail.com",
    "gmail.co": "gmail.com", "gmail.cm": "gmail.com", "gmail.con": "gmail.com",
    "gmaill.com": "gmail.com", "gnail.com": "gmail.com", "gmail.om": "gmail.com", "gmali.com": "gmail.com",
    "yaho.com": "yahoo.com", "yahooo.com": "yahoo.com", "yahoo.co": "yahoo.com", "yahoo.con": "yahoo.com",
    "hotmial.com": "hotmail.com", "hotmai.com": "hotmail.com", "hotmail.co": "hotmail.com",
    "hotmail.con": "hotmail.com", "outlok.com": "outlook.com", "outllook.com": "outlook.com",
    "outlook.co": "outlook.com", "iclod.com": "icloud.com", "icloud.co": "icloud.com",
}


def suggest(email: str) -> str | None:
    local, _, domain = email.rpartition("@")
    fixed = TYPOS.get(domain.lower())
    return f"{local}@{fixed}" if fixed else None


DOH_URL = "https://dns.google/resolve"


def _doh_accepts_mail(domain: str, timeout: float) -> bool | None:
    """Dự phòng khi DNS thường (cổng 53) bị chặn: hỏi qua DNS-over-HTTPS của Google."""
    import json
    import urllib.parse
    import urllib.request

    def query(rtype: str) -> tuple[int, list]:
        url = f"{DOH_URL}?{urllib.parse.urlencode({'name': domain, 'type': rtype})}"
        with urllib.request.urlopen(url, timeout=timeout) as res:  # noqa: S310 - URL cố định https
            data = json.load(res)
        return data.get("Status", 2), [a for a in data.get("Answer", []) if a.get("type") in (15, 1, 28)]

    try:
        status, answers = query("MX")
        if status == 3:  # NXDOMAIN: tên miền không tồn tại
            return False
        if status != 0:
            return None
        mx = [a["data"].split()[-1].rstrip(".") for a in answers if a["type"] == 15]
        if mx:
            return any(mx)
        for rtype in ("A", "AAAA"):
            status, answers = query(rtype)
            if status == 0 and answers:
                return True
        return False
    except (OSError, ValueError, KeyError):
        log.warning("DoH check for %s failed, skipping", domain)
        return None


def domain_accepts_mail(domain: str, timeout: float = 2.5) -> bool | None:
    """True: có máy chủ nhận thư. False: chắc chắn không có. None: không kiểm tra được (lỗi mạng)."""
    result = _dns_accepts_mail(domain, timeout)
    return result if result is not None else _doh_accepts_mail(domain, timeout)


def _dns_accepts_mail(domain: str, timeout: float) -> bool | None:
    try:
        import dns.exception
        import dns.resolver
    except ImportError:
        return None
    resolver = dns.resolver.Resolver()
    resolver.lifetime = timeout
    try:
        answers = resolver.resolve(domain, "MX")
        # MX "." (null MX, RFC 7505) nghĩa là tên miền tuyên bố không nhận thư
        return any(str(r.exchange).rstrip(".") for r in answers)
    except dns.resolver.NXDOMAIN:
        return False
    except dns.resolver.NoAnswer:
        pass
    except (dns.exception.Timeout, dns.resolver.NoNameservers):
        return None
    # Không có MX: theo chuẩn SMTP, thư vẫn được gửi tới địa chỉ A/AAAA của tên miền
    for rtype in ("A", "AAAA"):
        try:
            resolver.resolve(domain, rtype)
            return True
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            continue
        except (dns.exception.Timeout, dns.resolver.NoNameservers):
            return None
    return False


def check_email(email: str, check_dns: bool = True) -> str | None:
    """Trả về thông báo lỗi tiếng Việt, hoặc None nếu email dùng được."""
    if len(email) > 254 or not EMAIL_RE.match(email):
        return "Địa chỉ email không hợp lệ."
    fixed = suggest(email)
    if fixed:
        return f"Có phải bạn muốn nhập {fixed}? Hãy kiểm tra lại tên miền email."
    domain = email.rpartition("@")[2].lower()
    if domain in DISPOSABLE:
        return "Không dùng được email tạm thời. Hãy dùng email bạn thường sử dụng."
    if check_dns and domain_accepts_mail(domain) is False:
        return f"Tên miền {domain} không nhận được thư. Hãy kiểm tra lại địa chỉ email."
    return None
