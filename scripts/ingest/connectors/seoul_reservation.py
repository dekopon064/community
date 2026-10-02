"""서울 예약 read/normalize only. Not registered in the DB/AI runner."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from ingest.connectors.base import BatchConnector
from ingest.http_client import HttpClient
from ingest.models import BatchMeta, BatchResult, Checkpoint, ObservationRecord

SEOUL_SOURCE_ID = "seoul_reservation"
SEOUL_API_KEY_ENV = "SEOUL_OPEN_DATA_API_KEY"
SERVICE = "tvYeyakCOllect"
KST = timezone(timedelta(hours=9), name="Asia/Seoul")
DATE_FIELDS = ("RCPTBGNDT", "RCPTENDDT", "SVCOPNBGNDT", "SVCOPNENDDT")
SOURCE_FIELDS = (
    "SVCID", "SVCNM", "SVCURL", "MAXCLASSNM", "MINCLASSNM", "DTLCONT",
    "USETGTINFO", "PLACENM", "AREANM", "PAYATNM", "SVCSTATNM",
    *DATE_FIELDS, "V_MIN", "V_MAX", "IMGURL", "X", "Y",
)
STATUSES = {"접수중": "open", "예약마감": "reservation_closed", "접수종료": "application_closed"}


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
    marker = re.search(r"(?:3\s*\.\s*)?상세\s*내용", plain)
    details = plain[marker.end():].strip() if marker else plain
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


def normalize_seoul_item(item: dict[str, Any]) -> ObservationRecord:
    if not isinstance(item, dict):
        raise SeoulContractError("seoul_item_invalid")
    raw: dict[str, str] = {}
    for name in SOURCE_FIELDS:
        value = item.get(name)
        if value is not None and not isinstance(value, (str, int, float)):
            raise SeoulContractError("seoul_field_type_invalid")
        raw[name] = "" if value is None else str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", raw["SVCID"]):
        raise SeoulContractError("seoul_id_invalid")
    if not raw["SVCNM"]:
        raise SeoulContractError("seoul_title_missing")
    if len(raw["DTLCONT"].encode("utf-8")) > 512_000:
        raise SeoulContractError("seoul_body_too_large")
    source_url = raw["SVCURL"] or None
    if source_url:
        try:
            url = urlsplit(source_url)
            valid = (url.scheme in {"http", "https"} and url.netloc == "yeyak.seoul.go.kr"
                     and url.path == "/web/reservation/selectReservView.do"
                     and parse_qs(url.query).get("rsv_svc_id") == [raw["SVCID"]]
                     and set(parse_qs(url.query)) == {"rsv_svc_id"} and not url.fragment)
        except ValueError:
            valid = False
        if not valid:
            raise SeoulContractError("seoul_link_invalid")
    body = parse_body(raw["DTLCONT"])
    normalized = {
        "source_id": SEOUL_SOURCE_ID, "title": raw["SVCNM"], "source_url": source_url,
        "source_body_html": raw["DTLCONT"],  # inert internal source data; never render as HTML
        "provider_fields": {k: v for k, v in raw.items() if k != "DTLCONT"},
        **body, "dates": {name: parse_seoul_date(raw[name]) for name in DATE_FIELDS},
        "timezone": "Asia/Seoul", "source_status": STATUSES.get(raw["SVCSTATNM"], "unknown"),
        "source_updated_at_available": False,
    }
    # Raw content (including table/language structure) participates in the revision.
    # Observed-at, total_count, row/page number and parser version do not.
    digest = hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
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

    def fetch_batch(self, checkpoint: Checkpoint | None) -> BatchResult:
        page = 1 if checkpoint is None else checkpoint.rest_page_num()
        if type(page) is not int or not 1 <= page <= self.max_pages:
            raise SeoulContractError("seoul_checkpoint_out_of_range")
        if page == 1:
            self._seen.clear()
            self._expected_total = None
        key = self._api_key_provider() if self._api_key_provider else os.environ.get(SEOUL_API_KEY_ENV, "")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key):
            raise SeoulContractError("seoul_api_key_missing_or_invalid")
        first, last = (page - 1) * self.page_size + 1, page * self.page_size
        payload, status, size = self.http.get_json(
            f"http://openapi.seoul.go.kr:8088/{key}/json/{SERVICE}/{first}/{last}/",
            source_id=SEOUL_SOURCE_ID, page_num=page, sensitive_values=(key,),
        )
        # Do not retain an echoed credential, even in unexpected provider fields.
        encoded = json.dumps(payload, ensure_ascii=False)
        if key in encoded:
            raise SeoulContractError("seoul_credential_in_response")
        if status != 200 or not isinstance(payload, dict):
            raise SeoulContractError("seoul_response_invalid")
        service = payload.get(SERVICE)
        result = service.get("RESULT") if isinstance(service, dict) else payload.get("RESULT")
        code = result.get("CODE") if isinstance(result, dict) else None
        if code == "INFO-200" and page == 1:
            rows, total = [], 0
        elif code == "INFO-000" and isinstance(service, dict):
            rows, total = service.get("row"), service.get("list_total_count")
        else:
            raise SeoulContractError("seoul_api_result_error")
        if (not isinstance(rows, list) or type(total) is not int or total < 0
                or len(rows) != max(0, min(self.page_size, total - first + 1))):
            raise SeoulContractError("seoul_page_shape_invalid")
        records = [normalize_seoul_item(row) for row in rows]
        ids = [record.external_key for record in records]
        if len(set(ids)) != len(ids):
            raise SeoulContractError("seoul_duplicate_id_in_page")
        if ids and all(sid in self._seen for sid in ids):
            raise SeoulContractError("seoul_repeated_page")
        for record in records:
            if record.external_key in self._seen and self._seen[record.external_key] != record.revision_hash:
                raise SeoulContractError("seoul_revision_changed_during_scan")
        if any(sid in self._seen for sid in ids):
            raise SeoulContractError("seoul_overlapping_pages")
        for record in records:
            self._seen[record.external_key] = record.revision_hash
        drift = self._expected_total is not None and total != self._expected_total
        if self._expected_total is None:
            self._expected_total = total
        end = last >= total
        return BatchResult(tuple(rows), None if end else Checkpoint.for_rest_page(page + 1), end,
                           {"page_num": page, "item_count": len(rows), "total_count": total,
                            "total_changed": drift, "ordering_capability": "untrusted"},
                           BatchMeta(http_status=status, response_bytes=size))

    def to_observation(self, item: dict[str, Any], *, permission_status: str, enabled: bool) -> ObservationRecord:
        # No permission grant, job creation or DB-compatible v1 facts here.
        return normalize_seoul_item(item)


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
