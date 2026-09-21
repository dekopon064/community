"""capital_v1 pure evaluator. MemoryStore authority; SQL mirror in unit B."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from ingest.gate_facts import GateFacts, parse_gate_facts
from ingest.models import JobPlan
from ingest.product_type import (
    PRODUCT_TYPE_EVENT_PROGRAM,
    PRODUCT_TYPE_LIVING_GUIDE,
    PRODUCT_TYPE_POLICY_REFERENCE,
)

# Profile id. Not product-type-v1 and not a trust score.
CAPITAL_V1_PROFILE = "capital_v1"
CAPITAL_V1_REGION_CODES = frozenset({"11", "28", "41"})
EVALUATOR_CONTRACT_ID = "capital_v1_evaluator"

GateStatus = Literal["passed", "failed", "review_required", "not_applicable"]
REASON_ATTACHMENT_DEPENDENT = "attachment_dependent"
REASON_MISSING_SOURCE_URL = "missing_source_url"
REASON_REGION_SCOPE_UNKNOWN = "region_scope_unknown"
REASON_RELEVANCE_UNCONFIRMED = "relevance_unconfirmed"


@dataclass(frozen=True)
class EvaluationResult:
    disposition: str
    jobs: tuple[JobPlan, ...]
    region_status: GateStatus
    audience_status: GateStatus
    evaluated_profile: str = CAPITAL_V1_PROFILE
    evaluator_contract_id: str = EVALUATOR_CONTRACT_ID


def evaluate_capital_v1(
    *,
    body_usable: bool,
    has_source_url: bool,
    attachment_present: bool,
    product_type: str | None,
    product_type_reasons: tuple[str, ...] = (),
    facts: Mapping[str, object] | GateFacts | None = None,
) -> EvaluationResult:
    """Result table 1–19. activity_location and delivery_mode are not inputs."""
    common = _evaluate_common(
        body_usable=body_usable,
        has_source_url=has_source_url,
        attachment_present=attachment_present,
    )
    if common is not None:
        return common

    if product_type is None:
        reasons = product_type_reasons or ("policy_lifecycle_uncertain",)
        return EvaluationResult(
            disposition="observe_only",
            jobs=_content_review(reasons),
            region_status="not_applicable",
            audience_status="not_applicable",
        )

    parsed = _coerce_facts(product_type, facts)
    region_status = _evaluate_region(product_type, parsed)
    audience_status = _evaluate_audience(product_type, parsed)

    if region_status == "failed" or audience_status == "failed":
        return EvaluationResult(
            disposition="non_target",
            jobs=(),
            region_status=region_status,
            audience_status=audience_status,
        )

    reasons: list[str] = []
    if region_status == "review_required":
        reasons.append(REASON_REGION_SCOPE_UNKNOWN)
    if audience_status == "review_required":
        reasons.append(REASON_RELEVANCE_UNCONFIRMED)
    if reasons:
        return EvaluationResult(
            disposition="region_review_required",
            jobs=_content_review(tuple(reasons)),
            region_status=region_status,
            audience_status=audience_status,
        )
    return EvaluationResult(
        disposition="target",
        jobs=(),
        region_status=region_status,
        audience_status=audience_status,
    )


def _evaluate_common(
    *,
    body_usable: bool,
    has_source_url: bool,
    attachment_present: bool,
) -> EvaluationResult | None:
    if not body_usable and attachment_present:
        reasons = [REASON_ATTACHMENT_DEPENDENT]
        if not has_source_url:
            reasons.append(REASON_MISSING_SOURCE_URL)
        return EvaluationResult(
            disposition="attachment_dependent",
            jobs=(
                JobPlan(stage="content_review", reason_codes=tuple(reasons)),
            ),
            region_status="not_applicable",
            audience_status="not_applicable",
        )
    if not body_usable:
        return EvaluationResult(
            disposition="non_target",
            jobs=(),
            region_status="not_applicable",
            audience_status="not_applicable",
        )
    if not has_source_url:
        return EvaluationResult(
            disposition="observe_only",
            jobs=_content_review((REASON_MISSING_SOURCE_URL,)),
            region_status="not_applicable",
            audience_status="not_applicable",
        )
    return None


def _content_review(reason_codes: tuple[str, ...]) -> tuple[JobPlan, ...]:
    return (JobPlan(stage="content_review", reason_codes=reason_codes),)


def _coerce_facts(
    product_type: str, facts: Mapping[str, object] | GateFacts | None
) -> GateFacts:
    if isinstance(facts, GateFacts):
        return facts
    if facts is None:
        raise ValueError("gate_facts_incomplete")
    return parse_gate_facts(product_type, facts)


def _evaluate_region(product_type: str, facts: GateFacts) -> GateStatus:
    if product_type == PRODUCT_TYPE_LIVING_GUIDE:
        return "not_applicable"
    if product_type not in {
        PRODUCT_TYPE_EVENT_PROGRAM,
        PRODUCT_TYPE_POLICY_REFERENCE,
    }:
        return "not_applicable"
    scope = facts.eligibility_scope
    if scope == "nationwide":
        return "passed"
    if scope == "unknown":
        return "review_required"
    codes = set(facts.eligibility_region_codes)
    if codes & CAPITAL_V1_REGION_CODES:
        return "passed"
    return "failed"


def _evaluate_audience(product_type: str, facts: GateFacts) -> GateStatus:
    if product_type != PRODUCT_TYPE_POLICY_REFERENCE:
        return "not_applicable"
    value = facts.foreign_resident_eligibility
    if value == "eligible":
        return "passed"
    if value == "ineligible":
        return "failed"
    return "review_required"


def facts_ignore_evaluator_non_inputs(facts: Mapping[str, object]) -> Mapping[str, object]:
    """delivery_mode is stored metadata and must not affect evaluation."""
    return facts
