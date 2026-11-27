"""Bounded Seoul Culture Portal HTML extraction. No AI, credentials or writes.

The initial source scope is the FESTIVAL list, not everything under menu 200010.
Only the event's detail area is evidence; nearby attractions are never evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import requests

from ingest.connectors.myseoul_program import Node, tree, visible_nodes, representative_image
from ingest.http_client import HttpBudgetExhausted, HttpRequestFailed, HttpStatusError, ResponseTooLarge

SOURCE = "seoul_culture_portal"
HOST = "culture.seoul.go.kr"
BASE = f"https://{HOST}"
DETAIL = "/culture/culture/cultureEvent/view.do"
LIST = "/culture/culture/cultureEvent/list.do"
LIST_JSON = "/culture/culture/cultureEvent/jsonList.json"
CONTRACT = "seoul-culture-portal-v1"
MAX_LIST_PAGES = 1000  # Runaway pagination guard, never a complete partial scan.
PAGE_SIZE = 10
LABELS = {"장소": "venue", "기간": "period", "시간": "hours", "대상": "audience", "요금": "fee", "문의": "contact"}


def text(node):
    # Unlike the My Seoul+ presentation helper, retain official contact details.
    if node.tag in {"script", "style", "iframe", "nav", "footer", "noscript"}:
        return ""
    if "hidden" in node.attrs or node.attrs.get("aria-hidden") == "true":
        return ""
    if node.tag == "br":
        return "\n"
    parts = []
    for c in node.children:
        if isinstance(c, str):
            parts.append(c)
        else:
            value = text(c)
            parts.append(("\n" if c.tag in {"p", "div", "li", "tr", "dt", "dd", "h2", "h3", "section"} else " ") + value)
    return "\n".join(re.sub(r"[\t \xa0]+", " ", s).strip() for s in "".join(parts).splitlines() if s.strip())


def detail_identity(href):
    if not isinstance(href, str) or len(href) > 2048 or re.search(r"[\x00-\x20\x7f]", href):
        raise ValueError("portal_detail_url_invalid")
    u = urlsplit(urljoin(BASE, href))
    if u.scheme != "https" or u.netloc != HOST or u.path != DETAIL or u.fragment:
        raise ValueError("portal_detail_url_invalid")
    q = parse_qs(u.query, keep_blank_values=True)
    ids = q.get("cultcode", [])
    if len(ids) != 1 or not re.fullmatch(r"[1-9][0-9]{0,11}", ids[0]):
        raise ValueError("portal_event_id_invalid")
    if set(q) - {"cultcode", "menuNo", "searchCate", "searchDist", "searchCost", "searchField", "searchAge", "sdate", "edate", "pageIndex", "searchStr"}:
        raise ValueError("portal_detail_query_invalid")
    return ids[0], BASE + DETAIL + "?" + urlencode({"cultcode": ids[0], "menuNo": "200010"})


def list_url(page, start, end=date.max):
    # date.max is an ISO date sentinel, not a rolling publication window.
    if type(page) is not int or not 1 <= page <= MAX_LIST_PAGES or not isinstance(start, date) or not isinstance(end, date) or end < start:
        raise ValueError("portal_list_window_invalid")
    return BASE + LIST + "?" + urlencode(dict(searchCate="FESTIVAL", menuNo="200010", sdate=start.isoformat(), edate=end.isoformat(), pageIndex=page))


def read_html(http, url, *, form=None):
    """Fixed-host, no redirects/retries, streamed byte limit and strict UTF-8."""
    u = urlsplit(url)
    if u.scheme != "https" or u.netloc != HOST or u.path not in {LIST, DETAIL, LIST_JSON}:
        raise ValueError("portal_fetch_not_allowed")
    if u.path == DETAIL:
        detail_identity(url)
    elif u.path == LIST_JSON:
        if not form or form.get("searchCate") != "FESTIVAL":
            raise ValueError("portal_festival_scope_required")
    elif parse_qs(u.query).get("searchCate") != ["FESTIVAL"]:
        raise ValueError("portal_festival_scope_required")
    if http.max_attempts != 1:
        raise ValueError("portal_no_retry_required")
    if http.request_count >= http.budget:
        raise HttpBudgetExhausted()
    http.request_count += 1
    response = None
    try:
        options = dict(timeout=http.timeout_seconds, allow_redirects=False, stream=True, headers={"Accept": "application/json" if form else "text/html"})
        if form is not None: options["data"] = form
        response = (http.transport or (requests.post if form else requests.get))(url, **options)
        if response.status_code != 200:
            raise HttpStatusError(response.status_code)
        if ("application/json" if form else "text/html") not in response.headers.get("Content-Type", "").lower():
            raise HttpRequestFailed("portal_non_html")
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=65536):
            if not isinstance(chunk, bytes):
                raise HttpRequestFailed("portal_invalid_bytes")
            size += len(chunk)
            if size > min(http.max_response_bytes, 1_000_000):
                raise ResponseTooLarge()
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="strict")
    except (HttpStatusError, HttpRequestFailed, ResponseTooLarge):
        raise
    except Exception:
        raise HttpRequestFailed("portal_download_failed") from None
    finally:
        if response is not None:
            response.close()


def parse_list(html):
    root = tree(html)
    containers = [n for n in visible_nodes(root) if n.attrs.get("id") == "dataList"]
    if len(containers) != 1:
        raise ValueError("portal_list_template_unknown")
    scope = containers[0]
    links = []
    for n in visible_nodes(scope):
        if n.tag == "a" and "cultcode=" in n.attrs.get("href", ""):
            _, url = detail_identity(n.attrs["href"])
            if url not in links:
                links.append(url)
    if len(links) > 100:
        raise ValueError("portal_list_bound_exceeded")
    # A missing/broken result area is not an empty successful crawl.
    if not links and not re.search(r"검색된.*없|등록된.*없|검색\s*결과가\s*없", text(scope)):
        raise ValueError("portal_empty_not_confirmed")
    return links


def read_list_entries(http, page, start, end=date.max):
    form = {k: v[0] for k,v in parse_qs(urlsplit(list_url(page,start,end)).query).items()}
    data = json.loads(read_html(http, BASE + LIST_JSON, form=form))
    if not isinstance(data, dict) or not isinstance(data.get("resultList"), list) or len(data["resultList"]) > PAGE_SIZE:
        raise ValueError("portal_list_response_invalid")
    # The response echoes the actual query. Wrong scope/page never becomes empty success.
    echoed = parse_qs(data.get("pageQueryString", ""))
    if any(echoed.get(k) != [v] for k,v in form.items()):
        raise ValueError("portal_list_scope_mismatch")
    urls, entries = [], []
    for row in data["resultList"]:
        if not isinstance(row,dict) or row.get("subjcodeGroup") != "FESTIVAL":
            raise ValueError("portal_list_category_mismatch")
        _, canonical = detail_identity(BASE + DETAIL + "?cultcode=" + str(row.get("cultcode", "")))
        if canonical in urls: raise ValueError("portal_list_duplicate")
        urls.append(canonical)
        dates = {k: row.get(v) if isinstance(row.get(v),str) and len(row[v])<=40 else None
                 for k,v in (('start','strtdate'),('end','endDate'))}
        entries.append(dict(url=canonical, **dates))
    return entries


def read_list(http, page, start, end=date.max):
    return [entry['url'] for entry in read_list_entries(http,page,start,end)]


def _labelled(root):
    entries = []
    for n in visible_nodes(root):
        children = [c for c in n.children if isinstance(c, Node)]
        if n.tag == "li" and len(children) >= 2:
            label = text(children[0]).strip(" :：")
            if label in LABELS:
                entries.append(dict(field=LABELS[label], value=" ".join(text(c) for c in children[1:]), origin="structured"))
        if n.tag == "dt" and n.parent:
            siblings = n.parent.children
            following = [c for c in siblings[siblings.index(n)+1:] if isinstance(c, Node)]
            if following and following[0].tag == "dd" and text(n).strip(" :：") in LABELS:
                entries.append(dict(field=LABELS[text(n).strip(" :：")], value=text(following[0]), origin="structured"))
    return [e for i,e in enumerate(entries) if e["value"] and e not in entries[:i]]


def parse_detail(html, url):
    key, canonical = detail_identity(url)
    root = tree(html)
    scopes = [n for n in visible_nodes(root) if n.attrs.get("id") == "print"]
    if len(scopes) != 1:
        raise ValueError("portal_detail_boundary_unknown")
    scope = scopes[0]
    nodes = list(visible_nodes(scope))
    headings = [n for n in nodes if n.tag == "h2"]
    if len(headings) != 1 or not 1 <= len(text(headings[0])) <= 500:
        raise ValueError("portal_detail_title_invalid")
    # Require an explicit event-description boundary. Never flatten the page.
    bodies = [n for n in nodes if n.has_class("culture-content")]
    if len(bodies) != 1:
        raise ValueError("portal_detail_body_unknown")
    body = bodies[0]
    headers = [n for n in nodes if n.has_class("type-box") and _labelled(n)]
    if len(headers) != 1: raise ValueError("portal_metadata_boundary_unknown")
    evidence = _labelled(headers[0])
    categories = [text(n) for n in nodes if n.has_class("type") and n.parent and n.parent.has_class("event-title")]
    if len(categories) != 1:
        raise ValueError("portal_category_unknown")
    alts = list(dict.fromkeys(n.attrs.get("alt", "").strip() for n in visible_nodes(body) if n.tag == "img" and n.attrs.get("alt", "").strip()))
    description = text(body)
    evidence += [dict(field="description", value=description, origin="body")]
    evidence += [dict(field="poster_text", value=a, origin="image_alt_unverified") for a in alts]
    links = []
    for n in visible_nodes(body):
        if n.tag != "a": continue
        href = urljoin(canonical, n.attrs.get("href", ""))
        u = urlsplit(href)
        if u.scheme == "https" and u.netloc == "yeyak.seoul.go.kr" and u.path == "/web/reservation/selectReservView.do":
            q = parse_qs(u.query)
            ids = q.get("rsv_svc_id", [])
            if len(ids) == 1 and re.fullmatch(r"S[0-9]{10,30}", ids[0]):
                # A festival's child reservation is not necessarily the whole festival.
                links.append(dict(kind="reservation", key=ids[0], label=text(n)))
    tables = [[[text(c) for c in row.children if isinstance(c,Node) and c.tag in {"td","th"}]
               for row in visible_nodes(t) if row.tag == "tr"] for t in visible_nodes(body) if t.tag == "table"]
    image_url,image_selection=representative_image(body,canonical)
    official_links=[]
    for box in nodes:
        if not box.has_class('detail-btn'):continue
        for n in visible_nodes(box):
            if n.tag!='a':continue
            link=urljoin(canonical,n.attrs.get('href',''));u=urlsplit(link)
            if (u.scheme=='https' and u.hostname and not u.username and not u.password and len(link)<=2048
                    and not re.search(r'token|secret|password|signature',u.query,re.I)):
                official_links.append(link)
    semantic = dict(contract=CONTRACT, external_key=key, title=text(headings[0]), source_url=canonical,
                    source_category=categories[0], description=description, evidence=evidence,
                    reservation_links=links, tables=tables, official_links=official_links,
                    source_image_url=image_url,source_image_selection=image_selection)
    if len(json.dumps(semantic, ensure_ascii=False).encode()) > 180000:
        raise ValueError("portal_detail_payload_too_large")
    semantic["revision_hash"] = hashlib.sha256(json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return semantic


def assess(event):
    """Conservative deterministic scope, NOT a replacement for human fact review."""
    evidence = event["evidence"]
    values = {k: [e["value"] for e in evidence if e["field"] == k] for k in LABELS.values()}
    body = event["description"]
    category = event["source_category"]
    reasons, issues = [], []
    def issue(code, field, observed):
        if code not in reasons: reasons.append(code)
        issues.append(dict(code=code, field=field, evidence=observed))
    cultural = bool(re.search(r"공연|공예|전통|역사|예술|체험|전시", body))
    # An explicit permanent facility-only description is the only automatic exclusion.
    out = bool(re.search(r"상설\s*(?:시설|관람)|시설\s*이용\s*안내", body) and
               re.search(r"(?:별도|특별)\s*(?:행사|프로그램).*없", body) and not cultural)
    if out:
        return dict(scope="out_of_scope", reasons=["portal_facility_only"], issues=[], ai_status="blocked")
    if not category.startswith("축제") or not cultural:
        issue("portal_scope_unconfirmed", "scope", [category, body])
    for field in ("venue", "period", "hours", "audience", "fee"):
        if not values[field]: issue("portal_missing_information", field, [])
        if len(set(values[field])) > 1: issue("portal_information_conflict", field, values[field])
    for period in values['period']:
        dates=re.findall(r'\d{4}-\d{2}-\d{2}',period)
        try:
            if len(dates)!=2 or date.fromisoformat(dates[0])>date.fromisoformat(dates[1]):raise ValueError()
        except ValueError:issue('portal_missing_information','period',[period])
    if not re.search(r"예약\s*(?:불필요|없이)|사전\s*예약|현장\s*(?:접수|참여)|신청", body):
        issue("portal_booking_unknown", "booking", [])
    if re.search(r"프로그램\s*별|프로그램별|회차\s*별|세부\s*프로그램", body + " ".join(values["hours"])):
        issue("portal_program_conditions", "subprograms", [body])
    if re.search(r"방한\s*외국인|외국인\s*관광객", " ".join(values["audience"]) + body):
        issue("portal_eligibility_unknown", "audience", values["audience"])
    alts = [e["value"] for e in evidence if e["origin"] == "image_alt_unverified"]
    if alts:
        issue("portal_image_evidence", "poster_text", alts)
    times = lambda s: set(re.findall(r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?!\d)", s))
    structured_times = times(" ".join(values["hours"]))
    alt_times = times(" ".join(alts))
    if structured_times and alt_times and structured_times != alt_times:
        issue("portal_information_conflict", "hours", values["hours"] + alts)
    if not body.strip(): issue("portal_missing_information", "description", [])
    # The initial collector adds evidence to human review, never queues AI.
    reasons.append("portal_facts_review")
    return dict(scope="culture_experience" if cultural else "unconfirmed", reasons=list(dict.fromkeys(reasons)), issues=issues, ai_status="blocked")
