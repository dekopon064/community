"""Small source-specific local rules. Not a DB facts/profile or an AI gate.

Preserve unresolved course relationships instead of building a schedule/NLP
engine. Employment is intentionally included only for this source.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ingest.connectors.myseoul_program import SOURCE, PARSER_VERSION, MySeoulContractError
from ingest.models import ObservationRecord

KST = timezone(timedelta(hours=9))
PROFILE = "myseoul-program-v1-local"
CAPITAL = re.compile(r"서울|인천|경기도|경기\s+(?:수원|성남|고양|광주|용인|부천|안양)")
NONCAPITAL = re.compile(r"부산|대구|대전|울산|세종|강원|충북|충남|충청|전북|전남|전라|경북|경남|경상|제주|광주광역시")
PROGRAM = re.compile(r"수업|교육|강좌|체험|취업\s*지원|취업\s*훈련|직업\s*훈련|안전\s*교육|한국어|교류\s*활동|자원봉사")
EVENT = re.compile(r"축제|기념\s*행사|공연|문화\s*행사")
PERSON = re.compile(r"개인|성인|어린이|아동|청소년|학부모|보호자|주민|외국인|국적자|일본인|누구나|가족|유학생")
INSTITUTION_ONLY = re.compile(r"개인\s*신청\s*(?:불가|불가능)|(?:학교|기관)\s*(?:담당자)?\s*만\s*신청\s*(?:가능|할\s*수)|(?:학교|기관)\s*전용\s*(?:신청|프로그램)")
INTERNAL = re.compile(r"기관\s*내부\s*(?:운영|담당자|행정)|사업주\s*전용|개인\s*이용\s*안내\s*없는\s*시설\s*조성")
DATE = re.compile(r"(?<!\d)(\d{4})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})[일.]?(?:\s*(?:\([월화수목금토일](?:요일)?\))?\s+(\d{1,2}):(\d{2}))?(?!\d)")


def values(payload: dict[str, Any], field: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(e["value"] for e in payload["labelled_evidence"] if e["field"] == field))


def parse_period(raw: str) -> dict[str, Any]:
    """Only explicit full dates. Keep raw; no year/clock inference or ID dates."""
    dates = list(DATE.finditer(raw))
    # A second clock without a second full date, ISO seconds or a course suffix
    # cannot be silently dropped. This small parser deliberately leaves such
    # windows unresolved instead of fabricating an end time.
    remainder = DATE.sub("", raw)
    if re.search(r"\d{1,2}:\d{2}|T\d|:\d{2}", remainder):
        return {"raw": raw, "status": "unparsed", "endpoints": []}
    endpoints = []
    for date in dates:
        year, month, day, hour, minute = date.groups()
        try:
            value = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), tzinfo=KST)
        except ValueError:
            return {"raw": raw, "status": "unparsed", "endpoints": []}
        endpoints.append({"value": value.isoformat() if hour is not None else value.date().isoformat(),
                          "precision": "minute" if hour is not None else "day"})
    if len(endpoints) not in {1, 2}:
        return {"raw": raw, "status": "unparsed", "endpoints": endpoints}
    # Date lists / multiple sessions are evidence, not an overall period.
    if len(endpoints) == 2 and not re.search(r"~|～|부터|–|—", raw[dates[0].end():dates[1].start()]):
        return {"raw": raw, "status": "unparsed", "endpoints": endpoints}
    if len(endpoints) == 2 and endpoints[0]["value"] > endpoints[1]["value"]:
        return {"raw": raw, "status": "unparsed", "endpoints": endpoints}
    return {"raw": raw, "status": "ok", "endpoints": endpoints}


def _boundary(endpoint: dict[str, str], *, end: bool) -> datetime:
    value = datetime.fromisoformat(endpoint["value"])
    if value.tzinfo is None:
        value = value.replace(tzinfo=KST)
    if end and endpoint["precision"] == "day":
        value += timedelta(days=1)
    return value


def _region(text: str) -> str:
    capital, other = bool(CAPITAL.search(text)), bool(NONCAPITAL.search(text))
    if capital and other:
        return "unknown"
    if capital:
        return "capital"
    return "noncapital" if other else "unknown"


GUIDANCE = {
    "description_missing": "이미지·첨부를 추정하지 말고 프로그램 설명을 확인해 주세요.",
    "target_missing": "명시된 참여 대상을 확인해 주세요. 국적 미표기 자체는 사유가 아닙니다.",
    "application_actor_unknown": "개인이 신청할 수 있는지 명시 근거를 확인해 주세요.",
    "delivery_mode_unknown": "실제 진행 방식과 과정별 안내를 확인해 주세요.",
    "course_modes_unresolved": "온라인·현장 과정이 여러 개입니다. 각 과정과 대상·장소를 대조해 주세요.",
    "activity_region_unknown": "운영기관 주소 대신 실제 개최지를 확인해 주세요.",
    "online_residence_unknown": "온라인 이용자의 거주 지역 범위를 확인해 주세요.",
    "category_unresolved": "본문의 주요 목적에 따라 프로그램/행사를 확인해 주세요.",
    "nationality_or_visa_unresolved": "일본인 거주자가 충족할 수 있는 명시된 국적·체류 조건을 확인해 주세요.",
    "application_method_missing": "원문의 신청 방법을 확인해 주세요. 별도 폼 URL은 필수가 아닙니다.",
    "application_period_unknown": "현재 신청 가능한 기간·상태 근거를 확인해 주세요.",
    "operation_period_unknown": "실제 운영기간과 회차를 확인해 주세요.",
    "fee_unknown": "수강료와 별도 비용을 구분해 확인해 주세요.",
    "fee_components_unresolved": "복합 비용의 종류별 구성을 확인해 주세요. 금액을 임의로 나누지 않습니다.",
    "source_fact_conflict": "같은 라벨·범위의 상단/본문 값이 다릅니다. 원문 근거를 대조해 주세요.",
    "application_state_unknown": "현재 모집·접수 상태를 확인해 주세요.",
}


def _fact_comparison(field: str, value: str) -> tuple[str, Any]:
    """Narrow equivalence only; evidence itself is never rewritten."""
    if field == "status":
        if re.fullmatch(r"(?:신청|접수|모집)\s*중|추가\s*모집\s*(?:중)?", value):
            return ("status", "open")
        if re.fullmatch(r"(?:신청|접수|모집)\s*(?:종료|마감)|예약\s*마감", value):
            return ("status", "closed")
    if field in {"tuition", "admission", "materials", "extra_fee"}:
        if value == "무료":
            return ("krw", 0)
        match = re.fullmatch(r"(\d+|\d{1,3}(?:,\d{3})+)\s*원(?:\s*\(\s*(수강료|입장료|재료비|부대비)\s*\))?", value)
        if match and (not match[2] or {"수강료": "tuition", "입장료": "admission", "재료비": "materials", "부대비": "extra_fee"}[match[2]] == field):
            return ("krw", int(match[1].replace(",", "")))
    return ("raw", value)


@dataclass(frozen=True)
class MySeoulAssessment:
    source: str
    profile: str
    observed: bool
    scope: str
    application: str
    quality: str
    public_category: str | None
    decision: str
    reason_codes: tuple[str, ...]
    facts: dict[str, Any]
    guidance: dict[str, str]
    db_connected: bool = False
    ai_executed: bool = False

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def assess_myseoul(record: ObservationRecord, *, now: datetime) -> MySeoulAssessment:
    if now.tzinfo is None:
        raise MySeoulContractError("evaluation_time_requires_timezone")
    payload = record.normalized_payload or {}
    if (payload.get("parser_version") != PARSER_VERSION
            or not payload.get("center_id") or not payload.get("program_id")):
        raise MySeoulContractError("myseoul_payload_required")
    body = payload["description"]
    target = "\n".join(values(payload, "target"))
    purpose = "\n".join(values(payload, "purpose"))
    venue = "\n".join(values(payload, "venue"))
    residence = "\n".join(values(payload, "residence"))
    mode_text = "\n".join(values(payload, "mode"))
    actor_text = "\n".join(values(payload, "actor"))
    conditions = tuple(payload["conditions"])
    missing: list[str] = []
    exclusions: list[str] = []
    conflicts: list[dict[str, Any]] = []
    evidence = payload["labelled_evidence"]

    # Canonical field aliases refer to the same overall fact. Class/session/
    # meeting labels remain separate; they are not overall period comparisons.
    for field in {e["field"] for e in evidence}:
        header = [e["value"] for e in evidence if e["field"] == field and e["origin"] == "header"]
        inline = [e["value"] for e in evidence if e["field"] == field and e["origin"] == "body"]
        if not header or not inline or set(header) == set(inline):
            continue
        if {_fact_comparison(field, v) for v in header} == {_fact_comparison(field, v) for v in inline}:
            continue
        if field in {"application", "operation"}:
            comparable = all(parse_period(v)["status"] == "ok" for v in header + inline)
            same = {json_period(v) for v in header} == {json_period(v) for v in inline}
            if not comparable or same:
                continue
        if field in {"application", "operation", "target", "mode", "venue", "status", "tuition", "materials", "admission", "extra_fee", "application_method"}:
            conflicts.append({"field": field, "labels": list(dict.fromkeys(e["label"] for e in evidence if e["field"] == field)),
                              "header": header, "body": inline})

    if not record.body_usable:
        missing.append("description_missing")
    if not target:
        missing.append("target_missing")
    if INSTITUTION_ONLY.search(body + "\n" + target + "\n" + actor_text):
        actor = "institution_only"
        exclusions.append("institution_only")
    elif PERSON.search(target + "\n" + actor_text):
        actor = "individual"
    else:
        actor = "unknown"
        missing.append("application_actor_unknown")
    if INTERNAL.search(purpose + "\n" + target):
        exclusions.append("internal_business")

    qualification = "\n".join((target, *values(payload, "condition"), *conditions))
    if re.search(r"(?:대한민국|한국)\s*(?:국적자|국민)\s*(?:만|전용)|(?:한국인|내국인)\s*만|일본(?:인|\s*국적자)\s*(?:참여|신청)?\s*(?:불가|제외)", qualification):
        exclusions.append("explicit_japanese_ineligible")
    elif re.search(r"(?:중국|베트남|미국|필리핀|몽골)\s*(?:국적자|인)\s*만", qualification):
        exclusions.append("explicit_other_nationality_only")
    elif (re.search(r"비자|체류\s*자격|[A-Z]-\d", qualification)
          or (re.search(r"국적자\s*만", qualification)
              and not re.search(r"일본\s*국적자\s*만", qualification))):
        missing.append("nationality_or_visa_unresolved")

    # Purpose and activity evidence must agree; a title/category keyword alone
    # is never enough. Both purposes => unresolved composite category.
    context = payload["title"] + "\n" + (payload["source_category"] or "")
    program = bool(PROGRAM.search(purpose or body) and PROGRAM.search(context + "\n" + purpose))
    event = bool(EVENT.search(purpose or body) and EVENT.search(context + "\n" + purpose))
    category = "program" if program and not event else "event" if event and not program else None
    if category is None:
        missing.append("category_unresolved")

    if re.search(r"혼합|온\s*[·/+-]\s*오프라인|온라인과\s*오프라인\s*병행", mode_text):
        mode = "mixed"
    elif "온라인" in mode_text and re.search(r"오프라인|현장", mode_text):
        mode = "course_unresolved"
        missing.append("course_modes_unresolved")
    elif re.search(r"온라인|비대면|Zoom|줌", mode_text, re.I):
        mode = "online"
    elif re.search(r"오프라인|현장", mode_text):
        mode = "offline"
    elif mode_text or re.search(r"온라인|비대면|Zoom|줌", body, re.I):
        mode = "unknown"
        missing.append("delivery_mode_unknown")
    elif venue:
        mode = "offline"
    else:
        mode = "unknown"
        missing.append("delivery_mode_unknown")
    activity_region = _region(venue)
    online_scope = residence or target
    unrestricted = bool(re.search(r"전국|지역\s*제한\s*없|거주\s*제한\s*없|국내\s*거주", online_scope))
    residence_region = _region(online_scope)
    if mode == "online":
        if unrestricted or residence_region == "capital" or re.search(r"수도권\s*(?:포함|거주자)", online_scope):
            pass
        elif residence_region == "noncapital" and re.search(r"거주자\s*(?:만|전용)|주민\s*(?:만|전용)", online_scope):
            exclusions.append("online_noncapital_only")
        else:
            missing.append("online_residence_unknown")
    elif mode in {"offline", "mixed"}:
        if activity_region == "noncapital":
            exclusions.append("noncapital_venue")
        elif activity_region != "capital":
            missing.append("activity_region_unknown")
        if residence_region == "noncapital" and re.search(r"거주자\s*(?:만|전용)|주민\s*(?:만|전용)", online_scope):
            exclusions.append("capital_residents_ineligible")

    periods = {}
    for field in ("application", "operation"):
        entries = [{**parse_period(e["value"]), "origin": e["origin"], "label": e["label"]}
                   for e in evidence if e["field"] == field]
        periods[field] = entries
    usable_app = [p for p in periods["application"] if p["status"] == "ok"]
    usable_op = [p for p in periods["operation"] if p["status"] == "ok"]
    if not usable_op or any(p["status"] != "ok" for p in periods["operation"]):
        missing.append("operation_period_unknown")
    methods = values(payload, "application_method")
    if not methods:
        missing.append("application_method_missing")
    fees = [{"component": field, "evidence": list(values(payload, field))}
            for field in ("tuition", "materials", "admission", "extra_fee") if values(payload, field)]
    if any(e["field"] == "extra_fee" and e["label"] in {"참가비", "비용"}
           and len(set(re.findall(r"수강료|입장료|재료비", e["value"]))) > 1 for e in evidence):
        missing.append("fee_components_unresolved")
    if not fees or any(not re.search(r"무료|\d[\d,]*\s*원|별도\s*(?:부담|납부)", value)
                       for fee in fees for value in fee["evidence"]):
        missing.append("fee_unknown")
    statuses = values(payload, "status")
    status_text = "\n".join(statuses)
    application = "unknown"
    application_reasons = []
    if any(p["status"] != "ok" for p in periods["application"]):
        missing.append("application_period_unknown")
    if re.search(r"접수\s*종료|모집\s*종료|예약\s*마감|접수\s*마감|신청\s*(?:마감|종료)", status_text):
        application = "closed"
        application_reasons.append("application_closed")
    elif usable_app:
        period = usable_app[0]
        start, end = period["endpoints"][0], period["endpoints"][-1]
        # A single date is an all-day application window if day precision.
        if now < _boundary(start, end=False):
            application = "not_started"
        else:
            closed = (now >= _boundary(end, end=True) if end["precision"] == "day"
                      else now > _boundary(end, end=True))
            application = "closed" if closed else "open"
        if application != "open":
            application_reasons.append("application_" + application)
    elif re.search(r"접수\s*중|모집\s*중|신청\s*중|추가\s*모집|현장\s*접수", status_text):
        application = "open"
    else:
        missing.append("application_period_unknown")
    # Already-started classes may still accept additional applications.
    if usable_op:
        end = usable_op[0]["endpoints"][-1]
        expired = now >= _boundary(end, end=True) if end["precision"] == "day" else now > _boundary(end, end=True)
        if expired:
            application = "ended"
            application_reasons.append("operation_ended")
    if conflicts:
        missing.append("source_fact_conflict")
        if any(c["field"] in {"application", "operation", "status"} for c in conflicts):
            application = "unknown"
            application_reasons = []
    if application == "unknown":
        missing.append("application_state_unknown")
    scope_unknown = {"target_missing", "application_actor_unknown", "delivery_mode_unknown",
                     "course_modes_unresolved", "activity_region_unknown", "online_residence_unknown",
                     "category_unresolved", "nationality_or_visa_unresolved"}
    scope = "excluded" if exclusions else "unknown" if scope_unknown.intersection(missing) else "included"
    quality = "conflict" if conflicts else "insufficient" if missing else "sufficient"
    reasons = tuple(dict.fromkeys(exclusions + missing + application_reasons))
    decision = ("exclude" if exclusions else "review" if missing else
                "exclude" if application != "open" else "include")
    facts = {
        "target": target, "residence": residence, "age": values(payload, "age"),
        "companion": values(payload, "companion"), "language": values(payload, "language"),
        "conditions": conditions, "purpose": purpose, "venue": venue,
        "delivery_mode": mode, "activity_region": activity_region,
        "application_actor": actor, "fees": fees, "periods": periods,
        "session_evidence": tuple(line for line in body.splitlines()
                                  if re.search(r"회차|요일|매주|총\s*\d+회|\d{1,2}:\d{2}|반\s*[:：]|과정\s*[:：]", line)),
        "meeting_evidence": values(payload, "meeting") + values(payload, "meeting_venue"),
        "application_methods": methods, "application_links": payload["application_links"],
        "source_status": statuses, "source_category": payload["source_category"],
        "early_close_evidence": tuple(c for c in conditions if re.search(r"선착순|조기\s*마감", c)),
        "capacity_raw": values(payload, "capacity"), "capacity_value": None,
        "missing": tuple(dict.fromkeys(missing)), "conflicts": conflicts,
        "evidence": evidence, "source_revision": record.revision_hash,
        "parser_version": payload["parser_version"],
    }
    return MySeoulAssessment(SOURCE, PROFILE, True, scope, application, quality, category,
                             decision, reasons, facts,
                             {r: GUIDANCE[r] for r in reasons if r in GUIDANCE})


def json_period(raw: str) -> tuple[tuple[str, str], ...]:
    return tuple((v["value"], v["precision"]) for v in parse_period(raw)["endpoints"])
