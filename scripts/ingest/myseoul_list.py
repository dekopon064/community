"""Public POST/HTML list adapter observed on 2026-10-03; no cookies/JS execution.

Only the declared PrgmListPage.js -> comUtil.submitHtml request is supported.
Each list read is one request, with no document/script/bootstrap fetch or retry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

from ingest.connectors.myseoul_program import (
    DETAIL_PATH, HOST, MySeoulContractError, _Tree, detail_identity, visible_nodes,
)
from ingest.http_client import HttpBudgetExhausted, HttpRequestFailed, HttpStatusError, ResponseTooLarge

LIST_URL = f"https://{HOST}/hmpg/ecpr/prgm/prgmListPage.do"
LIST_DATA_URL = f"https://{HOST}/hmpg/ecpr/prgm/prgmListPgng.do"
_TOTAL = re.compile(r"\s*\$\(['\"]#totalCnt['\"]\)\.text\(['\"]([0-9]{1,6})['\"]\);?\s*\Z")
_DETAIL = re.compile(r"\s*goPrgmDetail\(\s*['\"]([A-Fa-f0-9]{32})['\"]\s*,\s*['\"]([A-Fa-f0-9]{32})['\"]\s*\)\s*;?\s*(?:return\s+false\s*;?)?\s*\Z")


@dataclass(frozen=True)
class ListPage:
    """Validated internal result; not the site's HTML response schema."""
    page: int
    total: int
    items: list[dict]
    complete: bool
    page_size: int = 10


def list_parameters(page: int, page_size: int = 10) -> dict[str, str]:
    if type(page) is not int or page not in (1, 2) or type(page_size) is not int or page_size != 10:
        raise ValueError("myseoul_list_request_invalid")
    return {"miv_pageNo": str(page), "miv_pageSize": "10", "prgrm_se_cd": "",
            "cntr_no": "", "prgrm_nm": "", "rcpt_stadt": "", "rcpt_enddt": "",
            "aply_mthd_cds": "", "free_yn_cds": ""}


def parse_list_html(html: str, page: int, page_size: int = 10) -> ListPage:
    list_parameters(page, page_size)
    if not isinstance(html, str) or len(html.encode("utf-8")) > 1_000_000:
        raise ValueError("myseoul_list_html_invalid")
    parser = _Tree()
    parser.feed(html)
    parser.close()
    root = parser.root
    if parser.current is not root:
        raise ValueError("myseoul_list_incomplete")
    scripts = [n for n in root.children if not isinstance(n, str) and n.tag == "script"]
    if len(scripts) != 1 or scripts[0].attrs:
        raise ValueError("myseoul_list_total_missing")
    match = _TOTAL.fullmatch("".join(c for c in scripts[0].children if isinstance(c, str)))
    if match is None or int(match[1]) > 100000:
        raise ValueError("myseoul_list_total_invalid")
    total = int(match[1])
    scopes = [n for n in visible_nodes(root) if n.tag == "div" and n.has_class("counseling-list")]
    if len(scopes) != 1 or scopes[0].parent is not root:
        raise ValueError("myseoul_list_template_invalid")
    scope = scopes[0]
    cards = [n for n in visible_nodes(scope) if n.tag == "a" and n.has_class("item")]
    expected = min(page_size, max(0, total - (page - 1) * page_size))
    handlers = [n for n in visible_nodes(root) if "goPrgmDetail" in n.attrs.get("onclick", "")]
    if len(cards) != expected or handlers != cards or any(n.parent is not scope for n in cards):
        raise ValueError("myseoul_list_incomplete")
    paging = [n for n in root.children if not isinstance(n, str) and n.has_class("paging")]
    # PC/mobile pagination independently echo the requested page. Explicit zero
    # total + empty list may omit paging; real empty response remains unobserved.
    if (expected and len(paging) != 2) or (not expected and len(paging) not in (0, 2)):
        raise ValueError("myseoul_list_page_missing")
    for block in paging:
        current = [n for n in visible_nodes(block) if n.attrs.get("aria-current") == "page"]
        if len(current) != 1 or current[0].tag != "button" or current[0].text() != str(page):
            raise ValueError("myseoul_list_page_mismatch")
    items, seen = [], set()
    for card in cards:
        ids = _DETAIL.fullmatch(card.attrs.get("onclick", ""))
        if ids is None:
            raise ValueError("myseoul_list_identity_invalid")
        href = f"https://{HOST}{DETAIL_PATH}?" + urlencode({"prgrm_no": ids[1], "cntr_no": ids[2]})
        center, program, _, canonical = detail_identity(href)
        if (center, program) in seen:
            raise ValueError("myseoul_list_duplicate")
        seen.add((center, program))
        original_href = card.attrs.get("href", "")
        if original_href != "javascript:;":
            try:
                c, p, _, _ = detail_identity(original_href)
            except MySeoulContractError:
                raise ValueError("myseoul_list_link_invalid") from None
            if (c, p) != (center, program):
                raise ValueError("myseoul_list_link_mismatch")
        status = [n for n in visible_nodes(card) if n.tag == "span" and n.has_class("program-state")]
        if len(status) != 1 or not status[0].text() or len(status[0].text()) > 100:
            raise ValueError("myseoul_list_status_invalid")
        items.append({"url": canonical, "status": status[0].text()})
    return ListPage(page=page, total=total, items=items, complete=True, page_size=page_size)


def read_list_page(http, page: int, page_size: int = 10) -> ListPage:
    params = list_parameters(page, page_size)
    if http.max_attempts != 1:
        raise ValueError("myseoul_list_no_retry_required")
    if http.request_count >= http.budget:
        raise HttpBudgetExhausted()
    http.request_count += 1
    response, failure, chunks, size = None, None, [], 0
    limit = min(http.max_response_bytes, 1_000_000)
    try:
        try:
            sender = http.transport or requests.post
            response = sender(LIST_DATA_URL, data=params, timeout=http.timeout_seconds,
                              allow_redirects=False, stream=True, verify=True,
                              headers={"Accept": "text/html"})
            status = int(response.status_code)
            if 300 <= status < 400:
                failure = "redirect_blocked"
            elif status != 200:
                failure = f"http_status_{status}"
            elif "text/html" not in response.headers.get("Content-Type", "").lower():
                failure = "non_html"
            else:
                declared = response.headers.get("Content-Length", "")
                if declared.isdigit() and int(declared) > limit:
                    failure = "response_too_large"
                else:
                    for chunk in response.iter_content(chunk_size=65_536):
                        if not isinstance(chunk, bytes):
                            failure = "response_invalid"
                            break
                        size += len(chunk)
                        if size > limit:
                            failure = "response_too_large"
                            break
                        chunks.append(chunk)
        except requests.Timeout:
            failure = "timeout"
        except Exception:
            failure = "request_failed"
    finally:
        try:
            if response is not None:
                response.close()
        except Exception:
            failure = "response_close_failed"
    if failure == "response_too_large":
        raise ResponseTooLarge()
    if failure and failure.startswith("http_status_"):
        raise HttpStatusError(status)
    if failure:
        raise HttpRequestFailed(failure)
    try:
        html = b"".join(chunks).decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise HttpRequestFailed("html_encoding_invalid") from None
    return parse_list_html(html, page, page_size)
