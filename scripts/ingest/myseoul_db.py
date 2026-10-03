"""My Seoul+ storage contract. Explicit RPC injection; no environment/network/AI.

Initial extraction retains its raw diagnostics. Operator resolution is done by
SQL against current facts, not by re-running extraction over the observation.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Callable

from ingest.connectors.myseoul_program import SOURCE, PARSER_VERSION, REVISION_CONTRACT
from ingest.models import ObservationRecord
from ingest.myseoul_scope import KST, _boundary, _fact_comparison, assess_myseoul

SCHEMA = "myseoul-program-facts-v1-local"
SCOPE_UNKNOWN = {"target_missing", "application_actor_unknown", "delivery_mode_unknown",
                 "course_modes_unresolved", "activity_region_unknown", "online_residence_unknown",
                 "category_unresolved", "nationality_or_visa_unresolved"}


def myseoul_facts(record: ObservationRecord, *, now: datetime) -> dict[str, Any]:
    p = record.normalized_payload or {}
    if p.get("source_language") != "ko" or p.get("revision_contract") != REVISION_CONTRACT:
        raise ValueError("myseoul_contract_not_supported")
    result = assess_myseoul(record, now=now)
    # JSON round-trip converts immutable tuples; original extraction is untouched.
    import json
    f = json.loads(json.dumps(result.facts, ensure_ascii=False))
    issues = [{"code": code, "field": code, "evidence": []}
              for code in f["missing"] if code not in {"source_fact_conflict", "application_state_unknown"}]
    issues += [{"code": "source_fact_conflict:" + c["field"], "field": c["field"],
                "evidence": c["header"] + c["body"]} for c in f["conflicts"]]
    f.update(schema_version=SCHEMA, revision_contract=REVISION_CONTRACT,
             description=p["description"], official_url=p["official_url"],
             public_category=result.public_category or "unknown", issues=issues,
             scope_exclusions=[r for r in result.reason_codes if r in {
                 "institution_only", "internal_business", "explicit_japanese_ineligible",
                 "explicit_other_nationality_only", "online_noncapital_only",
                 "noncapital_venue", "capital_residents_ineligible"}],
             activity_evidence=[f["venue"]] if f["venue"] else [],
             residence_scope="includes_capital" if result.facts["delivery_mode"] == "online"
                 and "online_residence_unknown" not in result.reason_codes
                 and "online_noncapital_only" not in result.reason_codes else "unknown",
             residence_evidence=[f["residence"] or f["target"]] if result.facts["delivery_mode"] == "online" else [],
             qualification_note="")
    return f


def evaluate_myseoul_facts(f: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Mirror SQL decisions on structured facts, preserving extraction issues.

Raw HTML/source keyword interpretation remains the connector/local scope's job.
This function and SQL recalculate temporal gates from the same period endpoints.
"""
    if now.tzinfo is None:
        raise ValueError("evaluation_time_requires_timezone")
    reasons = [x["code"] for x in f["issues"]]
    exclusions = list(f["scope_exclusions"])
    if f["application_actor"] == "institution_only":
        exclusions.append("institution_only")
    if len(f["description"].strip()) < 20:
        reasons.append("description_missing")
    if not f["target"].strip():
        reasons.append("target_missing")
    if f["application_actor"] == "unknown":
        reasons.append("application_actor_unknown")
    if f["public_category"] == "unknown":
        reasons.append("category_unresolved")
    mode = f["delivery_mode"]
    if mode in {"unknown", "course_unresolved"}:
        reasons.append("course_modes_unresolved" if mode == "course_unresolved" else "delivery_mode_unknown")
    if mode in {"offline", "mixed"}:
        if f["activity_region"] == "noncapital":
            exclusions.append("noncapital_venue")
        elif f["activity_region"] != "capital" or not f["activity_evidence"] or not f["venue"].strip():
            reasons.append("activity_region_unknown")
    if mode == "online":
        if f["residence_scope"] == "noncapital_only":
            exclusions.append("online_noncapital_only")
        elif f["residence_scope"] not in {"nationwide", "includes_capital", "capital"} or not f["residence_evidence"]:
            reasons.append("online_residence_unknown")
    if not f["application_methods"]:
        reasons.append("application_method_missing")
    import re
    if not f["fees"] or any(not re.search(r"무료|\d[\d,]*\s*원|별도\s*(?:부담|납부)", v)
                            for fee in f["fees"] for v in fee["evidence"]):
        reasons.append("fee_unknown")
    for component in {fee["component"] for fee in f["fees"]}:
        if len({_fact_comparison(component, v) for fee in f["fees"] if fee["component"] == component
                for v in fee["evidence"]}) > 1:
            reasons.append("source_fact_conflict:" + component)
    periods = f["periods"]
    usable = {k: [p for p in periods[k] if p["status"] == "ok"] for k in ("application", "operation")}
    for k in ("application", "operation"):
        if any(p["status"] != "ok" for p in periods[k]) or k == "operation" and not usable[k]:
            reasons.append(k + "_period_unknown")
        if len({tuple((e["value"], e["precision"]) for e in p["endpoints"]) for p in usable[k]}) > 1:
            reasons.append("source_fact_conflict:" + k)
    if len({_fact_comparison("status", v) for v in f["source_status"]}) > 1:
        reasons.append("source_fact_conflict:status")
    application = "unknown"
    status = "\n".join(f["source_status"])
    if re.search(r"접수\s*종료|모집\s*종료|예약\s*마감|접수\s*마감|신청\s*(?:마감|종료)", status):
        application = "closed"
    elif usable["application"]:
        p = usable["application"][0]["endpoints"]
        end = _boundary(p[-1], end=True)
        application = ("not_started" if now < _boundary(p[0], end=False) else "closed"
                       if (now >= end if p[-1]["precision"] == "day" else now > end) else "open")
    elif re.search(r"접수\s*중|모집\s*중|신청\s*중|추가\s*모집|현장\s*접수", status):
        application = "open"
    else:
        reasons.append("application_period_unknown")
    if usable["operation"]:
        p = usable["operation"][0]["endpoints"][-1]
        end = _boundary(p, end=True)
        if now >= end if p["precision"] == "day" else now > end:
            application = "ended"
    if set(reasons).intersection({"source_fact_conflict:application", "source_fact_conflict:operation", "source_fact_conflict:status"}):
        application = "unknown"
    if application == "unknown":
        reasons.append("application_state_unknown")
    reasons = list(dict.fromkeys(reasons))
    exclusions = list(dict.fromkeys(exclusions))
    scope = "excluded" if exclusions else "unknown" if SCOPE_UNKNOWN.intersection(reasons) else "included"
    quality = "conflict" if any(r.startswith(("source_fact_conflict:", "source_change_conflict:")) for r in reasons) else "insufficient" if reasons else "sufficient"
    decision = "out_of_scope" if exclusions else "review_required" if reasons else "in_scope" if application == "open" else "not_currently_available"
    final = exclusions + reasons + (["operation_ended" if application == "ended" else "application_" + application]
                                   if application in {"ended", "closed", "not_started"} else [])
    return {"decision": decision, "disposition": "non_target" if exclusions else "target" if decision == "in_scope" else "observe_only",
            "scope": scope, "application": application, "quality": quality, "public_category": f["public_category"],
            "reasons": list(dict.fromkeys(final)), "ai_status": "blocked"}


def myseoul_rpc_item(record: ObservationRecord, *, now: datetime) -> dict[str, Any]:
    p = record.normalized_payload or {}
    if p.get("parser_version") != PARSER_VERSION:
        raise ValueError("myseoul_parser_not_supported")
    item = copy.deepcopy(record.to_rpc_item())
    item.update(disposition="observe_only", jobs=[], relationships=[],
                myseoul_facts=myseoul_facts(record, now=now))
    return item


class MySeoulObservationAdapter:
    def __init__(self, rpc: Callable[[str, dict[str, Any]], Any]):
        self.rpc = rpc

    def observe(self, run_id: str, records: list[ObservationRecord], checkpoint: dict[str, Any] | None):
        if not 1 <= len(records) <= 40:
            raise ValueError("myseoul_batch_size_invalid")
        items = [myseoul_rpc_item(r, now=datetime.now(KST)) for r in records]
        try:
            return self.rpc("observe_myseoul_program", {"p_run_id": run_id, "p_items": items,
                                                       "p_next_checkpoint": checkpoint})
        except Exception:
            raise RuntimeError("myseoul_observation_failed") from None

    def finish(self, run_id: str, summary: dict[str, Any], *, requests: int, batches: int):
        try:
            return self.rpc("finish_myseoul_run", {"p_run_id": run_id, "p_summary": summary,
                                                  "p_requests": requests, "p_batches": batches})
        except Exception:
            raise RuntimeError("myseoul_finish_failed") from None
