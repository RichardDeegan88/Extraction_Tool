"""HTTP repository for reading acquisition with SSRF prevention."""

import hashlib
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse


class HttpReadingRepository:
    """Fetches readings from URLs with SSRF prevention.

    Security invariants:
    - _is_public_host() blocks loopback, private, link-local, multicast, reserved IPs
    - _SafeRedirectHandler refuses non-HTTP(S) redirects and private-hosts redirects
    - Invisible/bidi/tag-block character sanitization mirrors preprocess_pdf.py
    """

    _VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com", "ted.com")
    _GATED_MARKERS = (
        "idm.oclc.org",
        "jstor.org",
        "tandfonline.com",
        "sciencedirect.com",
        "springer.com",
        "wiley.com",
        "ebscohost.com",
        "research-ebsco",
        "proquest.com",
        "muse.jhu.edu",
        "academic.oup.com",
    )
    MAX_ARTICLE_SIZE = 10 * 1024 * 1024
    MAX_PDF_SIZE = 100 * 1024 * 1024
    _DOWNLOAD_CHUNK = 64 * 1024
    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    )

    async def get(self, key: str) -> Any:
        """Not used for HTTP repository."""
        raise NotImplementedError("HttpReadingRepository does not support get()")

    async def save(self, key: str, value: Any) -> None:
        """Not used for HTTP repository."""
        raise NotImplementedError("HttpReadingRepository does not support save()")

    async def delete(self, key: str) -> None:
        """Not used for HTTP repository."""
        raise NotImplementedError("HttpReadingRepository does not support delete()")

    async def list_all(self) -> dict[str, Any]:
        """Not used for HTTP repository."""
        raise NotImplementedError("HttpReadingRepository does not support list_all()")

    @staticmethod
    def _is_public_host(host: str) -> tuple[bool, str]:
        """Resolve host and ensure every returned IP is public."""
        if not host:
            return False, "empty host"
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as e:
            return False, f"could not resolve host: {e.strerror or host}"
        except Exception as e:
            return False, f"could not resolve host: {type(e).__name__}: {e}"

        ips = set()
        for info in infos:
            sockaddr = info[4]
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            ips.add(ip)
            if ip.is_loopback:
                return False, f"refused loopback address: {ip}"
            if ip.is_link_local:
                return False, f"refused link-local address: {ip}"
            if ip.is_private:
                return False, f"refused private address: {ip}"
            if ip.is_multicast:
                return False, f"refused multicast address: {ip}"
            if ip.is_reserved:
                return False, f"refused reserved address: {ip}"
        if not ips:
            return False, "host resolved to no usable IP addresses"
        return True, ""

    class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                             headers: Any, newurl: str) -> Any | None:
            scheme = urlparse(newurl).scheme.lower()
            if scheme not in ("http", "https"):
                raise urllib.error.HTTPError(
                    newurl, code,
                    f"refused redirect to non-http(s) URL: {newurl}", headers, fp)
            host = urlparse(newurl).netloc.split(":")[0]
            ok, reason = HttpReadingRepository._is_public_host(host)
            if not ok:
                raise urllib.error.HTTPError(
                    newurl, code, f"refused redirect to private host: {reason}",
                    headers, fp)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    _OPENER = urllib.request.build_opener(_SafeRedirectHandler)

    @staticmethod
    def _header_size_limit(
        resp_headers: dict[str, str], max_size: int
    ) -> tuple[bytes | None, str, str, str | None] | None:
        """Return a size-limit error tuple if Content-Length exceeds max_size."""
        try:
            content_length = int(resp_headers.get("Content-Length", ""))
        except ValueError:
            return None
        if content_length > max_size:
            return (
                None,
                resp_headers.get("Content-Type", ""),
                f"response Content-Length ({content_length}) exceeds "
                f"limit ({max_size})",
                "size_limit",
            )
        return None

    def _read_bounded_body(
        self, resp: Any, max_size: int | None, content_type: str
    ) -> tuple[bytes | None, str, str, str | None]:
        """Read response body, aborting if max_size is exceeded."""
        body = bytearray()
        while True:
            chunk = resp.read(self._DOWNLOAD_CHUNK)
            if not chunk:
                break
            body.extend(chunk)
            if max_size is not None and len(body) > max_size:
                return (
                    None, content_type,
                    f"response body exceeded {max_size} byte limit",
                    "size_limit",
                )
        return bytes(body), content_type, "", None

    def fetch_url(
        self, url: str, timeout: int, max_size: int | None = None
    ) -> tuple[bytes | None, str, str, str | None]:
        """Fetch a URL. Returns (body, content_type, error, size_reason)."""
        scheme = urlparse(url).scheme.lower()
        if scheme not in ("http", "https"):
            return None, "", f"refused non-http(s) URL scheme: {scheme or 'none'}", None

        host = urlparse(url).netloc.split(":")[0]
        ok, reason = self._is_public_host(host)
        if not ok:
            return None, "", reason, None

        req = urllib.request.Request(url, headers={
            "User-Agent": self._UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
            "Accept-Language": "en-GB,en;q=0.9",
        })
        try:
            with self._OPENER.open(req, timeout=timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if max_size is not None:
                    limit = self._header_size_limit(resp.headers, max_size)
                    if limit is not None:
                        return limit
                return self._read_bounded_body(resp, max_size, content_type)
        except urllib.error.HTTPError as e:
            return None, "", f"HTTP {e.code} {e.reason}", None
        except urllib.error.URLError as e:
            return None, "", f"connection failed: {e.reason}", None
        except Exception as e:
            return None, "", f"{type(e).__name__}: {e}", None

    def fetch_rendered_html(self, url: str, timeout: int) -> tuple[str, str]:
        """Render *url* in headless Chrome; return (html, error).

        The SSRF host check runs BEFORE the browser launches so a private host
        is refused without any browser I/O. On any failure the function returns
        ("", error_string) so the caller can fall back or record a manual
        capture. The WebDriver is created inside this method (never at module
        level) to avoid global mutable state and to guarantee the host check
        precedes I/O.
        """
        scheme = urlparse(url).scheme.lower()
        if scheme not in ("http", "https"):
            return "", f"refused non-http(s) URL scheme: {scheme or 'none'}"

        host = urlparse(url).netloc.split(":")[0]
        ok, reason = self._is_public_host(host)
        if not ok:
            return "", reason

        try:
            from selenium import webdriver  # type: ignore[import-not-found]
            from selenium.webdriver.chrome.options import Options  # type: ignore
        except ImportError:
            return "", (
                "selenium is required for browser rendering. "
                "Install it with: pip install selenium"
            )

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(options=options)
        try:
            driver.set_page_load_timeout(timeout)
            driver.get(url)
            return driver.page_source, ""
        except Exception as e:
            return "", f"{type(e).__name__}: {e}"
        finally:
            driver.quit()

    def categorise(self, url: str) -> str:
        """Return one of: 'video', 'pdf', 'gated', 'article'."""
        host = urlparse(url).netloc.lower()
        path = urlparse(url).path.lower()
        if any(host == v or host.endswith("." + v) for v in self._VIDEO_HOSTS):
            return "video"
        if any(g in host for g in self._GATED_MARKERS):
            return "gated"
        if path.endswith(".pdf"):
            return "pdf"
        return "article"

    def safe_filename(self, url: str, max_len: int = 80) -> str:
        """Build a readable, filesystem-safe filename from a URL."""
        parsed = urlparse(url)
        host = parsed.netloc.replace("www.", "")
        slug = parsed.path.strip("/").replace("/", "_") or "index"
        slug = re.sub(r"\.(html?|php|aspx)$", "", slug, flags=re.IGNORECASE)
        name = f"{host}_{slug}"
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
        stem = name[:max_len]
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
        stem = f"{stem}-{digest}" if stem else digest
        return stem

    @staticmethod
    def strip_hidden(s: str) -> str:
        """Strip invisible/bidi/tag-block characters."""
        _ZERO_WIDTH_CODEPOINTS = frozenset({
            0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0x034F, 0x180E,
            0x2061, 0x2062, 0x2063, 0x2064,
        })
        _BIDI_CONTROL_CODEPOINTS = frozenset({
            0x200E, 0x200F, 0x061C, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
            0x2066, 0x2067, 0x2068, 0x2069,
        })
        _INVISIBLE_LETTER_CODEPOINTS = frozenset({0x115F, 0x1160, 0x3164, 0xFFA0})
        _INVISIBLE_CODEPOINTS = (
            _ZERO_WIDTH_CODEPOINTS | _BIDI_CONTROL_CODEPOINTS
            | _INVISIBLE_LETTER_CODEPOINTS
        )
        _TAG_BLOCK_START, _TAG_BLOCK_END = 0xE0000, 0xE007F
        return "".join(
            ch for ch in s
            if ord(ch) not in _INVISIBLE_CODEPOINTS
            and not (_TAG_BLOCK_START <= ord(ch) <= _TAG_BLOCK_END)
        )
