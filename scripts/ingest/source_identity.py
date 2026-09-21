"""Canonical source ID와 legacy curation source 매핑.

문자열 별칭은 이 모듈(및 동일 계약을 구현한 SQL 함수)에만 둔다.
"""

from __future__ import annotations

from typing import Final

CANONICAL_POLICY_SOURCE: Final = "youthcenter_policy"
CANONICAL_CONTENT_SOURCE: Final = "youthcenter_content"
PROVIDER_YOUTHCENTER: Final = "youthcenter"
SOURCE_KIND_POLICY: Final = "policy"
SOURCE_KIND_CONTENT: Final = "content"
CONNECTOR_TYPE_REST: Final = "rest"

LEGACY_POLICY_CURATION_SOURCE: Final = "youthcenter"
CONTENT_CURATION_SOURCE: Final = "youthcenter_content"

SOURCE_ID_PATTERN: Final = r"^[a-z][a-z0-9_]{1,31}$"

PERMISSION_TESTING_ONLY: Final = "testing_only"
PERMISSION_APPROVED_NONCOMMERCIAL: Final = "approved_noncommercial"
PERMISSION_COMMERCIAL_REVIEW_REQUIRED: Final = "commercial_review_required"
PERMISSION_APPROVED_COMMERCIAL: Final = "approved_commercial"

INTERNAL_PROCESSING_PERMISSIONS: Final = frozenset(
    {
        PERMISSION_TESTING_ONLY,
        PERMISSION_APPROVED_NONCOMMERCIAL,
        PERMISSION_APPROVED_COMMERCIAL,
    }
)
PUBLISH_PERMISSIONS: Final = frozenset(
    {
        PERMISSION_APPROVED_NONCOMMERCIAL,
        PERMISSION_APPROVED_COMMERCIAL,
    }
)

# SQL set_source_permission과 같은 허용 전환. 단계를 건너뛰지 않는다.
ALLOWED_PERMISSION_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    PERMISSION_TESTING_ONLY: frozenset({PERMISSION_APPROVED_NONCOMMERCIAL}),
    PERMISSION_APPROVED_NONCOMMERCIAL: frozenset(
        {PERMISSION_COMMERCIAL_REVIEW_REQUIRED}
    ),
    PERMISSION_COMMERCIAL_REVIEW_REQUIRED: frozenset(
        {PERMISSION_APPROVED_COMMERCIAL}
    ),
    PERMISSION_APPROVED_COMMERCIAL: frozenset(),
}

_CANONICAL_BY_CURATION: Final = {
    LEGACY_POLICY_CURATION_SOURCE: CANONICAL_POLICY_SOURCE,
    CONTENT_CURATION_SOURCE: CANONICAL_CONTENT_SOURCE,
    CANONICAL_POLICY_SOURCE: CANONICAL_POLICY_SOURCE,
    CANONICAL_CONTENT_SOURCE: CANONICAL_CONTENT_SOURCE,
}

_CURATION_BY_CANONICAL: Final = {
    CANONICAL_POLICY_SOURCE: LEGACY_POLICY_CURATION_SOURCE,
    CANONICAL_CONTENT_SOURCE: CONTENT_CURATION_SOURCE,
}


def canonical_source_id(source: str) -> str:
    """legacy 또는 canonical 값을 canonical source ID로 정규화한다."""
    key = (source or "").strip()
    mapped = _CANONICAL_BY_CURATION.get(key)
    if mapped is None:
        raise ValueError("unknown source identity")
    return mapped


def curation_source_for_enqueue(canonical_id: str) -> str:
    """enqueue/precheck에 넣을 legacy-compatible source 값."""
    mapped = _CURATION_BY_CANONICAL.get((canonical_id or "").strip())
    if mapped is None:
        raise ValueError("unknown canonical source")
    return mapped


def allows_internal_processing(permission_status: str, *, enabled: bool) -> bool:
    return bool(enabled) and permission_status in INTERNAL_PROCESSING_PERMISSIONS


def allows_publish(permission_status: str, *, enabled: bool) -> bool:
    return bool(enabled) and permission_status in PUBLISH_PERMISSIONS


def permission_transition_allowed(from_status: str, to_status: str) -> bool:
    if from_status == to_status:
        return False
    return to_status in ALLOWED_PERMISSION_TRANSITIONS.get(from_status, frozenset())
