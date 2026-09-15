"""온통청년 콘텐츠 REST connector. atchFile는 파싱 직후 제거한다."""

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
    RelationshipPlan,
)
from ingest.sanitize import body_is_usable, extract_http_urls, html_to_plain_text, is_http_url
from ingest.source_identity import (
    CANONICAL_CONTENT_SOURCE,
    CANONICAL_POLICY_SOURCE,
    CONNECTOR_TYPE_REST,
    CONTENT_CURATION_SOURCE,
    PROVIDER_YOUTHCENTER,
    SOURCE_KIND_CONTENT,
    allows_internal_processing,
)

CONTENT_LIST_URL = "https://www.youthcenter.go.kr/go/ythip/getContent"
CONTENT_API_KEY_ENV = "YOUTH_CONTENT_API_KEY"
CONTENT_PAGE_SIZE = 2
CONTENT_BOOTSTRAP_MAX_PAGES = 5
CONTENT_BOOTSTRAP_MAX_ITEMS = 10
CONTENT_MAX_PAGES = 5
CONTENT_HTTP_BUDGET = 15
CONTENT_MAX_RESPONSE_BYTES = 16_000_000

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/xml, text/xml, */*; q=0.01",
}

REVISION_HASH_FIELDS = (
    "pstTtl",
    "plain_text",
    "pstSeNm",
    "bbsSn",
    "pstSn",
    "source_url",
)


def content_external_key(item: dict[str, Any]) -> str:
    bbs = str(item.get("bbsSn") or "").strip()
    pst = str(item.get("pstSn") or "").strip()
    if not bbs or not pst:
        return ""
    return f"{bbs}:{pst}"


def select_content_source_url(item: dict[str, Any], plain_text: str, hrefs: tuple[str, ...]) -> str | None:
    direct = item.get("pstUrlAddr")
    if is_http_url(direct):
        return str(direct).strip()
    for url in hrefs:
        if is_http_url(url):
            return url
    return None


def content_revision_hash(item: dict[str, Any], *, plain_text: str, source_url: str | None) -> str:
    payload = {
        "pstTtl": html_to_plain_text(item.get("pstTtl")),
        "plain_text": plain_text,
        "pstSeNm": html_to_plain_text(item.get("pstSeNm")),
        "bbsSn": str(item.get("bbsSn") or "").strip(),
        "pstSn": str(item.get("pstSn") or "").strip(),
        "source_url": source_url or "",
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def content_job_and_flags(
    *,
    body_usable: bool,
    has_source_url: bool,
    attachment_present: bool,
    permission_ok: bool,
) -> tuple[str, tuple[JobPlan, ...]]:
    reasons: list[str] = []
    attachment_dependent = (not body_usable) and attachment_present
    if attachment_dependent:
        reasons.append("attachment_dependent")
    if not has_source_url:
        reasons.append("missing_source_url")
    if not body_usable and "attachment_dependent" not in reasons:
        reasons.append("empty_body")

    if (
        body_usable
        and has_source_url
        and permission_ok
        and not attachment_dependent
    ):
        return "target", (JobPlan(stage="ai_enrichment"),)

    disposition = "attachment_dependent" if attachment_dependent else "observe_only"
    return disposition, (JobPlan(stage="content_review", reason_codes=tuple(reasons)),)


def policy_relationship_candidates(
    *,
    title: str,
    plain_text: str,
    known_policies: dict[str, str] | None,
) -> tuple[RelationshipPlan, ...]:
    """자동 병합하지 않는다. 제목 완전 일치만 candidate로 남긴다."""
    if not known_policies:
        return ()
    needle = html_to_plain_text(title)
    if not needle:
        return ()
    matches: list[RelationshipPlan] = []
    for external_key, policy_title in known_policies.items():
        if html_to_plain_text(policy_title) == needle:
            matches.append(
                RelationshipPlan(
                    to_source_id=CANONICAL_POLICY_SOURCE,
                    to_external_key=external_key,
                )
            )
    return tuple(matches)


class YouthcenterContentConnector(BatchConnector):
    canonical_source_id = CANONICAL_CONTENT_SOURCE
    provider = PROVIDER_YOUTHCENTER
    source_kind = SOURCE_KIND_CONTENT
    connector_type = CONNECTOR_TYPE_REST
    legacy_curation_source = CONTENT_CURATION_SOURCE
    start_mode = "fresh_from_origin"
    page_size = CONTENT_PAGE_SIZE
    bootstrap_max_pages = CONTENT_BOOTSTRAP_MAX_PAGES
    bootstrap_max_items = CONTENT_BOOTSTRAP_MAX_ITEMS
    max_pages = CONTENT_MAX_PAGES
    http_budget = CONTENT_HTTP_BUDGET
    # Fail-closed overlay/streak policy until a content canary re-judges.
    # Not a claim that Youth API officially guarantees newest-first order.
    ordering_capability: OrderingCapability = "require_descending"

    def __init__(
        self,
        http: HttpClient | None = None,
        *,
        api_key_provider: Callable[[], str] | None = None,
        known_policies: dict[str, str] | None = None,
    ) -> None:
        self.http = http or HttpClient(
            budget=CONTENT_HTTP_BUDGET,
            max_response_bytes=CONTENT_MAX_RESPONSE_BYTES,
        )
        self._api_key_provider = api_key_provider
        self.known_policies = known_policies or {}

    def fetch_batch(self, checkpoint: Checkpoint | None) -> BatchResult:
        page_num = page_from_checkpoint(checkpoint)
        api_key = self._api_key()
        payload, status, size = self.http.get_json(
            CONTENT_LIST_URL,
            params={
                "apiKeyNm": api_key,
                "pageNum": page_num,
                "pageSize": self.page_size,
                "pageType": 1,
                "rtnType": "json",
            },
            headers=REQUEST_HEADERS,
        )
        items = _content_list(payload)
        natural_end = len(items) < self.page_size
        return BatchResult(
            items=tuple(items),
            next_checkpoint=None if natural_end else next_page_checkpoint(page_num),
            natural_end=natural_end,
            progress={"page_num": page_num, "item_count": len(items)},
            meta=BatchMeta(http_status=status, response_bytes=size),
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
        html_body = str(cleaned.get("pstWholCn") or "")
        hrefs = extract_http_urls(html_body)
        plain = html_to_plain_text(html_body)
        title = html_to_plain_text(cleaned.get("pstTtl"))
        source_url = select_content_source_url(cleaned, plain, hrefs)
        usable = body_is_usable(plain)
        permission_ok = allows_internal_processing(permission_status, enabled=enabled)
        disposition, jobs = content_job_and_flags(
            body_usable=usable,
            has_source_url=source_url is not None,
            attachment_present=attachment.present,
            permission_ok=permission_ok,
        )
        relationships = policy_relationship_candidates(
            title=title,
            plain_text=plain,
            known_policies=self.known_policies,
        )
        if relationships:
            jobs = jobs + (
                JobPlan(stage="relationship_review", reason_codes=("policy_link_candidate",)),
            )
        created = parse_source_datetime(
            cleaned.get("frstRegDt") or cleaned.get("regDt")
        )
        updated = parse_source_datetime(
            cleaned.get("lastMdfcnDt") or cleaned.get("mdfcnDt")
        )
        normalized = {
            "bbsSn": cleaned.get("bbsSn"),
            "pstSn": cleaned.get("pstSn"),
            "pstSeSn": cleaned.get("pstSeSn"),
            "pstSeNm": cleaned.get("pstSeNm"),
            "pstTtl": title,
            "plain_text": plain,
            "source_url": source_url,
        }
        return ObservationRecord(
            external_key=content_external_key(cleaned),
            revision_hash=content_revision_hash(
                cleaned, plain_text=plain, source_url=source_url
            ),
            disposition=disposition,  # type: ignore[arg-type]
            min_fields={
                "bbsSn": cleaned.get("bbsSn"),
                "pstSn": cleaned.get("pstSn"),
                "pstSeNm": cleaned.get("pstSeNm"),
            },
            normalized_payload=normalized,
            source_created_at=created.value,
            source_created_raw=created.raw,
            source_created_parse_status=created.status,
            source_updated_at=updated.value,
            source_updated_raw=updated.raw,
            source_updated_parse_status=updated.status,
            has_source_url=source_url is not None,
            body_usable=usable,
            attachment_present=attachment.present,
            attachment_length=attachment.length,
            is_data_url=attachment.is_data_url,
            jobs=jobs,
            relationships=relationships,
        )

    def _api_key(self) -> str:
        if self._api_key_provider is not None:
            return self._api_key_provider()
        key = os.environ.get(CONTENT_API_KEY_ENV)
        if not key:
            raise RuntimeError("youth_content_api_key_missing")
        return key


def _content_list(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise RuntimeError("youth_content_list_invalid")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("youth_content_list_invalid")
    try:
        return extract_sanitized_source_items(result.get("youthPolicyList"))
    except RuntimeError:
        raise RuntimeError("youth_content_list_invalid") from None
