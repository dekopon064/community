"""HTML을 실행 불가능한 plain text로 바꾼다. 원문 HTML은 보관하지 않는다."""

from __future__ import annotations

import html
import re

_SCRIPT_RE = re.compile(
    r"<(script|style|iframe|object|embed)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_HREF_RE = re.compile(
    r"""href\s*=\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
_ON_ATTR_RE = re.compile(r"\son[a-z]+\s*=\s*('[^']*'|\"[^\"]*\")", re.IGNORECASE)
_HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_HANGUL_OR_ALNUM_RE = re.compile(r"[0-9A-Za-z가-힣]")


def extract_http_urls(raw_html: str) -> tuple[str, ...]:
    urls: list[str] = []
    for match in _HREF_RE.finditer(raw_html or ""):
        candidate = html.unescape(match.group(1)).strip()
        if _HTTP_URL_RE.match(candidate) and len(candidate) <= 2048:
            urls.append(candidate)
    return tuple(dict.fromkeys(urls))


def html_to_plain_text(raw_html: object) -> str:
    if raw_html is None:
        return ""
    text = str(raw_html)
    text = _SCRIPT_RE.sub(" ", text)
    text = _ON_ATTR_RE.sub("", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def is_http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(_HTTP_URL_RE.match(text)) and 1 <= len(text) <= 2048


def body_is_usable(plain_text: str, *, min_len: int = 10) -> bool:
    stripped = (plain_text or "").strip()
    if len(stripped) < min_len:
        return False
    return _HANGUL_OR_ALNUM_RE.search(stripped) is not None
