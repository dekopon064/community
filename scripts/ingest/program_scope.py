"""Versioned program-scope evaluator mirrored by the isolated SQL contract.

Extraction is conservative and evidence-based; unknowns are not eligibility facts.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from ingest.connectors.seoul_reservation import KST
from ingest.evaluate_gates import EvaluationResult
from ingest.models import JobPlan, ObservationRecord

PROGRAM_SCHEMA = "program-scope-v1-local"
PROGRAM_PROFILE = "program_capital_v1_local"
CAPITAL = re.compile(r"서울(?:특별시)?|인천(?:광역시)?|경기도|경기\s+광주")
NONCAPITAL = re.compile(r"부산|대구|대전|울산|세종|강원|충북|충남|충청|전북|전남|전라|경북|경남|경상|제주|광주광역시|나주|화순")
SEOUL_DISTRICTS = frozenset("종로구 중구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 은평구 서대문구 마포구 양천구 강서구 구로구 금천구 영등포구 동작구 관악구 서초구 강남구 송파구 강동구".split())
LOCATION_LABELS = ("집결장소", "만나는장소", "만나는 장소", "운영장소", "개최지", "교육장소", "장소")
TARGET_LABELS = ("참가대상", "모집대상", "신청대상", "참여대상", "대상")


def _label_values(text: str, labels: tuple[str, ...]) -> tuple[str, ...]:
    lines = [line.strip().strip("| ") for line in text.splitlines() if line.strip().strip("| ")]
    values: list[str] = []
    for i, line in enumerate(lines):
        for label in labels:
            match = re.match(r"^[\[□■○ㅇ❐\s-]*" + re.escape(label) + r"[\]\s]*[:：]?\s*(.*)$", line)
            if match:
                value = match[1].strip("| ")
                if not value and i + 1 < len(lines):
                    value = lines[i + 1]
                if value:
                    values.append(value)
                break
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class ProgramFacts:
    schema_version: str
    content_kind: str
    application_actor: str
    delivery_mode: str
    activity_region: str
    activity_evidence: tuple[str, ...]
    residence_scope: str
    residence_evidence: tuple[str, ...]
    target_raw: str
    conditions: tuple[str, ...]
    application_methods: tuple[str, ...]
    fee_kind: str
    fee_amounts: tuple[str, ...]
    source_status: str
    conflicts: tuple[str, ...]
    missing: tuple[str, ...]
    editorial_pending: tuple[str, ...]
    period_evidence: tuple[str, ...] = ()
    official_url: str = ""
    description: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProgramAssessment:
    facts: ProgramFacts
    evaluation: EvaluationResult
    decision: str
    reason_codes: tuple[str, ...]
    # Local projection only, not a supported v1 RPC request.
    db_connected: bool = False


def extract_program_facts(record: ObservationRecord) -> ProgramFacts:
    payload = record.normalized_payload or {}
    raw = payload.get("provider_fields", {})
    body = str(payload.get("program_text") or "")
    title = str(payload.get("title") or "")
    target = str(raw.get("USETGTINFO") or "")
    targets = _label_values(body, TARGET_LABELS)
    audience = "\n".join((target, *targets))
    context = title + "\n" + body
    conditions = tuple(line for line in body.splitlines() if re.search(r"대상|동반|거주|연령|학년|만\s*\d+세|국적|증빙|등본|제출|언어|일본어|회차|가구당|신청|불가|제외|전용|조건|기간", line))
    conflicts: list[str] = []
    missing: list[str] = []
    if not record.body_usable:
        missing.append("attachment_dependent" if record.attachment_present else "program_description_missing")
    if not record.has_source_url:
        missing.append("missing_source_url")

    # Purpose, not a stray employment word in participant conditions.
    if re.search(r"취업\s*(?:지원|훈련|교육|준비|목적)|채용\s*(?:공고|모집|설명회)|인턴십|직업훈련", title) or re.search(r"(?:목적|내용)\s*[:：]\s*(?:취업|채용|직업훈련)", body):
        kind = "employment"
    elif re.search(r"기관\s*(?:운영지원|내부)|사업주\s*(?:운영지원|지원|전용)|시설\s*조성사업", context):
        kind = "institutional_business"
    elif re.search(r"정책|지원금|대출|금융\s*지원|보조금", title):
        kind = "policy_finance"
    elif re.search(r"체험|공예|교류|주민\s*활동|산책|탐방|숲해설|전시|해설|생활\s*교육|취미|인문|곤충|문화", body):
        kind = "program"
    else:
        kind = "unknown"

    # Names and group-only paperwork are not proof that individuals cannot apply.
    exclusive_pattern = r"개인\s*신청\s*(?:불가|불가능)|(?:학교|기관|단체)\s*(?:담당자)?\s*(?:만\s*(?:신청|참여)|전용)"
    institution = bool(re.search(exclusive_pattern, body + "\n" + audience))
    explicit_personal = bool(re.search(r"개인\s*신청\s*가능|개인\s*[/·,]\s*단체|개인과\s*단체\s*신청\s*가능", body))
    explicitly_exclusive = institution
    # Conditional group documents do not remove explicitly allowed individuals.
    if explicit_personal and not explicitly_exclusive:
        institution = False
    actor = "institution" if institution else "individual_or_group" if explicit_personal else "individual"
    if institution and explicit_personal:
        conflicts.append("application_actor_conflict")

    locations = _label_values(body, LOCATION_LABELS)
    online_pattern = r"온라인\s*(?:교육|프로그램|수업|참여)|비대면\s*(?:교육|수업|참여)|원격\s*(?:화상)?\s*(?:교육|수업)|ZOOM|줌\s*(?:수업|화상)"
    online = any(not re.match(r"\s*(?:은|는|이|가)?\s*(?:불가|불가능|없음|아님|진행하지)", context[match.end():])
                 for match in re.finditer(online_pattern, context, re.I))
    hybrid = bool(re.search(r"온\s*[/·+]?\s*오프라인|온라인.*오프라인|오프라인.*온라인|혼합\s*(?:교육|수업|진행)", context))
    mode = "hybrid" if hybrid else "online" if online else "offline" if locations else "unknown"
    activity = "not_applicable" if mode == "online" else "unknown"
    if mode in {"offline", "hybrid"}:
        joined = "\n".join(locations)
        cap, noncap = bool(CAPITAL.search(joined)), bool(NONCAPITAL.search(joined))
        if cap and noncap:
            activity = "mixed"
        elif noncap:
            activity = "noncapital"
        elif cap:
            activity = "capital"
        else:
            # Only relate provider area to an explicit matching activity place.
            place = str(raw.get("PLACENM") or "")
            if place and any(place in loc or loc in place for loc in locations) and raw.get("AREANM") in SEOUL_DISTRICTS:
                activity = "capital"

    residence_lines = tuple(line for line in (target, *targets) if re.search(r"거주|주민|시민|지역\s*제한|전국", line))
    residence = "not_stated"
    if residence_lines:
        value = "\n".join(residence_lines)
        cap, noncap = bool(CAPITAL.search(value)), bool(NONCAPITAL.search(value))
        if re.search(r"전국|지역\s*제한\s*없음", value):
            residence = "nationwide"
        elif cap and noncap:
            residence = "includes_capital"
        elif cap:
            residence = "capital"
        elif noncap:
            residence = "noncapital"
        else:
            residence = "unknown"
    if mode == "online" and residence == "not_stated":
        residence = "unknown"

    methods: list[str] = []
    if re.search(r"현장\s*(?:접수|참여)|방문\s*예약", body):
        methods.append("onsite")
    if re.search(r"인터넷.*(?:접수|예약)|인터넷\s*신청|온라인\s*(?:예약|접수)|예약방법.*공공서비스|신청방법.*공공서비스", body):
        methods.append("internet")
    if re.search(r"온라인\s*예약\s*불가|현장접수만", body):
        methods = [method for method in methods if method != "internet"]
    if re.search(r"전화\s*(?:예약|접수)", body):
        methods.append("phone")

    fee = {"무료": "free", "유료": "paid"}.get(raw.get("PAYATNM"), "unknown")
    fee_lines = _label_values(body, ("참가비", "참 가 비", "참가비용", "수강료", "분양가격", "비용"))
    fee_evidence = " ".join(fee_lines)
    amounts = tuple(dict.fromkeys(re.findall(r"\d[\d,]*(?:\.\d+)?\s*(?:만\s*)?원(?:\s*/\s*[^\s]+)?", fee_evidence)))
    if fee == "paid" and "무료" in fee_evidence:
        conflicts.append("fee_conflict")
    if fee == "free" and any(not re.match(r"0\s*원", amount) for amount in amounts):
        conflicts.append("fee_conflict")
    if not institution and target and "제한없음" in " ".join(targets) and re.search(r"유아|초등|어린이.*전용", target):
        conflicts.append("target_conflict")
    if re.search(r"(?:한국|대한민국)\s*국적자\s*(?:만|전용)|내국인\s*(?:만|전용)|외국인\s*(?:불가|제외)", audience + "\n" + body):
        actor = "nationality_excluded"
    if re.search(r"(?:중국|베트남|미국)\s*국적자\s*(?:만|전용)", audience):
        actor = "nationality_excluded"
    if re.search(r"주민등록등본|국적\s*증빙", body):
        missing.append("eligibility_document_unconfirmed")

    for date in payload.get("dates", {}).values():
        if date["status"] != "ok":
            missing.append("period_missing_or_unparsed")
    for begin, end in (("RCPTBGNDT", "RCPTENDDT"), ("SVCOPNBGNDT", "SVCOPNENDDT")):
        dates = payload.get("dates", {})
        a, b = dates.get(begin, {}).get("value"), dates.get(end, {}).get("value")
        # Compare day precision as days; a date-only end includes that date.
        if a and b and (a[:10] > b[:10] or (len(a) > 10 and len(b) > 10 and datetime.fromisoformat(a) > datetime.fromisoformat(b))):
            conflicts.append("period_order_conflict")
    period_evidence: list[str] = []
    for labels, fields in ((("접수기간", "신청기간", "모집기간"), ("RCPTBGNDT", "RCPTENDDT")),
                          (("운영기간", "진행기간"), ("SVCOPNBGNDT", "SVCOPNENDDT"))):
        for statement in _label_values(body, labels):
            period_evidence.append(statement)
            explicit = re.findall(r"(20\d{2})\s*[.년/-]\s*(\d{1,2})\s*[.월/-]\s*(\d{1,2})\s*일?", statement)
            if len(explicit) != 2:
                missing.append("body_period_needs_confirmation")
                continue
            try:
                parsed = [datetime(*map(int, parts)).date().isoformat() for parts in explicit]
            except ValueError:
                conflicts.append("invalid_body_date")
                continue
            for parsed_day, field_name in zip(parsed, fields):
                api_value = payload.get("dates", {}).get(field_name, {}).get("value")
                if api_value and parsed_day != api_value[:10]:
                    conflicts.append("body_api_period_conflict")
    for match in re.finditer(r"(20\d{2})\s*[.년/-]\s*(\d{1,2})\s*[.월/-]\s*(\d{1,2})\s*일?\s*\(([월화수목금토일])(?:요일)?\)", body):
        try:
            date = datetime(*map(int, match.group(1, 2, 3)))
            if "월화수목금토일"[date.weekday()] != match[4]:
                conflicts.append("date_weekday_conflict")
        except ValueError:
            conflicts.append("invalid_body_date")
    if re.search(r"(?:접수|예약)\s*마감|접수\s*종료", body) and payload.get("source_status") == "open":
        # A generic early-closing warning is not a current closed status.
        if re.search(r"(?:현재|상태)\s*[:：]?\s*(?:접수|예약)\s*(?:마감|종료)|(?:예약|접수)\s*(?:마감|종료)\s*(?:되었습니다|됐습니다|입니다|완료|됨)|^(?:예약|접수)\s*(?:마감|종료)[.!\s]*$", body, re.M):
            conflicts.append("source_status_conflict")
    # Paid and family/child programs are included; no ranking/subtype gate.
    editorial = []
    return ProgramFacts(PROGRAM_SCHEMA, kind, actor, mode, activity, locations, residence, residence_lines,
                        target, conditions, tuple(methods), fee, amounts, str(payload.get("source_status", "unknown")),
                        tuple(dict.fromkeys(conflicts)), tuple(dict.fromkeys(missing)), tuple(editorial), tuple(period_evidence),
                        str(payload.get("source_url") or ""), body)


def assess_seoul_program(record: ObservationRecord, *, now: datetime) -> ProgramAssessment:
    if now.tzinfo is None:
        raise ValueError("program_now_requires_timezone")
    if (record.normalized_payload or {}).get("source_id") != "seoul_reservation":
        raise ValueError("program_source_not_supported")
    facts = extract_program_facts(record)
    return assess_program_facts(facts, (record.normalized_payload or {}).get("dates", {}), now=now)


def assess_program_facts(facts: ProgramFacts, dates: dict[str, Any], *, now: datetime) -> ProgramAssessment:
    """Same structured facts/date contract as SQL; extraction remains separate."""
    if now.tzinfo is None:
        raise ValueError("program_now_requires_timezone")
    reasons: list[str] = []
    excluded: list[str] = []
    if facts.content_kind in {"employment", "institutional_business"}:
        excluded.append("service_scope_excluded")
    if facts.application_actor in {"institution", "nationality_excluded"} and "application_actor_conflict" not in facts.conflicts:
        excluded.append("individual_participation_excluded" if facts.application_actor == "institution" else "nationality_explicitly_excluded")
    if facts.activity_region in {"noncapital", "mixed"} and facts.delivery_mode != "online":
        excluded.append("activity_outside_capital")
    if facts.residence_scope == "noncapital":
        excluded.append("residence_outside_capital")
    deadline = dates.get("RCPTENDDT", {})
    expired = False
    if deadline.get("value"):
        if deadline["precision"] == "day":
            expired = now.astimezone(KST).date().isoformat() > deadline["value"]
        else:
            expired = now > datetime.fromisoformat(deadline["value"])
    if excluded:
        evaluation = EvaluationResult("non_target", (), "failed", "not_applicable", PROGRAM_PROFILE, PROGRAM_SCHEMA)
        return ProgramAssessment(facts, evaluation, "out_of_scope", tuple(excluded))
    reasons.extend(facts.missing)
    reasons.extend(facts.conflicts)
    # Re-derive important facts on every evaluation, including operator patches.
    # Diagnostic removal alone must not turn absent facts into a passing result.
    if not facts.official_url:
        reasons.append("missing_source_url")
    if len(facts.description.strip()) < 20 and not {"attachment_dependent", "program_description_missing"}.intersection(reasons):
        reasons.append("program_description_missing")
    if any(d.get("status") != "ok" for d in dates.values()) or len(dates) != 4:
        reasons.append("period_missing_or_unparsed")
    for begin, end in (("RCPTBGNDT", "RCPTENDDT"), ("SVCOPNBGNDT", "SVCOPNENDDT")):
        a, b = dates.get(begin, {}), dates.get(end, {})
        if a.get("value") and b.get("value"):
            if (a["value"][:10] > b["value"][:10] or
                    (a.get("precision") == b.get("precision") == "second" and datetime.fromisoformat(a["value"]) > datetime.fromisoformat(b["value"]))):
                reasons.append("period_order_conflict")
    if facts.fee_kind == "free" and any(re.match(r"[1-9]\d*[\d,]*(?:\.\d+)?\s*(?:만\s*)?원", a) for a in facts.fee_amounts):
        reasons.append("fee_conflict")
    if facts.content_kind != "program":
        reasons.append("policy_eligibility_unconfirmed" if facts.content_kind == "policy_finance" else "program_purpose_unconfirmed")
    if facts.delivery_mode == "unknown":
        reasons.append("delivery_mode_unknown")
    if facts.delivery_mode in {"offline", "hybrid"} and (facts.activity_region != "capital" or not facts.activity_evidence):
        reasons.append("activity_location_unknown")
    if facts.residence_scope == "unknown" or (facts.delivery_mode == "online" and
            (facts.residence_scope not in {"nationwide", "includes_capital", "capital"} or not facts.residence_evidence)):
        reasons.append("residence_scope_unknown")
    if facts.source_status == "unknown":
        reasons.append("source_status_unknown")
    reasons = list(dict.fromkeys(reasons))
    # Availability is not a service-scope or foreign-eligibility exclusion.
    # Unresolved conflicts still remain visible instead of being hidden by closure.
    unavailable = []
    if facts.source_status in {"reservation_closed", "application_closed"} or expired:
        unavailable.append("not_currently_accepting")
    operation_end = dates.get("SVCOPNENDDT", {})
    if operation_end.get("value"):
        ended = (now.astimezone(KST).date().isoformat() > operation_end["value"]
                 if operation_end["precision"] == "day" else now > datetime.fromisoformat(operation_end["value"]))
        if ended:
            unavailable.append("program_ended")
    start = dates.get("RCPTBGNDT", {})
    if start.get("value"):
        future = (now.astimezone(KST).date().isoformat() < start["value"]
                  if start["precision"] == "day" else now < datetime.fromisoformat(start["value"]))
        if future:
            unavailable.append("application_not_started")
    if unavailable and not reasons:
        evaluation = EvaluationResult("observe_only", (), "passed", "not_applicable", PROGRAM_PROFILE, PROGRAM_SCHEMA)
        return ProgramAssessment(facts, evaluation, "not_currently_available", tuple(unavailable))
    jobs = (JobPlan("content_review", tuple(reasons)),) if reasons else ()
    evaluation = EvaluationResult("observe_only" if reasons else "target", jobs,
                                  "review_required" if reasons else "passed", "not_applicable", PROGRAM_PROFILE, PROGRAM_SCHEMA)
    return ProgramAssessment(facts, evaluation, "review_required" if reasons else "in_scope", tuple(reasons))
