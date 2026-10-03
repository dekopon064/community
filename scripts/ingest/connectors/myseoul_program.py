"""My Seoul+ partial homepage discovery. Local-only: no registry/DB/AI binding.

HTML examples in the tests are synthetic, not saved site responses. Selectors
come from the investigation; a small live parity check remains a separate step.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Iterator
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import requests

from ingest.connectors.base import BatchConnector
from ingest.http_client import (
    HttpBudgetExhausted, HttpClient, HttpRequestFailed, HttpStatusError,
    ResponseTooLarge,
)
from ingest.models import BatchMeta, BatchResult, Checkpoint, ObservationRecord
from ingest.source_images import source_image_url

SOURCE = "myseoul_program"
PARSER_VERSION = "myseoul-html-v2-local"
REVISION_CONTRACT = "myseoul-semantic-v2"
HOST = "global.seoul.go.kr"
HOME = f"https://{HOST}/hmpg/main/main.do"
DETAIL_PATH = "/hmpg/ecpr/prgm/prgmDetail.do"
_VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
_SKIP = frozenset("script style iframe object form textarea nav footer".split())
_BLOCK = frozenset("p div li ul ol table dl dt dd h1 h2 h3 h4 tr section article br".split())


class MySeoulContractError(RuntimeError):
    """Fixed codes only: no URLs, page text or underlying exception messages."""


def clean(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[연락처 생략]", text)
    text = re.sub(r"(?<!\d)(?:\+82[- ]?|0)(?:\d{1,2})[- .]\d{3,4}[- .]\d{4}(?!\d)", "[연락처 생략]", text)
    return re.sub(r"[ \t\xa0]+", " ", text).strip()


@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict[str, str]
    parent: Node | None = field(default=None, repr=False)
    children: list[Node | str] = field(default_factory=list)

    def nodes(self) -> Iterator[Node]:
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.nodes()

    def has_class(self, name: str) -> bool:
        return name in self.attrs.get("class", "").split()

    def text(self) -> str:
        if self.tag in _SKIP:
            return ""
        if self.tag == "br":
            return "\n"
        parts = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            else:
                value = child.text()
                if child.tag in {"td", "th"}:
                    parts.append(" | " + value)
                elif child.tag in _BLOCK:
                    parts.append("\n" + value + "\n")
                else:
                    parts.append(value)
        return "\n".join(line for x in "".join(parts).splitlines() if (line := clean(x)))


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document", {})
        self.current = self.root
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.count += 1
        if self.count > 20_000:
            raise MySeoulContractError("html_node_limit")
        node = Node(tag, {key: value or "" for key, value in attrs}, self.current)
        self.current.children.append(node)
        if tag not in _VOID:
            self.current = node
            # Bounded nesting also protects recursive text/tree walkers.
            depth, cursor = 0, node
            while cursor.parent is not None:
                depth += 1
                cursor = cursor.parent
            if depth > 100:
                raise MySeoulContractError("html_depth_limit")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        cursor = self.current
        while cursor.parent is not None:
            if cursor.tag == tag:
                self.current = cursor.parent
                return
            cursor = cursor.parent

    def handle_data(self, data: str) -> None:
        self.current.children.append(data)


def tree(html: str) -> Node:
    if not isinstance(html, str) or len(html.encode("utf-8")) > 1_000_000:
        raise MySeoulContractError("html_size_or_type_invalid")
    parser = _Tree()
    parser.feed(html)
    parser.close()
    return parser.root


def visible_nodes(node: Node) -> Iterator[Node]:
    if node.tag in _SKIP:
        return
    yield node
    for child in node.children:
        if isinstance(child, Node):
            yield from visible_nodes(child)


def detail_identity(href: str) -> tuple[str, str, str, str]:
    """Canonical KO identity; unknown params are rejected instead of forwarded."""
    try:
        url = urlsplit(urljoin(HOME, href))
    except ValueError:
        url = None
    if url is None:
        raise MySeoulContractError("detail_url_invalid")
    if (url.scheme != "https" or url.netloc != HOST or url.path != DETAIL_PATH
            or url.fragment or len(url.query) > 512):
        raise MySeoulContractError("detail_url_invalid")
    params = parse_qs(url.query, keep_blank_values=True)
    if set(params) - {"cntr_no", "prgrm_no", "lang"}:
        raise MySeoulContractError("detail_query_invalid")
    ids = []
    for key in ("cntr_no", "prgrm_no"):
        values = params.get(key, [])
        if len(values) != 1 or not re.fullmatch(r"[A-Fa-f0-9]{32}", values[0]):
            raise MySeoulContractError("detail_id_invalid")
        ids.append(values[0].upper())
    langs = params.get("lang", ["ko"])
    if len(langs) != 1 or langs[0] not in {"ko", "en", "ja", "zh"}:
        raise MySeoulContractError("detail_language_invalid")
    canonical = f"https://{HOST}{DETAIL_PATH}?" + urlencode(
        {"cntr_no": ids[0], "prgrm_no": ids[1], "lang": "ko"}
    )
    return ids[0], ids[1], langs[0], canonical


def _education_scope(root: Node) -> Node:
    # Observed live markup: div.edu-program > div.ep-head > span.ep-label.
    # The ep-more link also says "교육 프로그램" in span.hide; it is NOT a title.
    containers = [n for n in visible_nodes(root)
                  if n.tag == "div" and n.has_class("edu-program")]
    if containers:
        if len(containers) != 1:
            raise MySeoulContractError("education_section_missing_or_ambiguous")
        scope = containers[0]
        heads = [n for n in visible_nodes(scope)
                 if n.tag == "div" and n.has_class("ep-head") and n.parent is scope]
        if len(heads) != 1:
            raise MySeoulContractError("education_section_boundary_unknown")
        labels = [n for n in visible_nodes(heads[0])
                  if n.tag == "span" and n.has_class("ep-label") and n.parent is heads[0]]
        if len(labels) != 1 or labels[0].text() != "교육 프로그램":
            raise MySeoulContractError("education_section_missing_or_ambiguous")
        # A second legacy education block is ambiguous too. Do not silently
        # ignore it or merge links across unrelated homepage regions.
        own_nodes = set(visible_nodes(scope))
        if any(n.tag in {"h1", "h2", "h3", "h4"} and n.text() == "교육 프로그램"
               and n not in own_nodes for n in visible_nodes(root)):
            raise MySeoulContractError("education_section_missing_or_ambiguous")
        return scope

    # Compatibility with a bounded heading-based layout. If canonical markup
    # is present but malformed, the branch above fails instead of falling back.
    headings = [n for n in visible_nodes(root)
                if n.tag in {"h1", "h2", "h3", "h4"} and n.text() == "교육 프로그램"]
    if len(headings) != 1:
        raise MySeoulContractError("education_section_missing_or_ambiguous")
    heading = headings[0]
    # Smallest containing block, bounded by unrelated headings. Never use the
    # entire document/body as a fallback when the site's template changes.
    scope = heading.parent
    while scope is not None and scope.tag not in {"body", "html", "document"}:
        nodes = list(visible_nodes(scope))
        unrelated = [n for n in nodes if n.tag in {"h1", "h2", "h3", "h4"}
                     and n is not heading and n.text() != "교육 프로그램"]
        links = [n for n in nodes if n.tag == "a" and DETAIL_PATH in n.attrs.get("href", "")]
        if not unrelated and (links or scope.tag == "section"):
            break
        if unrelated:
            raise MySeoulContractError("education_section_boundary_unknown")
        scope = scope.parent
    if scope is None or scope.tag in {"body", "html", "document"}:
        raise MySeoulContractError("education_section_boundary_unknown")
    return scope


def discover_home(html: str) -> tuple[dict[str, Any], ...]:
    scope = _education_scope(tree(html))
    found: dict[str, dict[str, Any]] = {}
    for node in visible_nodes(scope):
        if node.tag != "a" or DETAIL_PATH not in node.attrs.get("href", ""):
            continue
        center, program, lang, url = detail_identity(node.attrs["href"])
        key = f"{center}:{program}"
        entry = found.setdefault(key, {"external_key": key, "center_id": center,
                                     "program_id": program, "url": url, "discovered_languages": []})
        if lang not in entry["discovered_languages"]:
            entry["discovered_languages"].append(lang)
    # Explicit empty education section is different from a missing template.
    if not found and not re.search(r"등록된\s*(?:교육\s*)?프로그램이\s*없|프로그램\s*없음", scope.text()):
        raise MySeoulContractError("education_links_not_readable")
    return tuple(found.values())


LABELS = {
    "구분": "category", "분류": "category", "교육분류": "category",
    "대상": "target", "교육대상": "target", "참가대상": "target", "참여대상": "target", "신청자격": "target",
    "거주조건": "residence", "거주지": "residence", "연령": "age", "동반조건": "companion",
    "진행언어": "language", "교육언어": "language",
    "장소": "venue", "교육장소": "venue", "개최장소": "venue",
    "진행방식": "mode", "교육방식": "mode", "신청주체": "actor", "신청대상": "actor",
    "수강료": "tuition", "참가비": "tuition", "비용": "tuition",
    "재료비": "materials", "입장료": "admission", "부대비": "extra_fee",
    "신청일시": "application", "신청기간": "application", "접수기간": "application",
    "교육일시": "operation", "운영기간": "operation", "교육기간": "operation", "행사일시": "operation", "일시": "operation",
    "회차": "sessions", "일정": "sessions", "집결시간": "meeting", "집결장소": "meeting_venue",
    "모집상태": "status", "접수상태": "status", "상태": "status",
    "신청방법": "application_method", "예약방법": "application_method", "신청": "application_method",
    "내용": "purpose", "주요내용": "purpose", "프로그램내용": "purpose", "목적": "purpose",
    "명시조건": "condition", "신청조건": "condition", "참여조건": "condition", "정원": "capacity",
}


def _label_key(label: str, value: str) -> str | None:
    label = re.sub(r"[\s\[\]:：|]", "", label)
    key = LABELS.get(label)
    # Generic participation fee can explicitly mean admission/materials. Do
    # not relabel specific tuition or guess a composite/unspecified cost.
    if label in {"참가비", "비용"}:
        mentioned = set(re.findall(r"수강료|입장료|재료비", value))
        if len(mentioned) > 1:
            return "extra_fee"  # Preserve composite evidence; scope marks unresolved.
        kinds = [field for token, field in (("입장료", "admission"), ("재료비", "materials"))
                 if re.search(r"\(\s*" + token + r"\s*\)", value)]
        if len(kinds) == 1:
            key = kinds[0]
    return key


def metadata_values(header: Node) -> list[dict[str, str]]:
    """Observed metadata only; malformed canonical layout never falls back."""
    lists = [n for n in visible_nodes(header) if n.has_class("pg-det-list")]
    if not lists:
        return labelled_values(header, "header")
    if len(lists) != 1 or lists[0].tag != "div":
        raise MySeoulContractError("detail_metadata_invalid")
    items = [n for n in lists[0].children if isinstance(n, Node)]
    if not items or any(n.tag != "div" or not n.has_class("item") for n in items):
        raise MySeoulContractError("detail_metadata_invalid")
    result, seen = [], set()
    for item in items:
        children = [n for n in item.children if isinstance(n, Node)]
        if len(children) != 2 or children[0].tag != "em" or children[1].tag != "span":
            raise MySeoulContractError("detail_metadata_invalid")
        label, value = children[0].text(), children[1].text()
        canonical_label = re.sub(r"\s", "", label)
        if not label or canonical_label in seen:
            raise MySeoulContractError("detail_metadata_invalid")
        seen.add(canonical_label)
        key = _label_key(label, value)
        if key and value:
            result.append({"field": key, "label": label, "value": value, "origin": "header"})
    return result


def title_parts(container: Node) -> tuple[str, str | None]:
    titles = [n for n in visible_nodes(container) if n.tag == "p" and n.has_class("txt-26")]
    badges = [n for n in container.children if isinstance(n, Node) and n.has_class("cate-st4")]
    if titles or badges or any(isinstance(n, Node) for n in container.children):
        if len(titles) != 1 or len(badges) != 1 or not badges[0].text():
            raise MySeoulContractError("detail_title_structure_invalid")
        return titles[0].text(), badges[0].text()
    # Existing plain-text synthetic/legacy title has no status/category children.
    return container.text(), None


def labelled_values(node: Node, origin: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []

    def add(label: str, value: str) -> None:
        key = _label_key(label, value)
        if key and (value := clean(value).strip(" |")):
            item = {"field": key, "label": clean(label), "value": value, "origin": origin}
            if item not in result:
                result.append(item)

    for n in visible_nodes(node):
        if n.tag == "dt" and n.parent:
            siblings = n.parent.children
            index = siblings.index(n)
            next_nodes = [s for s in siblings[index + 1:] if isinstance(s, Node)]
            if next_nodes and next_nodes[0].tag == "dd":
                add(n.text(), next_nodes[0].text())
        if n.tag == "tr":
            cells = [c for c in n.children if isinstance(c, Node) and c.tag in {"th", "td"}]
            if len(cells) == 2:
                add(cells[0].text(), cells[1].text())
        if n.tag == "li":
            children = [c for c in n.children if isinstance(c, Node)]
            if len(children) == 2:
                add(children[0].text(), children[1].text())
    for line in node.text().splitlines():
        match = re.match(r"^[•○ㅇ■□\s-]*([^:：|]{1,20})\s*[:：|]\s*(.+)$", line)
        if match:
            add(match[1], match[2])
    return result


def _one_class(root: Node, class_name: str) -> Node:
    matches = [n for n in visible_nodes(root) if n.has_class(class_name)]
    if len(matches) != 1:
        raise MySeoulContractError("detail_template_invalid")
    return matches[0]


def safe_application_link(href: str, label: str) -> str | None:
    # Preserve a labelled public application link; do NOT fetch it. Links with
    # secret-looking query names or attachment paths are not copied to payloads.
    try:
        url = urlsplit(urljoin(HOME, href))
    except ValueError:
        return None
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or not re.search(r"신청|예약|접수|폼|form", label, re.I)
            or re.search(r"\.(?:pdf|hwp|hwpx|png|jpe?g|gif)(?:$|/)", url.path, re.I)
            or re.search(r"token|secret|password|email|phone|key", url.query, re.I)):
        return None
    return url.geturl() if len(url.geturl()) <= 2048 else None


def representative_image(body: Node, base_url: str) -> tuple[str | None, str]:
    """Only images inside the program body; ambiguous candidates stay absent.

    URL validation is shared with the other sources. No image fetch is made.
    A unique poster-labelled image wins, otherwise require one unique body image.
    """
    candidates: dict[str, bool] = {}
    for node in visible_nodes(body):
        if node.tag != "img":
            continue
        cursor, hidden = node, False
        while cursor is not None:
            if (cursor.tag in {"template", "noscript"} or "hidden" in cursor.attrs
                    or cursor.attrs.get("aria-hidden", "").lower() == "true"
                    or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", cursor.attrs.get("style", ""), re.I)):
                hidden = True
                break
            if cursor is body:
                break
            cursor = cursor.parent
        if hidden or any(re.fullmatch(r"[01](?:px)?", node.attrs.get(k, "").strip(), re.I)
                         for k in ("width", "height")):
            continue
        label = " ".join(node.attrs.get(k, "") for k in ("alt", "title", "class", "id"))
        raw = node.attrs.get("src", "")
        # urljoin/urlsplit strip some control characters: reject them first.
        if re.search(r"[\x00-\x1f\x7f]", raw):
            continue
        if re.search(r"logo|icon|banner|tracker|tracking|pixel|로고|아이콘|배너", label + " " + raw, re.I):
            continue
        # Do not retain signed/authenticated links or private query values.
        try:
            resolved = urljoin(base_url, raw) if raw.strip() else None
            if resolved and any(re.search(r"token|secret|password|signature|api_key|access_key|auth", k, re.I)
                                for k in parse_qs(urlsplit(resolved).query)):
                continue
            validated = source_image_url(resolved)
        except ValueError:
            validated = None
        if validated:
            poster = bool(re.search(r"poster|포스터", label, re.I))
            candidates[validated] = candidates.get(validated, False) or poster
    posters = [u for u, marked in candidates.items() if marked]
    if len(posters) == 1:
        return posters[0], "body_poster"
    if len(candidates) == 1:
        return next(iter(candidates)), "unique_body_image"
    return None, "absent_or_ambiguous"


def normalize_detail(html: str, url: str) -> ObservationRecord:
    center, program, lang, official_url = detail_identity(url)
    if lang != "ko":
        raise MySeoulContractError("detail_not_korean")
    root = _one_class(tree(html), "board_detail")
    title, badge = title_parts(_one_class(root, "program-tit"))
    if not title or len(title) > 500:
        raise MySeoulContractError("detail_title_invalid")
    header = _one_class(root, "program-detail")
    body = _one_class(root, "program-content")
    description = body.text()
    evidence = metadata_values(header)
    if badge:
        evidence.append({"field": "status", "label": "모집 배지", "value": badge, "origin": "header"})
    evidence += labelled_values(body, "body")
    categories = [n.text() for n in visible_nodes(root) if n.has_class("program-cate")]
    if len(categories) != 1 or not categories[0]:
        raise MySeoulContractError("detail_category_invalid")
    source_category = categories[0]
    tables = []
    for table in visible_nodes(body):
        if table.tag != "table":
            continue
        rows = []
        for row in visible_nodes(table):
            if row.tag != "tr":
                continue
            cells = []
            for cell in row.children:
                if not isinstance(cell, Node) or cell.tag not in {"th", "td"}:
                    continue
                def span(key: str) -> int:
                    raw = cell.attrs.get(key, "1")
                    return int(raw) if re.fullmatch(r"[1-9]\d{0,2}", raw) else 1
                cells.append({"text": cell.text(), "header": cell.tag == "th",
                              "rowspan": span("rowspan"), "colspan": span("colspan")})
            rows.append(cells)
        tables.append(rows)
    nodes = list(visible_nodes(body))
    application_links = list(dict.fromkeys(link for n in nodes if n.tag == "a"
                              and (link := safe_application_link(n.attrs.get("href", ""), n.text()))))
    conditions = [line for line in description.splitlines()
                  if re.search(r"조건|제한|불가|필수|선착순|조기\s*마감|동반|국적|비자|체류|인원|취소|불참|환불", line)]
    semantic = {"center_id": center, "program_id": program, "source_language": "ko",
                "title": title, "official_url": official_url, "source_category": source_category,
                "description": description, "labelled_evidence": evidence, "tables": tables,
                "conditions": conditions, "application_links": application_links}
    image_url, image_selection = representative_image(body, official_url)
    # An absent image preserves the pre-image semantic hash. Valid image URL
    # add/change/removal is meaningful; selector capability is a separate ref.
    if image_url:
        semantic["source_image_url"] = image_url
    # Parser/profile versions are references, not source changes.
    revision = hashlib.sha256(json.dumps(semantic, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()
    images = any(n.tag == "img" for n in nodes)
    attachments = any(n.tag == "a" and re.search(r"\.(?:pdf|hwp|hwpx)(?:[?#]|$)",
                      n.attrs.get("href", ""), re.I) for n in nodes)
    payload = {**semantic, "parser_version": PARSER_VERSION,
               "revision_contract": REVISION_CONTRACT,
               "source_image_url": image_url,
               "source_image_selection": image_selection,
               "source_image_contract": "myseoul-body-image-v1",
               "body_has_images": images, "attachment_links_present": attachments}
    return ObservationRecord(
        external_key=f"{center}:{program}", revision_hash=revision, disposition="observe_only",
        min_fields={"title": title, "source_url": official_url}, normalized_payload=payload,
        source_created_at=None, source_created_raw=None, source_created_parse_status="missing",
        source_updated_at=None, source_updated_raw=None, source_updated_parse_status="missing",
        has_source_url=True, body_usable=len(description) >= 20,
        attachment_present=images or attachments, attachment_length=0, is_data_url=False,
    )


def _read_html(http: HttpClient, url: str) -> tuple[str, int, int]:
    if url != HOME:
        detail_identity(url)
    if http.request_count >= http.budget:
        raise HttpBudgetExhausted()
    http.request_count += 1
    response = None
    failure: str | None = None
    content: bytes | None = None
    status = 0
    try:
        try:
            sender = http.transport or requests.get
            response = sender(url, timeout=http.timeout_seconds, allow_redirects=False,
                              stream=True, headers={"Accept": "text/html"})
            status = int(response.status_code)
            if 300 <= status < 400:
                failure = "redirect_blocked"
            elif status != 200:
                failure = f"status_{status}"
            elif "text/html" not in response.headers.get("Content-Type", "").lower():
                failure = "non_html"
            else:
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=65_536):
                    if not isinstance(chunk, bytes):
                        failure = "response_invalid"
                        break
                    size += len(chunk)
                    if size > min(http.max_response_bytes, 1_000_000):
                        failure = "response_too_large"
                        break
                    chunks.append(chunk)
                if not failure:
                    content = b"".join(chunks)
        except requests.Timeout:
            failure = "timeout"
        except Exception:
            failure = "request_failed"
    finally:
        # Never let an unsafe underlying URL/response exception escape.
        try:
            if response is not None:
                response.close()
        except Exception:
            failure = "response_close_failed"
    if failure == "response_too_large":
        raise ResponseTooLarge()
    if failure and failure.startswith("status_"):
        raise HttpStatusError(status)
    if failure or content is None:
        raise HttpRequestFailed(failure or "response_invalid")
    try:
        html = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        html = None
    if html is None:
        raise MySeoulContractError("html_encoding_invalid")
    return html, status, len(content)


class MySeoulProgramConnector(BatchConnector):
    canonical_source_id = SOURCE
    provider = "myseoulplus"
    source_kind = "content"  # Registry kind; public program/event is a facts axis.
    connector_type = "public_homepage_partial"
    legacy_curation_source = SOURCE  # Disabled local SQL identity; default runners unchanged.
    ordering_capability = "untrusted"
    page_size = bootstrap_max_items = 8
    bootstrap_max_pages = max_pages = 1

    def __init__(self, http: HttpClient, *, detail_limit: int = 8) -> None:
        if not 1 <= detail_limit <= 20 or not 1 <= http.budget <= 21:
            raise MySeoulContractError("discovery_budget_invalid")
        self.http = http
        self.http_budget = http.budget
        self.detail_limit = detail_limit
        self.page_size = self.bootstrap_max_items = detail_limit

    def fetch_batch(self, checkpoint: Checkpoint | None) -> BatchResult:
        if checkpoint is not None:
            raise MySeoulContractError("homepage_checkpoint_not_supported")
        before = self.http.request_count
        home, status, size = _read_html(self.http, HOME)
        found = discover_home(home)
        available = min(self.detail_limit, self.http.remaining())
        selected = found[:available]
        items = []
        for entry in selected:
            html, _, byte_count = _read_html(self.http, entry["url"])
            size += byte_count
            record = normalize_detail(html, entry["url"])
            items.append({"record": record, "discovered_languages": entry["discovered_languages"]})
        complete = len(items) == len(found)
        # Incomplete runs do NOT advertise natural_end/whole-source completeness.
        return BatchResult(
            items=tuple(items), next_checkpoint=None, natural_end=complete,
            progress={"coverage": "homepage_education_only", "source_complete": False,
                      "homepage_scope_complete": complete, "discovered": len(found),
                      "processed": len(items), "omitted": len(found) - len(items),
                      "stop_reason": "homepage_scope_complete" if complete else "discovery_budget_limit"},
            meta=BatchMeta(http_status=status, response_bytes=size,
                           request_count_delta=self.http.request_count - before),
        )

    def to_observation(self, item: dict, *, permission_status: str, enabled: bool) -> ObservationRecord:
        # Local parser output never invents jobs/gate facts or evaluates permission.
        record = item.get("record")
        if not isinstance(record, ObservationRecord):
            raise MySeoulContractError("local_item_invalid")
        return record
