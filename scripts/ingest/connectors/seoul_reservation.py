"""서울 예약 read/normalize connectors; no storage or AI execution here."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Callable

from ingest.connectors.base import BatchConnector
from ingest.http_client import HttpClient
from ingest.models import BatchMeta, BatchResult, Checkpoint, ObservationRecord
from ingest.source_images import source_image_url
from ingest.seoul_links import seoul_source_link

SEOUL_SOURCE_ID = "seoul_reservation"
SEOUL_API_KEY_ENV = "SEOUL_OPEN_DATA_API_KEY"
SERVICE = "tvYeyakCOllect"
CULTURE_SERVICE = "ListPublicReservationCulture"
CULTURE_PAGE_SIZE = 1000
CULTURE_MAX_PAGES = 2
COLLECTION_STATUSES = frozenset({'안내중', '접수중'})
KST = timezone(timedelta(hours=9), name="Asia/Seoul")
DATE_FIELDS = ("RCPTBGNDT", "RCPTENDDT", "SVCOPNBGNDT", "SVCOPNENDDT")
SOURCE_FIELDS = (
    "SVCID", "SVCNM", "SVCURL", "MAXCLASSNM", "MINCLASSNM", "DTLCONT",
    "USETGTINFO", "PLACENM", "AREANM", "PAYATNM", "SVCSTATNM",
    *DATE_FIELDS, "V_MIN", "V_MAX", "IMGURL", "X", "Y",
)
STATUSES = {"안내중": "announced", "접수중": "open", "예약마감": "reservation_closed", "접수종료": "application_closed"}


class SeoulContractError(RuntimeError):
    """Only fixed error codes; never attach raw provider responses or URLs."""


class _BodyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.tables: list[list[list[dict[str, Any]]]] = []
        self.table: list[list[dict[str, Any]]] | None = None
        self.row: list[dict[str, Any]] | None = None
        self.cell: dict[str, Any] | None = None
        self.table_stack: list[tuple[Any, Any, Any]] = []
        self.skip = 0
        self.images = False
        self.attachments = False
        self.table_ranges: list[tuple[int, int, int]] = []
        self._outer_table: tuple[int, int] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "iframe", "object"}:
            self.skip += 1
        if self.skip:
            return
        attributes = dict(attrs)
        if tag == "img":
            self.images = True
        if tag == "a" and re.search(r"\.(?:pdf|hwp|hwpx|jpg|png)(?:[?#]|$)", attributes.get("href") or "", re.I):
            self.attachments = True
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "dt", "dd"}:
            self.parts.append("\n")
            if self.cell:
                self.cell["text"] += " "
        if tag == "table":
            if not self.table_stack:
                self._outer_table = (len(self.parts), len(self.tables))
            if self.cell is not None:
                self.cell.setdefault("nested_tables", []).append(len(self.tables))
            self.table_stack.append((self.table, self.row, self.cell))
            self.table = []
            self.row = self.cell = None
            self.tables.append(self.table)
        if tag == "tr" and self.table is not None:
            self.row = []
            self.table.append(self.row)
        if tag in {"td", "th"}:
            self.parts.append(" | ")
            if self.row is not None:
                def span(name: str) -> int:
                    raw = attributes.get(name) or "1"
                    return int(raw) if re.fullmatch(r"[1-9]\d{0,2}", raw) else 1
                self.cell = {"text": "", "header": tag == "th", "rowspan": span("rowspan"), "colspan": span("colspan")}
                self.row.append(self.cell)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "iframe", "object"}:
            self.skip = max(0, self.skip - 1)
        if self.skip:
            return
        if tag in {"td", "th"}:
            if self.cell:
                self.cell["text"] = re.sub(r"\s+", " ", self.cell["text"]).strip()
            self.cell = None
        if tag == "tr":
            self.row = None
        if tag == "table":
            self.table, self.row, self.cell = self.table_stack.pop() if self.table_stack else (None, None, None)
            if not self.table_stack and self._outer_table is not None:
                start, index = self._outer_table
                self.table_ranges.append((start, len(self.parts), index))
                self._outer_table = None
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "dt", "dd"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)
            if self.cell is not None:
                self.cell["text"] += data
            for _, _, parent_cell in self.table_stack:
                if parent_cell is not None and parent_cell is not self.cell:
                    parent_cell["text"] += " " + data


def parse_body(raw: str) -> dict[str, Any]:
    parser = _BodyParser()
    parser.feed(raw.replace("\\r\\n", "\n"))
    lines = [re.sub(r"[ \t\u00a0]+", " ", part).strip() for part in "".join(parser.parts).splitlines()]
    plain = "\n".join(part for part in lines if part)
    # Preserve simple explicit header/row tables in the AI description. Raw
    # HTML and parsed spans stay separate, including unsupported nested tables.
    parts = parser.parts[:]
    for start, end, index in reversed(parser.table_ranges):
        table = parser.tables[index]
        weekly = bool(table and len(table[0]) >= 3
            and re.fullmatch(r'시간(?:\s*[/·]\s*요일)?', table[0][0]['text'])
            and all(re.fullmatch(r'[월화수목금토일](?:요일)?', c['text']) for c in table[0][1:]))
        if (len(table) < 2 or not table[0] or not (weekly or all(cell['header'] for cell in table[0]))
                or any(len(row) != len(table[0]) for row in table)
                or any((not cell['text'] and not (weekly and row_index > 0 and cell_index > 0))
                       or cell['rowspan'] != 1 or cell['colspan'] != 1 or cell.get('nested_tables')
                       for row_index,row in enumerate(table) for cell_index,cell in enumerate(row))):
            continue
        # Empty cells are an explicit source position, never an inferred session.
        # Only regular weekday matrices permit them; unsupported spans stay raw.
        row_text = lambda row: '| ' + ' | '.join((cell['text'] or '—').replace('|', r'\|') for cell in row) + ' |'
        markdown = '\n\n' + row_text(table[0]) + '\n| ' + ' | '.join('---' for _ in table[0]) + ' |\n'
        markdown += '\n'.join(row_text(row) for row in table[1:]) + '\n\n'
        parts[start:end] = [markdown]
    formatted = '\n'.join(re.sub(r'[ \t\u00a0]+', ' ', line).strip()
                          for line in ''.join(parts).splitlines())
    marker = re.search(r"(?:3\s*\.\s*)?상세\s*내용", formatted)
    details = formatted[marker.end():].strip() if marker else formatted.strip()
    # Warnings can contain actual eligibility, documents and closing conditions.
    # Preserve them for both review and extraction instead of dropping this section.
    # Boilerplate without a details section is not program evidence.
    if not marker and "공공시설 예약서비스 이용시 필수 준수사항" in plain:
        details = ""
    return {"plain_text": plain, "program_text": details, "tables": parser.tables,
            "body_has_images": parser.images, "attachment_links_present": parser.attachments}


def parse_seoul_date(raw: str) -> dict[str, str | None]:
    if not raw:
        return {"raw": None, "value": None, "status": "missing", "precision": None}
    formats = (("%Y-%m-%d %H:%M:%S.%f", "second"), ("%Y-%m-%d %H:%M:%S", "second"), ("%Y-%m-%d", "day"))
    for fmt, precision in formats:
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        # A date-only value remains a date, not a fabricated midnight timestamp.
        value = parsed.date().isoformat() if precision == "day" else parsed.replace(tzinfo=KST).isoformat()
        return {"raw": raw, "value": value, "status": "ok", "precision": precision}
    return {"raw": raw, "value": None, "status": "unparsed", "precision": None}


def seoul_item_id(item: dict[str, Any]) -> str:
    """The existing ID alphabet/length, without repairing or inventing keys."""
    if not isinstance(item, dict):
        raise SeoulContractError("seoul_item_invalid")
    value = item.get('SVCID')
    if value is not None and not isinstance(value, (str, int, float)):
        raise SeoulContractError('seoul_id_invalid')
    sid = '' if value is None else str(value).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', sid):
        raise SeoulContractError('seoul_id_invalid')
    return sid


def invalid_id_error(row_index: int, page: int) -> dict:
    # Do not echo provider values, URLs, titles or credential-like ID strings.
    return dict(row_index=row_index, api_row=row_index + 1, page=page,
                stage='row_identity', error_code='seoul_id_invalid')


def _invalid_page_identity(item: dict[str, Any]) -> tuple[str, str]:
    """Unstorable IDs still participate in page integrity via private hashes.

    Nonempty malformed IDs retain a stable identity across content changes.
    Missing/empty IDs have no usable identity: fingerprint their source fields
    so distinct missing-ID rows can be quarantined independently, while exact
    repeated rows/pages remain detectable. These keys never reach storage.
    """
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                        separators=(',', ':')).encode('utf-8')).hexdigest()
    revision = digest({name: item.get(name) for name in SOURCE_FIELDS})
    value = item.get('SVCID')
    if isinstance(value, (str, int, float)):
        value = str(value).strip()
    identity = ('\0invalid-row:' + revision if value is None or value == ''
                else '\0invalid-id:' + digest(value))
    return identity, revision


def _source_fields(item: dict[str, Any]) -> dict[str, str]:
    sid = seoul_item_id(item)
    raw: dict[str, str] = {}
    for name in SOURCE_FIELDS:
        value = item.get(name)
        if value is not None and not isinstance(value, (str, int, float)):
            raise SeoulContractError("seoul_field_type_invalid")
        raw[name] = "" if value is None else str(value).strip()
    raw['SVCID'] = sid
    return raw


def _raw_revision(raw: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def normalize_seoul_item(item: dict[str, Any], *, culture_external_links: bool = False) -> ObservationRecord:
    raw = _source_fields(item)
    if not raw["SVCNM"]:
        raise SeoulContractError("seoul_title_missing")
    if len(raw["DTLCONT"].encode("utf-8")) > 512_000:
        raise SeoulContractError("seoul_body_too_large")
    original_url = item.get('SVCURL')
    original_url = '' if original_url is None else str(original_url)
    try:
        link = seoul_source_link(original_url, raw['SVCID'], culture_external=culture_external_links)
    except ValueError:
        raise SeoulContractError('seoul_link_invalid') from None
    source_url = link['url']
    body = parse_body(raw["DTLCONT"])
    normalized = {
        "source_id": SEOUL_SOURCE_ID, "title": raw["SVCNM"], "source_url": source_url,
        "source_body_html": raw["DTLCONT"],  # inert internal source data; never render as HTML
        "provider_fields": {k: v for k, v in raw.items() if k != "DTLCONT"},
        "source_image_url": source_image_url(raw["IMGURL"]),
        **body, "dates": {name: parse_seoul_date(raw[name]) for name in DATE_FIELDS},
        "timezone": "Asia/Seoul", "source_status": STATUSES.get(raw["SVCSTATNM"], "unknown"),
        "source_updated_at_available": False,
    }
    if culture_external_links:
        normalized['source_link'] = link
    # Raw content (including table/language structure) participates in the revision.
    # Observed-at, total_count, row/page number and parser version do not.
    digest = _raw_revision(raw)
    attachment = bool(body["body_has_images"] or body["attachment_links_present"] or raw["IMGURL"])
    return ObservationRecord(
        external_key=raw["SVCID"], revision_hash=digest, disposition="observe_only",
        min_fields={"title": raw["SVCNM"], "source_id": SEOUL_SOURCE_ID}, normalized_payload=normalized,
        source_created_at=None, source_created_raw=None, source_created_parse_status="missing",
        source_updated_at=None, source_updated_raw=None, source_updated_parse_status="missing",
        has_source_url=source_url is not None, body_usable=len(body["program_text"]) >= 20,
        attachment_present=attachment, attachment_length=0, is_data_url=False,
    )


class SeoulReservationConnector(BatchConnector):
    service = SERVICE
    isolate_invalid_ids = False
    canonical_source_id = SEOUL_SOURCE_ID
    provider = "seoul"
    source_kind = "content"
    connector_type = "rest"
    legacy_curation_source = SEOUL_SOURCE_ID
    ordering_capability = "untrusted"
    start_mode = "fresh_from_origin"

    def __init__(self, http: HttpClient | None = None, *, api_key_provider: Callable[[], str] | None = None,
                 page_size: int = 50, max_pages: int = 1) -> None:
        if type(page_size) is not int or not 1 <= page_size <= 1000 or type(max_pages) is not int or not 1 <= max_pages <= 5:
            raise SeoulContractError("seoul_limits_invalid")
        self.page_size = page_size
        self.max_pages = self.bootstrap_max_pages = max_pages
        self.bootstrap_max_items = max_pages * page_size
        self.http_budget = max_pages * 3
        self.http = http or HttpClient(budget=self.http_budget)
        self._api_key_provider = api_key_provider
        self._expected_total: int | None = None
        self._seen: dict[str, str] = {}
        self.identity_errors: list[dict] = []
        self.last_diagnostic: dict[str, Any] = {}

    def fetch_batch(self, checkpoint: Checkpoint | None) -> BatchResult:
        self.last_diagnostic = {"stage": "checkpoint"}
        page = 1 if checkpoint is None else checkpoint.rest_page_num()
        if type(page) is not int or not 1 <= page <= self.max_pages:
            raise SeoulContractError("seoul_checkpoint_out_of_range")
        if page == 1:
            self._seen.clear()
            self.identity_errors.clear()
            self._expected_total = None
        self.last_diagnostic.update(stage="configuration", page=page)
        key = self._api_key_provider() if self._api_key_provider else os.environ.get(SEOUL_API_KEY_ENV, "")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key):
            raise SeoulContractError("seoul_api_key_missing_or_invalid")
        first, last = (page - 1) * self.page_size + 1, page * self.page_size
        self.last_diagnostic["stage"] = "api_read"
        payload, status, size = self.http.get_json(
            f"http://openapi.seoul.go.kr:8088/{key}/json/{self.service}/{first}/{last}/",
            source_id=SEOUL_SOURCE_ID, page_num=page, sensitive_values=(key,),
        )
        self.last_diagnostic.update(stage="response_contract", http_status=status, response_bytes=size)
        # Do not retain an echoed credential, even in unexpected provider fields.
        encoded = json.dumps(payload, ensure_ascii=False)
        if key in encoded:
            raise SeoulContractError("seoul_credential_in_response")
        if status != 200 or not isinstance(payload, dict):
            raise SeoulContractError("seoul_response_invalid")
        service = payload.get(self.service)
        result = service.get("RESULT") if isinstance(service, dict) else payload.get("RESULT")
        code = result.get("CODE") if isinstance(result, dict) else None
        if isinstance(code, str) and re.fullmatch(r"(?:INFO|ERROR)-[0-9]{3}", code):
            self.last_diagnostic["api_code"] = code
        if code == "INFO-200" and page == 1:
            rows, total = [], 0
        elif code == "INFO-000" and isinstance(service, dict):
            rows, total = service.get("row"), service.get("list_total_count")
        else:
            raise SeoulContractError("seoul_api_result_error")
        self.last_diagnostic["stage"] = "page_contract"
        if type(rows) is list:
            self.last_diagnostic["row_count"] = len(rows)
        if type(total) is int and total >= 0:
            self.last_diagnostic["total_count"] = total
        if (not isinstance(rows, list) or type(total) is not int or total < 0
                or len(rows) != max(0, min(self.page_size, total - first + 1))):
            raise SeoulContractError("seoul_page_shape_invalid")
        # Page integrity needs identities/revisions, not accepted source URLs.
        # Full item validation belongs to planning, where one rejected item
        # cannot discard the other valid observations in this bounded page.
        identities = []
        for index, row in enumerate(rows):
            self.last_diagnostic.update(stage="row_identity", row_index=index)
            try:
                raw = _source_fields(row)
                identities.append((raw['SVCID'], _raw_revision(raw)))
            except SeoulContractError as exc:
                if not self.isolate_invalid_ids or exc.args != ('seoul_id_invalid',):
                    raise
                self.identity_errors.append(invalid_id_error(first + index - 1, page))
                identities.append(_invalid_page_identity(row))
        self.last_diagnostic.pop("row_index", None)
        self.last_diagnostic["stage"] = "page_identity"
        ids = [sid for sid, _ in identities]
        if len(set(ids)) != len(ids):
            raise SeoulContractError("seoul_duplicate_id_in_page")
        if ids and all(sid in self._seen for sid in ids):
            raise SeoulContractError("seoul_repeated_page")
        for sid, revision in identities:
            if sid in self._seen and self._seen[sid] != revision:
                raise SeoulContractError("seoul_revision_changed_during_scan")
        if any(sid in self._seen for sid in ids):
            raise SeoulContractError("seoul_overlapping_pages")
        for sid, revision in identities:
            self._seen[sid] = revision
        drift = self._expected_total is not None and total != self._expected_total
        if self._expected_total is None:
            self._expected_total = total
        end = last >= total
        self.last_diagnostic["stage"] = "read_complete"
        return BatchResult(tuple(rows), None if end else Checkpoint.for_rest_page(page + 1), end,
                           {"page_num": page, "item_count": len(rows), "total_count": total,
                            "total_changed": drift, "ordering_capability": "untrusted"},
                           BatchMeta(http_status=status, response_bytes=size))

    def to_observation(self, item: dict[str, Any], *, permission_status: str, enabled: bool) -> ObservationRecord:
        # No permission grant, job creation or DB-compatible v1 facts here.
        return normalize_seoul_item(item)


class SeoulCultureConnector(SeoulReservationConnector):
    """Culture listing with two HTTP attempts total, without retry/redirect."""
    service = CULTURE_SERVICE
    isolate_invalid_ids = True

    def __init__(self, http: HttpClient | None = None, *, api_key_provider: Callable[[], str] | None = None):
        super().__init__(http or HttpClient(budget=CULTURE_MAX_PAGES, max_attempts=1),
                         api_key_provider=api_key_provider,
                         page_size=CULTURE_PAGE_SIZE, max_pages=CULTURE_MAX_PAGES)
        self.http_budget = CULTURE_MAX_PAGES

    def to_observation(self, item: dict[str, Any], *, permission_status: str, enabled: bool) -> ObservationRecord:
        return normalize_seoul_item(item, culture_external_links=True)


def require_culture_reader(connector) -> None:
    if (connector.service != CULTURE_SERVICE or connector.page_size != CULTURE_PAGE_SIZE
            or connector.max_pages != CULTURE_MAX_PAGES
            or connector.http.budget != CULTURE_MAX_PAGES or connector.http.max_attempts != 1
            or connector.http.request_count != 0):
        raise SeoulContractError('seoul_culture_limits_invalid')


def read_culture_collection(connector: SeoulCultureConnector) -> BatchResult:
    """Read the complete bounded range before any planning or observation write.

    Unchanged totals and disjoint IDs detect observable page drift; the API
    does not provide a snapshot token, so a transactional snapshot is not claimed.
    """
    require_culture_reader(connector)
    rows, checkpoint = [], None
    for _ in range(CULTURE_MAX_PAGES):
        try:
            page = connector.fetch_batch(checkpoint)
        except Exception:
            connector.last_diagnostic['scanned_rows'] = len(rows)
            raise
        rows.extend(page.items)
        connector.last_diagnostic['scanned_rows'] = len(rows)
        if page.progress['total_count'] > CULTURE_PAGE_SIZE * CULTURE_MAX_PAGES:
            raise SeoulContractError('seoul_culture_range_exceeded')
        if page.progress['total_changed']:
            raise SeoulContractError('seoul_listing_changed')
        if page.natural_end:
            return BatchResult(tuple(rows), None, True,
                               dict(page.progress, identity_errors=tuple(connector.identity_errors)), page.meta)
        checkpoint = page.next_checkpoint
    raise SeoulContractError('seoul_culture_range_incomplete')


@dataclass(frozen=True)
class SeoulPreview:
    records: tuple[ObservationRecord, ...]
    status: str
    stop_reason: str
    pages: int
    request_count: int
    coverage: str = field(default="bounded_listing_observation")


def preview_seoul(connector: SeoulReservationConnector) -> SeoulPreview:
    """Explicit read/normalize preview; never imports a store or AI runner."""
    records: list[ObservationRecord] = []
    checkpoint = None
    changed = False
    for page in range(1, connector.max_pages + 1):
        batch = connector.fetch_batch(checkpoint)
        records.extend(connector.to_observation(item, permission_status="testing_only", enabled=False) for item in batch.items)
        changed = changed or bool(batch.progress["total_changed"])
        if batch.natural_end:
            return SeoulPreview(tuple(records), "incomplete" if changed else "complete",
                                "listing_changed" if changed else "natural_end", page, connector.http.request_count)
        checkpoint = batch.next_checkpoint
    return SeoulPreview(tuple(records), "incomplete", "page_limit", connector.max_pages, connector.http.request_count)
