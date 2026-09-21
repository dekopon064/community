"""V1 gate facts parse/validate. capital/noncapital are not stored facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ingest.product_type import (
    PRODUCT_TYPE_EVENT_PROGRAM,
    PRODUCT_TYPE_LIVING_GUIDE,
    PRODUCT_TYPE_POLICY_REFERENCE,
    PRODUCT_TYPES,
)

GATE_FACTS_SCHEMA_VERSION = "gate-facts-v1"
ELIGIBILITY_SCOPES = frozenset({"nationwide", "specific", "unknown"})
FOREIGN_ELIGIBILITY_VALUES = frozenset({"eligible", "ineligible", "unknown"})
DELIVERY_MODES = frozenset({"online", "offline", "hybrid", "unknown"})

REGION_REQUIRED_KEYS = (
    "eligibility_scope",
    "eligibility_region_codes",
    "eligibility_region_evidence",
)
AUDIENCE_REQUIRED_KEYS = ("foreign_resident_eligibility",)
OPTIONAL_FACT_KEYS = ("schema_version", "delivery_mode")
FORBIDDEN_FACT_KEYS = frozenset(
    {
        "audience_relevance",
        "nationwide_or_online",
        "kr_japan_activity",
        "kr_jp_exchange",
        "activity_region_codes",
        "capital",
        "noncapital",
    }
)

_ONLINE_DELIVERY = (
    "온라인 참여",
    "온라인참여",
    "온라인으로 참여",
    "비대면 참여",
    "비대면참여",
    "화상 참여",
    "화상참여",
    "온라인 프로그램",
    "장소 제한 없는 온라인",
)
_OFFLINE_DELIVERY = (
    "현장 참여",
    "현장참여",
    "오프라인 참여",
    "오프라인참여",
    "대면 참여",
    "대면참여",
    "방문 참여",
)


@dataclass(frozen=True)
class GateFacts:
    schema_version: str
    eligibility_scope: str | None
    eligibility_region_codes: tuple[str, ...]
    eligibility_region_evidence: str | None
    foreign_resident_eligibility: str | None
    delivery_mode: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"schema_version": self.schema_version}
        if self.eligibility_scope is not None:
            payload["eligibility_scope"] = self.eligibility_scope
            payload["eligibility_region_codes"] = list(self.eligibility_region_codes)
            payload["eligibility_region_evidence"] = (
                self.eligibility_region_evidence or ""
            )
        if self.foreign_resident_eligibility is not None:
            payload["foreign_resident_eligibility"] = (
                self.foreign_resident_eligibility
            )
        if self.delivery_mode is not None:
            payload["delivery_mode"] = self.delivery_mode
        return payload


class InvalidGateFacts(ValueError):
    def __init__(self, code: str = "invalid_gate_facts") -> None:
        self.code = code
        super().__init__(code)


def extract_delivery_mode(text: str) -> str:
    body = text or ""
    online = any(phrase in body for phrase in _ONLINE_DELIVERY)
    offline = any(phrase in body for phrase in _OFFLINE_DELIVERY)
    if online and offline:
        return "hybrid"
    if online:
        return "online"
    if offline:
        return "offline"
    return "unknown"


def required_keys_for_product_type(product_type: str) -> tuple[str, ...]:
    if product_type == PRODUCT_TYPE_LIVING_GUIDE:
        return ()
    if product_type == PRODUCT_TYPE_EVENT_PROGRAM:
        return REGION_REQUIRED_KEYS
    if product_type == PRODUCT_TYPE_POLICY_REFERENCE:
        return REGION_REQUIRED_KEYS + AUDIENCE_REQUIRED_KEYS
    raise InvalidGateFacts("invalid_product_type")


def forbidden_keys_present(raw: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(raw) & FORBIDDEN_FACT_KEYS


def is_empty_facts(raw: object) -> bool:
    return raw is None or raw == {}


def parse_gate_facts(product_type: str, raw: object) -> GateFacts:
    if product_type not in PRODUCT_TYPES:
        raise InvalidGateFacts("invalid_product_type")
    if not isinstance(raw, dict):
        raise InvalidGateFacts("invalid_gate_facts")
    if raw == {}:
        raise InvalidGateFacts("gate_facts_incomplete")
    extra_forbidden = forbidden_keys_present(raw)
    if extra_forbidden:
        raise InvalidGateFacts("invalid_gate_facts")
    schema = str(raw.get("schema_version") or "").strip()
    if schema != GATE_FACTS_SCHEMA_VERSION:
        raise InvalidGateFacts("invalid_assessment_schema_version")

    allowed = {"schema_version", *REGION_REQUIRED_KEYS, *AUDIENCE_REQUIRED_KEYS, *OPTIONAL_FACT_KEYS}
    unknown_keys = set(raw) - allowed
    if unknown_keys:
        raise InvalidGateFacts("invalid_gate_facts")

    delivery_raw = raw.get("delivery_mode")
    delivery_mode = None if delivery_raw is None else str(delivery_raw).strip()
    if delivery_mode is not None and delivery_mode not in DELIVERY_MODES:
        raise InvalidGateFacts("invalid_gate_facts")

    required = required_keys_for_product_type(product_type)
    if product_type == PRODUCT_TYPE_LIVING_GUIDE:
        if any(key in raw for key in REGION_REQUIRED_KEYS + AUDIENCE_REQUIRED_KEYS):
            raise InvalidGateFacts("invalid_gate_facts")
        return GateFacts(
            schema_version=schema,
            eligibility_scope=None,
            eligibility_region_codes=(),
            eligibility_region_evidence=None,
            foreign_resident_eligibility=None,
            delivery_mode=delivery_mode,
        )

    missing = [key for key in required if key not in raw]
    if missing:
        raise InvalidGateFacts("gate_facts_incomplete")

    scope = str(raw.get("eligibility_scope") or "").strip()
    if scope not in ELIGIBILITY_SCOPES:
        raise InvalidGateFacts("invalid_gate_facts")
    codes_raw = raw.get("eligibility_region_codes")
    if not isinstance(codes_raw, (list, tuple)):
        raise InvalidGateFacts("invalid_gate_facts")
    codes = tuple(str(code).strip() for code in codes_raw)
    if any(not code for code in codes):
        raise InvalidGateFacts("invalid_gate_facts")
    if scope == "specific" and len(codes) < 1:
        raise InvalidGateFacts("invalid_gate_facts")
    if scope in {"nationwide", "unknown"} and codes:
        raise InvalidGateFacts("invalid_gate_facts")
    evidence = raw.get("eligibility_region_evidence")
    if evidence is None:
        evidence_text = ""
    elif isinstance(evidence, str):
        evidence_text = evidence
    else:
        raise InvalidGateFacts("invalid_gate_facts")
    if len(evidence_text) > 500:
        raise InvalidGateFacts("invalid_gate_facts")

    audience = None
    if product_type == PRODUCT_TYPE_POLICY_REFERENCE:
        audience = str(raw.get("foreign_resident_eligibility") or "").strip()
        if audience not in FOREIGN_ELIGIBILITY_VALUES:
            raise InvalidGateFacts("invalid_gate_facts")
    elif "foreign_resident_eligibility" in raw:
        raise InvalidGateFacts("invalid_gate_facts")

    return GateFacts(
        schema_version=schema,
        eligibility_scope=scope,
        eligibility_region_codes=codes,
        eligibility_region_evidence=evidence_text,
        foreign_resident_eligibility=audience,
        delivery_mode=delivery_mode,
    )


def is_complete_v1_facts(
    *,
    product_type: str,
    gate_facts: object,
    assessment_schema_version: str | None,
    evaluated_profile: str | None,
    evaluated_at: object,
    expected_profile: str,
) -> bool:
    if is_empty_facts(gate_facts):
        return False
    if assessment_schema_version != GATE_FACTS_SCHEMA_VERSION:
        return False
    if evaluated_profile != expected_profile:
        return False
    if evaluated_at is None:
        return False
    try:
        parsed = parse_gate_facts(product_type, gate_facts)
    except InvalidGateFacts:
        return False
    return parsed.schema_version == GATE_FACTS_SCHEMA_VERSION


def is_legacy_facts_row(
    *,
    gate_facts: object,
    assessment_schema_version: str | None,
    evaluated_profile: str | None,
    evaluated_at: object,
) -> bool:
    return (
        gate_facts is None
        and assessment_schema_version is None
        and evaluated_profile is None
        and evaluated_at is None
    )
