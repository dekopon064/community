"""Central V1 assessment pipeline. Store imports this; it does not own classifiers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from ingest.evaluate_gates import CAPITAL_V1_PROFILE, EvaluationResult, evaluate_capital_v1
from ingest.gate_facts import (
    GATE_FACTS_SCHEMA_VERSION,
    GateFacts,
    extract_delivery_mode,
)
from ingest.models import JobPlan, ObservationRecord
from ingest.product_type import (
    PRODUCT_TYPE_EVENT_PROGRAM,
    PRODUCT_TYPE_KIND_CONFIRMED,
    PRODUCT_TYPE_LIVING_GUIDE,
    PRODUCT_TYPE_POLICY_REFERENCE,
    ProductTypeClassification,
    propose_product_type,
)
from ingest.region import extract_eligibility_facts
from ingest.relevance import classify_foreign_resident_eligibility


@dataclass(frozen=True)
class AssessmentProposal:
    skip_product_type: bool
    product_type_classification: ProductTypeClassification | None
    gate_facts: GateFacts | None
    text: str


def _record_text(record: ObservationRecord) -> str:
    payload = record.normalized_payload or {}
    title = str(
        payload.get("plcyNm")
        or payload.get("pstTtl")
        or record.min_fields.get("plcyNm")
        or record.min_fields.get("pstTtl")
        or ""
    )
    body = str(payload.get("plain_text") or "")
    return f"{title}\n{body}".strip()


def _zip_and_extra(record: ObservationRecord) -> tuple[object, object]:
    payload = record.normalized_payload or {}
    zip_cd = payload.get("zipCd", record.min_fields.get("zipCd"))
    extra = payload.get("rgLcnCd")
    return zip_cd, extra


def _common_blocks_pipeline(record: ObservationRecord) -> bool:
    if not record.body_usable:
        return True
    if not record.has_source_url:
        return True
    return False


def _build_confirmed_facts(
    product_type: str,
    *,
    text: str,
    zip_cd: object,
    extra_region_raw: object,
) -> GateFacts:
    delivery_mode = extract_delivery_mode(text)
    if product_type == PRODUCT_TYPE_LIVING_GUIDE:
        return GateFacts(
            schema_version=GATE_FACTS_SCHEMA_VERSION,
            eligibility_scope=None,
            eligibility_region_codes=(),
            eligibility_region_evidence=None,
            foreign_resident_eligibility=None,
            delivery_mode=delivery_mode,
        )
    scope, codes, evidence = extract_eligibility_facts(
        zip_cd=zip_cd, text=text, extra_region_raw=extra_region_raw
    )
    audience = None
    if product_type == PRODUCT_TYPE_POLICY_REFERENCE:
        audience = classify_foreign_resident_eligibility(text)
    return GateFacts(
        schema_version=GATE_FACTS_SCHEMA_VERSION,
        eligibility_scope=scope,
        eligibility_region_codes=codes,
        eligibility_region_evidence=evidence,
        foreign_resident_eligibility=audience,
        delivery_mode=delivery_mode,
    )


def propose_assessment(
    record: ObservationRecord,
    *,
    source_kind: str | None = None,
) -> AssessmentProposal:
    """Common facts → product type proposal → gate facts. Does not write."""
    del source_kind
    text = _record_text(record)
    if _common_blocks_pipeline(record):
        return AssessmentProposal(
            skip_product_type=True,
            product_type_classification=None,
            gate_facts=None,
            text=text,
        )
    classification = propose_product_type(text)
    if classification.kind != PRODUCT_TYPE_KIND_CONFIRMED or not classification.product_type:
        return AssessmentProposal(
            skip_product_type=False,
            product_type_classification=classification,
            gate_facts=None,
            text=text,
        )
    zip_cd, extra = _zip_and_extra(record)
    facts = _build_confirmed_facts(
        classification.product_type,
        text=text,
        zip_cd=zip_cd,
        extra_region_raw=extra,
    )
    return AssessmentProposal(
        skip_product_type=False,
        product_type_classification=classification,
        gate_facts=facts,
        text=text,
    )


def evaluate_proposal(
    record: ObservationRecord, proposal: AssessmentProposal
) -> EvaluationResult:
    if proposal.skip_product_type:
        return evaluate_capital_v1(
            body_usable=record.body_usable,
            has_source_url=record.has_source_url,
            attachment_present=record.attachment_present,
            product_type=None,
            product_type_reasons=(),
            facts=None,
        )
    classification = proposal.product_type_classification
    confirmed = None
    reasons: tuple[str, ...] = ()
    if classification is not None:
        reasons = classification.reason_codes
        if (
            classification.kind == PRODUCT_TYPE_KIND_CONFIRMED
            and classification.product_type
        ):
            confirmed = classification.product_type
    facts_payload = None if proposal.gate_facts is None else proposal.gate_facts
    return evaluate_capital_v1(
        body_usable=record.body_usable,
        has_source_url=record.has_source_url,
        attachment_present=record.attachment_present,
        product_type=confirmed,
        product_type_reasons=reasons,
        facts=facts_payload,
    )


def _relationship_jobs(record: ObservationRecord) -> tuple[JobPlan, ...]:
    return tuple(
        job for job in record.jobs if job.stage == "relationship_review"
    )


def assess_observation(
    record: ObservationRecord,
    *,
    source_kind: str | None = None,
) -> ObservationRecord:
    """Connector normalize → proposal → Python evaluator. Used by tests and MemoryStore."""
    proposal = propose_assessment(record, source_kind=source_kind)
    evaluation = evaluate_proposal(record, proposal)
    classification_payload = None
    if proposal.product_type_classification is not None:
        classification_payload = proposal.product_type_classification.to_payload()
    facts_payload = None
    schema = None
    profile = None
    if proposal.gate_facts is not None:
        facts_payload = proposal.gate_facts.to_payload()
        schema = GATE_FACTS_SCHEMA_VERSION
        profile = CAPITAL_V1_PROFILE
    return replace(
        record,
        disposition=evaluation.disposition,  # type: ignore[arg-type]
        jobs=evaluation.jobs + _relationship_jobs(record),
        classifier_decision=None,
        product_type_classification=classification_payload,
        gate_facts=facts_payload,
        assessment_schema_version=schema,
        evaluated_profile=profile,
    )


def confirmed_product_type(proposal: AssessmentProposal) -> str | None:
    classification = proposal.product_type_classification
    if classification is None:
        return None
    if classification.kind != PRODUCT_TYPE_KIND_CONFIRMED:
        return None
    if classification.product_type in {
        PRODUCT_TYPE_EVENT_PROGRAM,
        PRODUCT_TYPE_POLICY_REFERENCE,
        PRODUCT_TYPE_LIVING_GUIDE,
    }:
        return classification.product_type
    return None


def proposal_payload(proposal: AssessmentProposal) -> Mapping[str, Any] | None:
    if proposal.product_type_classification is None:
        return None
    return proposal.product_type_classification.to_payload()
