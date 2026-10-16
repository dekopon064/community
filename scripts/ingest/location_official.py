"""Bounded, credential-free reads of public Korean government HTML only."""
from __future__ import annotations

from html.parser import HTMLParser
import http.client
import ipaddress
import re
import socket
import ssl
from urllib.parse import urlsplit

MAX_PAGE_BYTES = 512_000


class OfficialReadError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def official_url(value):
    try:
        if not isinstance(value, str) or len(value) > 2048 or value != value.strip() or re.search(r'[\s\\\x00-\x1f]', value):
            raise ValueError()
        u = urlsplit(value)
        if (u.scheme != 'https' or u.username or u.password or u.port is not None or
                not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)*\.go\.kr', u.hostname or '') or
                re.search(r'(?:token|secret|api[_-]?key|authorization|password|code)=', u.query, re.I)):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise OfficialReadError('official_url_invalid') from None


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1
        if tag in {'p', 'div', 'li', 'tr', 'td', 'br', 'h1', 'h2', 'h3'} and not self.hidden:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.hidden = max(0, self.hidden-1)
        if tag in {'p', 'div', 'li', 'tr', 'td'} and not self.hidden:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def page_text(body, content_type):
    if not isinstance(body, bytes) or len(body) > MAX_PAGE_BYTES:
        raise OfficialReadError('official_page_unverified')
    if not re.match(r'^text/(?:html|plain)(?:;|$)', content_type, re.I):
        raise OfficialReadError('official_page_unverified')
    charset = re.search(r'charset\s*=\s*["\']?([\w-]+)', content_type, re.I)
    encoding = charset.group(1).lower() if charset else 'utf-8'
    if encoding not in {'utf-8', 'utf8', 'euc-kr', 'cp949'}:
        raise OfficialReadError('official_page_unverified')
    try:
        decoded = body.decode(encoding, errors='strict')
        if content_type.lower().startswith('text/plain'):
            return decoded
        parser = PlainText()
        parser.feed(decoded)
        return ''.join(parser.parts)
    except (UnicodeError, ValueError):
        raise OfficialReadError('official_page_unverified') from None


class PublicHTTPS(http.client.HTTPSConnection):
    def connect(self):
        # Resolve once, reject any non-public answer, pin the connected IP, and
        # validate TLS against the original government hostname. No proxy/cookies.
        candidates = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
        ips = [row[4][0] for row in candidates]
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise OfficialReadError('official_url_invalid')
        raw = socket.create_connection((ips[0], 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def read_official_page(url, *, connection_factory=PublicHTTPS):
    u = urlsplit(official_url(url))
    connection = connection_factory(u.hostname, timeout=15, context=ssl.create_default_context())
    try:
        connection.request('GET', (u.path or '/') + ('?' + u.query if u.query else ''), headers={
            'User-Agent': 'Machimoa-location-review/1.0', 'Accept': 'text/html,text/plain', 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        if response.status != 200:
            raise OfficialReadError('official_read_unavailable' if response.status >= 500 else 'official_page_unverified')
        declared = response.getheader('Content-Length')
        if declared and (not declared.isdigit() or int(declared) > MAX_PAGE_BYTES):
            raise OfficialReadError('official_page_unverified')
        if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
            raise OfficialReadError('official_page_unverified')
        return page_text(response.read(MAX_PAGE_BYTES+1), response.getheader('Content-Type', ''))
    except OfficialReadError:
        raise
    except Exception:
        raise OfficialReadError('official_read_unavailable') from None
    finally:
        connection.close()
