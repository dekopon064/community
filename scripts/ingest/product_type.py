"""Revision-scoped product_type classification. Independent of source_kind and relevance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

PRODUCT_TYPE_EVENT_PROGRAM = "event_program"
PRODUCT_TYPE_POLICY_REFERENCE = "policy_reference"
PRODUCT_TYPE_LIVING_GUIDE = "living_guide"
PRODUCT_TYPE_REVIEW_STAGE = "product_type_review"
PRODUCT_TYPE_RULE_VERSION = "product-type-v1"
PRODUCT_TYPE_KIND_CONFIRMED = "confirmed"
PRODUCT_TYPE_KIND_REVIEW = "review"
PRODUCT_TYPE_ORIGIN_CLASSIFIER = "classifier"
PRODUCT_TYPE_ORIGIN_HUMAN = "human"
PRODUCT_TYPE_ACTION_CONFIRM = "confirm"
PRODUCT_TYPE_ACTION_OVERRIDE = "override"
PRODUCT_TYPE_ACTION_ROLLBACK = "rollback"
REASON_CONTENT_FIXED = "content_fixed_event_program"
REASON_POLICY_EVENT = "policy_period_event_program"
REASON_POLICY_REFERENCE = "policy_standing_reference"
REASON_POLICY_UNCERTAIN = "policy_lifecycle_uncertain"
REASON_POLICY_CONFLICT = "policy_lifecycle_conflict"
REASON_END_DATE_ABSENT = "end_date_absent_not_reference"

PRODUCT_TYPES: frozenset[str] = frozenset(
    {
        PRODUCT_TYPE_EVENT_PROGRAM,
        PRODUCT_TYPE_POLICY_REFERENCE,
        PRODUCT_TYPE_LIVING_GUIDE,
    }
)
# V1 classifier may confirm event/policy only. living_guide is stored, never auto-proposed.
PROPOSED_PRODUCT_TYPES: frozenset[str] = frozenset(
    {PRODUCT_TYPE_EVENT_PROGRAM, PRODUCT_TYPE_POLICY_REFERENCE}
)
PRODUCT_TYPE_ORIGINS: frozenset[str] = frozenset(
    {PRODUCT_TYPE_ORIGIN_CLASSIFIER, PRODUCT_TYPE_ORIGIN_HUMAN}
)
PRODUCT_TYPE_ACTIONS: frozenset[str] = frozenset(
    {
        PRODUCT_TYPE_ACTION_CONFIRM,
        PRODUCT_TYPE_ACTION_OVERRIDE,
        PRODUCT_TYPE_ACTION_ROLLBACK,
    }
)
PRODUCT_TYPE_KINDS: frozenset[str] = frozenset(
    {PRODUCT_TYPE_KIND_CONFIRMED, PRODUCT_TYPE_KIND_REVIEW}
)
PRODUCT_TYPE_CLASSIFICATION_KEYS: frozenset[str] = frozenset(
    {
        "kind",
        "product_type",
        "reason_codes",
        "period_signals",
        "rule_version",
    }
)

_EVENT_SIGNALS: tuple[str, ...] = (
    "신청",
    "접수",
    "마감",
    "개최",
    "설명회",
    "행사",
    "교육일",
    "기수",
    "모집",
    "참석",
    "이번 회차",
)
_STANDING_SIGNALS: tuple[str, ...] = (
    "상시",
    "연중",
    "지속 시행",
    "지원 자격",
    "이용 방법",
    "자격 요건",
    "혜택 안내",
    "제도",
    "절차",
)
_END_DATE_ABSENT_SIGNALS: tuple[str, ...] = (
    "종료일 없음",
    "기한 없음",
    "마감일 없음",
)


@dataclass(frozen=True)
class ProductTypeClassification:
    kind: str
    product_type: str | None
    reason_codes: tuple[str, ...]
    period_signals: tuple[str, ...]
    rule_version: str = PRODUCT_TYPE_RULE_VERSION

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "reason_codes": list(self.reason_codes),
            "period_signals": list(self.period_signals),
            "rule_version": self.rule_version,
        }
        if self.kind == PRODUCT_TYPE_KIND_CONFIRMED:
            payload["product_type"] = self.product_type
        return payload


def _matched_signals(text: str, signals: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(signal for signal in signals if signal in text)


def classify_content_product_type() -> ProductTypeClassification:
    """v3 content lock helper. V1 assessment does not call this."""
    return ProductTypeClassification(
        kind=PRODUCT_TYPE_KIND_CONFIRMED,
        product_type=PRODUCT_TYPE_EVENT_PROGRAM,
        reason_codes=(REASON_CONTENT_FIXED,),
        period_signals=(),
    )


def propose_product_type(text: str) -> ProductTypeClassification:
    """V1 product type proposal. living_guide is never auto-confirmed."""
    return classify_policy_product_type(text)


def classify_policy_product_type(text: str) -> ProductTypeClassification:
    body = text or ""
    event = _matched_signals(body, _EVENT_SIGNALS)
    standing = _matched_signals(body, _STANDING_SIGNALS)
    absent = _matched_signals(body, _END_DATE_ABSENT_SIGNALS)
    period_signals = event + standing + absent
    if absent:
        return ProductTypeClassification(
            kind=PRODUCT_TYPE_KIND_REVIEW,
            product_type=None,
            reason_codes=(REASON_END_DATE_ABSENT, REASON_POLICY_UNCERTAIN),
            period_signals=period_signals,
        )
    if event and standing:
        return ProductTypeClassification(
            kind=PRODUCT_TYPE_KIND_REVIEW,
            product_type=None,
            reason_codes=(REASON_POLICY_CONFLICT, REASON_POLICY_UNCERTAIN),
            period_signals=period_signals,
        )
    if event:
        return ProductTypeClassification(
            kind=PRODUCT_TYPE_KIND_CONFIRMED,
            product_type=PRODUCT_TYPE_EVENT_PROGRAM,
            reason_codes=(REASON_POLICY_EVENT,),
            period_signals=period_signals,
        )
    if standing:
        return ProductTypeClassification(
            kind=PRODUCT_TYPE_KIND_CONFIRMED,
            product_type=PRODUCT_TYPE_POLICY_REFERENCE,
            reason_codes=(REASON_POLICY_REFERENCE,),
            period_signals=period_signals,
        )
    return ProductTypeClassification(
        kind=PRODUCT_TYPE_KIND_REVIEW,
        product_type=None,
        reason_codes=(REASON_POLICY_UNCERTAIN,),
        period_signals=period_signals,
    )


def product_type_classification_payload(
    classification: ProductTypeClassification,
) -> dict[str, Any]:
    return classification.to_payload()


def parse_product_type_classification(raw: Mapping[str, Any]) -> ProductTypeClassification:
    kind = str(raw.get("kind") or "").strip()
    product_type = raw.get("product_type")
    reasons_raw = raw.get("reason_codes", ())
    signals_raw = raw.get("period_signals", ())
    rule_version = str(raw.get("rule_version") or "").strip()
    confirmed_type = None if product_type is None else str(product_type).strip()
    return ProductTypeClassification(
        kind=kind,
        product_type=confirmed_type or None,
        reason_codes=tuple(str(code) for code in reasons_raw),
        period_signals=tuple(str(signal) for signal in signals_raw),
        rule_version=rule_version,
    )
