"""External URL metadata only. No downloads, extra requests, HTML rendering or blobs."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

# Shared with the public projection and the browser; HTTPS public DNS names only.
URL_PATTERN = r"^https://(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?::443)?(?:[/?][^\s\\#<>\"']*)?$"


def source_image_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip(" ")
    if len(value) > 2048 or not re.fullmatch(URL_PATTERN, value, re.I):
        return None
    parts = urlsplit(value)
    if parts.hostname.endswith((".localhost", ".local", ".internal", ".invalid", ".test")):
        return None
    if re.search(r"\.svg(?:$|[/?])", parts.path, re.I) or re.search(r"%0[ad]", value, re.I):
        return None
    return value


class _ContentImages(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.hidden = 0
        self.url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "iframe", "object", "template", "noscript"):
            self.hidden += 1
        if tag != "img" or self.hidden or self.url:
            return
        fields = dict(attrs)
        if any((fields.get(name) or "").strip() in ("0", "1") for name in ("width", "height")):
            return
        raw = fields.get("src") or ""
        # Relative paths are resolved against the content provider, not an outbound link.
        self.url = source_image_url(urljoin(self.base_url, raw)) if raw else None

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "iframe", "object", "template", "noscript"):
            self.hidden = max(0, self.hidden - 1)


def first_content_image(html: str, base_url: str) -> str | None:
    parser = _ContentImages(base_url)
    parser.feed(html[:1_000_000])
    return parser.url
