"""온통청년 정책 REST connector. 페이지 번호는 이 파일 안에만 있다."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Callable

from ingest.attachments import (
    drop_forbidden_attachments,
    extract_sanitized_source_items,
    merge_attachment_meta,
    strip_attachment_meta_keys,
)
from ingest.connectors.base import BatchConnector
from ingest.connectors.paging import next_page_checkpoint, page_from_checkpoint
from ingest.dates import parse_source_datetime
from ingest.http_client import HttpClient
from ingest.models import (
    BatchMeta,
    BatchResult,
    Checkpoint,
    JobPlan,
    ObservationRecord,
    OrderingCapability,
)
from ingest.sanitize import html_to_plain_text, is_http_url
from ingest.source_identity import (
    CANONICAL_POLICY_SOURCE,
    CONNECTOR_TYPE_REST,
    LEGACY_POLICY_CURATION_SOURCE,
    PROVIDER_YOUTHCENTER,
    SOURCE_KIND_POLICY,
)

POLICY_LIST_URL = "https://www.youthcenter.go.kr/go/ythip/getPlcy"
POLICY_PAGE_SIZE = 5
POLICY_BOOTSTRAP_MAX_PAGES = 5
POLICY_BOOTSTRAP_MAX_ITEMS = 25
POLICY_MAX_PAGES = 10
POLICY_HTTP_BUDGET = 30

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/xml, text/xml, */*; q=0.01",
}

SOURCE_URL_FIELDS = ("aplyUrlAddr", "refUrlAddr1", "refUrlAddr2")

MIN_FIELD_KEYS = (
    "plcyNo",
    "plcyNm",
    "zipCd",
    "pvsnInstGroupCd",
    "operInstCd",
    "operInstNm",
    "operInstCdNm",
    "sprvsnInstCd",
    "sprvsnInstNm",
    "sprvsnInstCdNm",
    "rgtrInstCd",
    "rgtrInstNm",
    "rgtrInstCdNm",
    "frstRegDt",
    "lastMdfcnDt",
)

NORMALIZED_KEYS = MIN_FIELD_KEYS + (
    "plcyExplnCn",
    "plcySprtCn",
    "aplyUrlAddr",
    "refUrlAddr1",
    "refUrlAddr2",
    "plcyTpNm",
    "lclsfNm",
    "mclsfNm",
    "polyBizSecd",
    "rgLcnCd",
    "activity_location_text",
)

REVISION_HASH_FIELDS = (
    "plcyNm",
    "plcyExplnCn",
    "plcySprtCn",
    "plcyTpNm",
    "lclsfNm",
    "mclsfNm",
    "source_url",
    "polyBizSecd",
    "zipCd",
    "rgLcnCd",
    "sprvsnInstNm",
    "operInstNm",
    "lastMdfcnDt",
    "pvsnInstGroupCd",
    "operInstCd",
    "sprvsnInstCd",
    "rgtrInstCd",
)


def _copy_keys(item: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: item.get(key) for key in keys}


def select_policy_source_url(item: dict[str, Any]) -> str | None:
    for key in SOURCE_URL_FIELDS:
        value = item.get(key)
        if is_http_url(value):
            return str(value).strip()
    return None


def policy_revision_hash(item: dict[str, Any], source_url: str | None) -> str:
    payload: dict[str, str] = {}
    for key in REVISION_HASH_FIELDS:
        if key == "source_url":
            payload[key] = html_to_plain_text(source_url or "")
        else:
            payload[key] = html_to_plain_text(item.get(key))
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def policy_job_plan(
    disposition: str,
    *,
    reason_codes: tuple[str, ...] = (),
) -> tuple[JobPlan, ...]:
    # Phase 1: never enqueue ai_enrichment. approve_ai RPC is Phase 2.
    if disposition == "region_review_required":
        codes = reason_codes or ("region_review_required",)
        return (JobPlan(stage="region_review", reason_codes=codes),)
    return ()


class YouthcenterPolicyConnector(BatchConnector):
    canonical_source_id = CANONICAL_POLICY_SOURCE
    provider = PROVIDER_YOUTHCENTER
    source_kind = SOURCE_KIND_POLICY
    connector_type = CONNECTOR_TYPE_REST
    legacy_curation_source = LEGACY_POLICY_CURATION_SOURCE
    start_mode = "fresh_from_origin"
    page_size = POLICY_PAGE_SIZE
    bootstrap_max_pages = POLICY_BOOTSTRAP_MAX_PAGES
    bootstrap_max_items = POLICY_BOOTSTRAP_MAX_ITEMS
    max_pages = POLICY_MAX_PAGES
    http_budget = POLICY_HTTP_BUDGET
    ordering_capability: OrderingCapability = "untrusted"

    def __init__(
        self,
        http: HttpClient | None = None,
        *,
        api_key_provider: Callable[[], str] | None = None,
    ) -> None:
        self.http = http or HttpClient(budget=POLICY_HTTP_BUDGET)
        self._api_key_provider = api_key_provider

    def fetch_batch(self, checkpoint: Checkpoint | None) -> BatchResult:
        page_num = page_from_checkpoint(checkpoint)
        api_key = self._api_key()
        payload, status, size = self.http.get_json(
            POLICY_LIST_URL,
            params={
                "apiKeyNm": api_key,
                "pageNum": page_num,
                "pageSize": self.page_size,
                "pageType": 1,
                "rtnType": "json",
            },
            headers=REQUEST_HEADERS,
        )
        items = _policy_list(payload)
        natural_end = len(items) < self.page_size
        return BatchResult(
            items=tuple(items),
            next_checkpoint=None if natural_end else next_page_checkpoint(page_num),
            natural_end=natural_end,
            progress={"page_num": page_num, "item_count": len(items)},
            meta=BatchMeta(
                http_status=status,
                response_bytes=size,
                request_count_delta=0,
            ),
        )

    def to_observation(
        self,
        item: dict[str, Any],
        *,
        permission_status: str,
        enabled: bool,
    ) -> ObservationRecord:
        cleaned, scanned = drop_forbidden_attachments(item)
        if not isinstance(cleaned, dict):
            cleaned = {}
        attachment = merge_attachment_meta(
            item if isinstance(item, dict) else {}, scanned
        )
        cleaned = strip_attachment_meta_keys(cleaned)
        external_key = str(cleaned.get("plcyNo") or "").strip()
        source_url = select_policy_source_url(cleaned)
        created = parse_source_datetime(cleaned.get("frstRegDt"))
        updated = parse_source_datetime(cleaned.get("lastMdfcnDt"))
        body = html_to_plain_text(
            f"{cleaned.get('plcyExplnCn') or ''}\n\n{cleaned.get('plcySprtCn') or ''}"
        )
        normalized = _copy_keys(cleaned, NORMALIZED_KEYS)
        normalized["source_url"] = source_url
        normalized["plain_text"] = body
        normalized["activity_location_text"] = (
            html_to_plain_text(cleaned.get("activity_location_text") or "") or None
        )
        return ObservationRecord(
            external_key=external_key,
            revision_hash=policy_revision_hash(cleaned, source_url),
            disposition="observe_only",
            min_fields=_copy_keys(cleaned, MIN_FIELD_KEYS),
            normalized_payload=normalized,
            source_created_at=created.value,
            source_created_raw=created.raw,
            source_created_parse_status=created.status,
            source_updated_at=updated.value,
            source_updated_raw=updated.raw,
            source_updated_parse_status=updated.status,
            has_source_url=source_url is not None,
            body_usable=bool(body),
            attachment_present=attachment.present,
            attachment_length=attachment.length,
            is_data_url=attachment.is_data_url,
            jobs=(),
            classifier_decision=None,
            product_type_classification=None,
        )

    def _api_key(self) -> str:
        if self._api_key_provider is not None:
            return self._api_key_provider()
        key = os.environ.get("YOUTH_API_KEY")
        if not key:
            raise RuntimeError("youth_api_key_missing")
        return key


def _policy_list(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise RuntimeError("youth_policy_list_invalid")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("youth_policy_list_invalid")
    try:
        return extract_sanitized_source_items(result.get("youthPolicyList"))
    except RuntimeError:
        raise RuntimeError("youth_policy_list_invalid") from None
