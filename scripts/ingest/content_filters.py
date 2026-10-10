"""Local content-filters-v1 boundary. No I/O, discovery policy or current-facts edits.

Evidence names only top-level retained payload/observed-facts fields accepted by
Build's SQL. Claim data is an immutable server snapshot, never re-extracted.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

SCHEMA = "content-filters-v1"
KEYS = ("topic", "location", "delivery", "audience", "spaceKind", "application", "schedule")
PROGRAM_TOPICS = {"language_learning", "culture_experience", "employment_career",
                  "daily_safety", "community_exchange", "other"}
EVENT_TOPICS = {"festival_exchange", "culture_arts", "lecture_commemoration", "other"}
DISTRICTS = {
    "11": "종로구 중구 용산구 성동구 광진구 동대문구 동작구 중랑구 성북구 강북구 도봉구 노원구 은평구 서대문구 마포구 양천구 강서구 구로구 금천구 영등포구 관악구 서초구 강남구 송파구 강동구".split(),
    "41": "수원시 성남시 의정부시 안양시 부천시 광명시 평택시 동두천시 안산시 고양시 과천시 구리시 남양주시 오산시 시흥시 군포시 의왕시 하남시 용인시 파주시 이천시 안성시 김포시 화성시 광주시 양주시 포천시 여주시 연천군 가평군 양평군".split(),
    "28": "제물포구 영종구 미추홀구 연수구 남동구 부평구 계양구 서구 검단구 강화군 옹진군".split(),
}
KST = timezone(timedelta(hours=9))


def field(value: Any = None, status: str | None = None) -> dict:
    return {"status": status or ("unknown" if value is None else "known"), "value": value}


def empty_filters(category: str) -> dict:
    required = {"program": {"topic", "location", "delivery", "audience", "application"},
                "event": {"topic", "location", "schedule"},
                "youth_space": {"location", "spaceKind"}}[category]
    return {"schema": SCHEMA, "category": category,
            **{k: field(status="unknown" if k in required else "not_applicable") for k in KEYS}}


def _exact(v: Any, keys: set[str]) -> dict:
    if type(v) is not dict or set(v) != keys:
        raise ValueError("invalid_content_filters")
    return v


def _text(v: Any, maximum: int = 500) -> str:
    if type(v) is not str or len(v) > maximum or re.search(r"[<>\x00-\x08\x0b\x0c\x0e-\x1f]", v):
        raise ValueError("invalid_content_filters")
    return v


def _day(v: Any) -> str:
    _text(v, 10)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) or not "1900-01-01" <= v <= "2199-12-31" or date.fromisoformat(v).isoformat() != v:
        raise ValueError("invalid_content_filters")
    return v


def endpoint(v: Any) -> dict:
    _exact(v, {"value", "precision"})
    value, precision = v["value"], v["precision"]
    _text(value, 25)
    _day(value[:10])
    if precision == "day":
        if len(value) != 10:
            raise ValueError("invalid_content_filters")
    elif precision in {"minute", "second"}:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\+09:00", value) or precision == "minute" and value[17:19] != "00":
            raise ValueError("invalid_content_filters")
    else:
        raise ValueError("invalid_content_filters")
    return copy.deepcopy(v)


def _rank(v: dict, end: bool = False) -> str:
    return v["value"] + ("T23:59:59+09:00" if end else "T00:00:00+09:00") if v["precision"] == "day" else v["value"]


def expand_recurrence(r: Any) -> list[dict]:
    _exact(r, {"from", "through", "weekdays", "startTime", "endTime", "precision", "exceptions"})
    start, end = date.fromisoformat(_day(r["from"])), date.fromisoformat(_day(r["through"]))
    span = (end - start).days
    days, exceptions, precision = r["weekdays"], r["exceptions"], r["precision"]
    if (not 0 <= span <= 730 or type(days) is not list or not 1 <= len(days) <= 7
            or any(type(d) is not int or not 0 <= d <= 6 for d in days) or len(set(days)) != len(days)
            or type(exceptions) is not list or len(exceptions) > 200):
        raise ValueError("invalid_content_filters")
    for d in exceptions:
        _day(d)
        if not r["from"] <= d <= r["through"] or (date.fromisoformat(d).weekday() + 1) % 7 not in days:
            raise ValueError("invalid_content_filters")
    if len(set(exceptions)) != len(exceptions):
        raise ValueError("invalid_content_filters")
    a, b = r["startTime"], r["endTime"]
    if precision == "day":
        if a is not None or b is not None:
            raise ValueError("invalid_content_filters")
    else:
        pattern = r"(?:[01]\d|2[0-3]):[0-5]\d" + (":[0-5]\\d" if precision == "second" else "")
        if precision not in {"minute", "second"} or type(a) is not str or type(b) is not str or not re.fullmatch(pattern, a) or not re.fullmatch(pattern, b) or a > b:
            raise ValueError("invalid_content_filters")
    result = []
    for i in range(span + 1):
        d = start + timedelta(days=i)
        if (d.weekday() + 1) % 7 not in days or d.isoformat() in exceptions:
            continue
        def value(t):
            return d.isoformat() if precision == "day" else d.isoformat() + "T" + t + (":00" if precision == "minute" else "") + "+09:00"
        result.append({"start": {"value": value(a), "precision": precision}, "end": {"value": value(b), "precision": precision}})
    if not 1 <= len(result) <= 200:
        raise ValueError("invalid_content_filters")
    return result


def validate_filters(d: Any) -> dict:
    _exact(d, {"schema", "category", *KEYS})
    if d["schema"] != SCHEMA or d["category"] not in {"program", "event", "youth_space"} or len(json.dumps(d).encode()) > 120000:
        raise ValueError("invalid_content_filters")
    base = empty_filters(d["category"])
    for k in KEYS:
        f = _exact(d[k], {"status", "value"})
        status, x = f["status"], f["value"]
        if status not in {"known", "unknown", "not_applicable"}:
            raise ValueError("invalid_content_filters")
        if base[k]["status"] == "not_applicable" and status != "not_applicable" or k != "location" and base[k]["status"] == "unknown" and status == "not_applicable":
            raise ValueError("invalid_content_filters")
        if status != "known":
            if x is not None:
                raise ValueError("invalid_content_filters")
            continue
        if k in {"topic", "delivery", "audience", "spaceKind"}:
            options = {"topic": PROGRAM_TOPICS if d["category"] == "program" else EVENT_TOPICS,
                       "delivery": {"online", "onsite", "mixed"}, "audience": {"children", "other"}, "spaceKind": {"introduction", "news"}}[k]
            if type(x) is not str or x not in options:
                raise ValueError("invalid_content_filters")
        elif k == "location":
            _exact(x, {"scope", "venues"})
            if x["scope"] not in {"specific", "nationwide"} or type(x["venues"]) is not list or len(x["venues"]) > 20 or (not x["venues"] if x["scope"] == "specific" else bool(x["venues"])):
                raise ValueError("invalid_content_filters")
            seen = set()
            for p in x["venues"]:
                _exact(p, {"province", "district", "facility", "address"})
                if p["province"] not in DISTRICTS or p["district"] is not None and p["district"] not in DISTRICTS[p["province"]]:
                    raise ValueError("invalid_content_filters")
                _text(p["facility"], 200); _text(p["address"], 500)
                if re.search(r"[\x00-\x1f]", p["facility"] + p["address"]):
                    raise ValueError("invalid_content_filters")
                token = json.dumps(p, sort_keys=True)
                if token in seen:
                    raise ValueError("invalid_content_filters")
                seen.add(token)
        elif k == "application":
            _exact(x, {"deadlineKind", "start", "end", "sourceStatus"})
            if x["deadlineKind"] not in {"fixed", "none"} or x["sourceStatus"] not in {"not_started", "open", "closed", "unknown"} or (x["end"] is None if x["deadlineKind"] == "fixed" else x["end"] is not None):
                raise ValueError("invalid_content_filters")
            a = endpoint(x["start"]) if x["start"] is not None else None
            b = endpoint(x["end"]) if x["end"] is not None else None
            if a and b and _rank(a) > _rank(b, True):
                raise ValueError("invalid_content_filters")
        else:
            _exact(x, {"kind", "occurrences", "recurrence"})
            if x["kind"] not in {"continuous", "occurrences"} or type(x["occurrences"]) is not list or not 1 <= len(x["occurrences"]) <= 200 or x["kind"] == "continuous" and (len(x["occurrences"]) != 1 or x["recurrence"] is not None):
                raise ValueError("invalid_content_filters")
            previous = None
            for o in x["occurrences"]:
                _exact(o, {"start", "end"})
                a, b = endpoint(o["start"]), endpoint(o["end"])
                if _rank(a) > _rank(b, True) or previous and previous >= _rank(a):
                    raise ValueError("invalid_content_filters")
                previous = _rank(b, True)
            if x["recurrence"] is not None and expand_recurrence(x["recurrence"]) != x["occurrences"]:
                raise ValueError("invalid_content_filters")
    exempt = (d["category"] == "program" and d["delivery"] == field("online") or d["category"] == "youth_space" and d["spaceKind"] == field("news"))
    if exempt != (d["location"]["status"] == "not_applicable") and (exempt or d["category"] != "youth_space" or d["spaceKind"] == field("introduction")):
        raise ValueError("invalid_content_filters")
    return copy.deepcopy(d)


def program_application_complete(d: dict) -> bool:
    a = d['application']
    return d['category'] != 'program' or (a['status'] == 'known' and
        a['value']['deadlineKind'] == 'fixed' and a['value']['start'] is not None and
        a['value']['end'] is not None)


def missing_filters(d: dict) -> list[str]:
    missing = [k for k in KEYS if d[k]["status"] == "unknown"]
    if d["location"]["status"] == "known" and any(v["district"] is None for v in d["location"]["value"]["venues"]):
        missing.append("location")
    if not program_application_complete(d):
        missing.append("application")
    return list(dict.fromkeys(missing))


def validate_claim_filter(c: Any, *, worker: str, fence: dict | None = None, category: str | None = None) -> dict:
    """Bind server metadata to the already validated outer claim; no live re-extraction.

    The SQL context intentionally has no identity/revision or current-version
    echo. Outer claim owns identity/revision; finish RPC rechecks filter version
    and source binding against the captured snapshot atomically.
    """
    _exact(c, {"schema", "filterVersion", "data", "claimedAt", "leaseUntil", "workerId"})
    if c["schema"] != SCHEMA or type(c["filterVersion"]) is not int or not 1 <= c["filterVersion"] <= 9007199254740991 or c["workerId"] != worker:
        raise ValueError("invalid_content_filter_claim")
    a, b = [datetime.fromisoformat(_text(c[k], 40).replace("Z", "+00:00")) for k in ("claimedAt", "leaseUntil")]
    if a.tzinfo is None or b.tzinfo is None or not timedelta(seconds=30) <= b - a <= timedelta(seconds=3600) or b <= datetime.now(timezone.utc):
        raise ValueError("invalid_content_filter_claim")
    if fence is not None and any(c[k] != fence[k] for k in ("claimedAt", "leaseUntil", "workerId")):
        raise ValueError("invalid_content_filter_claim")
    d = validate_filters(c["data"])
    if missing_filters(d) or category is not None and d["category"] != category:
        raise ValueError("invalid_content_filter_claim")
    return copy.deepcopy(c)


def confirmed_filter_values(f: dict) -> dict:
    """Same typed delivery/application projection as Build's fact_values SQL.

    For program claims only. Generic claims do not return current facts and
    cannot fabricate this check; their captured binding is verified by SQL.
    """
    result = {}
    mode = f.get("delivery_mode")
    if mode in {"online", "offline", "mixed", "hybrid"}:
        result["delivery"] = {"offline": "onsite", "hybrid": "mixed"}.get(mode, mode)
    periods = f.get("periods", {})
    start = end = None
    if type(periods.get("application")) is list:
        app = next((p for p in periods["application"] if p.get("status") == "ok"), None)
        if app and app.get("endpoints"):
            ends = app["endpoints"]
            start = ends[0] if len(ends) > 1 else None
            end = ends[-1]
    elif periods.get("RCPTENDDT", {}).get("status") == "ok":
        end = {k: periods["RCPTENDDT"][k] for k in ("value", "precision")}
        if periods.get("RCPTBGNDT", {}).get("status") == "ok":
            start = {k: periods["RCPTBGNDT"][k] for k in ("value", "precision")}
    if end:
        status = f.get("source_status")
        state = status if type(status) is str and status in {"not_started", "open", "closed"} else "unknown"
        if status in ("application_closed", "reservation_closed") or type(status) is list and "신청마감" in status:
            state = "closed"
        elif type(status) is list and "신청중" in status:
            state = "open"
        result["application"] = {"deadlineKind": "fixed", "start": endpoint(start) if start else None,
                                 "end": endpoint(end), "sourceStatus": state}
    return result


def validate_program_filter_snapshot(d: dict, f: dict) -> None:
    v = confirmed_filter_values(f)
    if d["category"] == "program":
        if "delivery" in v and d["delivery"] != field(v["delivery"]):
            raise ValueError("content_filter_facts_mismatch")
        if "application" in v:
            a, b = d["application"]["value"], v["application"]
            if a is None or any(a[k] != b[k] for k in ("start", "end")) or b["sourceStatus"] != "unknown" and a["sourceStatus"] != b["sourceStatus"]:
                raise ValueError("content_filter_facts_mismatch")
    elif d["category"] == "event":
        if v.get("delivery") == "online":
            raise ValueError("content_filter_facts_mismatch")
        windows = [p["endpoints"] for p in f.get("periods", {}).get("operation", []) if p.get("status") == "ok" and p.get("endpoints")]
        for o in d["schedule"]["value"]["occurrences"]:
            if not any(_rank(o["start"]) >= _rank(w[0]) and _rank(o["end"], True) <= _rank(w[-1], True) for w in windows):
                raise ValueError("content_filter_facts_mismatch")


def _lines(text: str, labels: str) -> list[str]:
    return [m[1].strip() for m in re.finditer(r"(?m)^\s*(?:" + labels + r")\s*[:：]\s*([^\n]+)", text)]


def _primary(text: str) -> str:
    return "\n".join(_lines(text, "목적|주요 활동|주요 내용|교육 내용|프로그램 내용")) or text


def _topic(text: str, category: str) -> str | None:
    t = _primary(text)
    t = re.sub(r"취업\s*목적(?:이)?\s*(?:없는|없음|아닌)", "", t)
    if re.search(r"불명확|확인 필요|미정|(?:교육|체험|교류|취업)\s*(?:아님|아닌|제외)", t):
        return None
    if category == "program":
        if re.search(r"취업\s*(?:목적|지원\s*(?:목적|프로그램)|준비\s*(?:교육|행사|활동|콘서트)|역량\s*(?:교육|강화))|직무\s*(?:교육|훈련|설명회|역량)|채용\s*설명회|(?:취업|구직)(?:을|를)?\s*위한", t):
            return "employment_career"
        if re.search(r"(?:생활|안전|재난|응급처치|교통안전)\s*(?:교육|훈련|학습)", t):
            return "daily_safety"
        if re.search(r"(?:한국어|일본어|영어|언어|시험|컴퓨터\s*기초|AI\s*도구)\s*(?:교육|학습|수업|강좌|활용)|(?:언어|시험)\s*준비", t):
            return "language_learning"
        matches = [name for name, pattern in (
            ("culture_experience", r"(?:문화|공예|미술|음악|창작|취미|요리)\s*(?:체험|활동|교육|수업|강좌)|(?:그림|공예품)\s*만들기"),
            ("community_exchange", r"(?:주민|지역|이웃)\s*(?:교류|만남|활동)|교류\s*(?:활동|모임)")) if re.search(pattern, t)]
    else:
        matches = [name for name, pattern in (
            ("festival_exchange", r"축제(?:를|가|에)?\s*(?:개최|진행)|교류회(?:를|가)?\s*(?:개최|진행)"),
            ("culture_arts", r"(?:공연|전시회|문화예술\s*행사)(?:를|가)?\s*(?:개최|진행|관람)"),
            ("lecture_commemoration", r"(?:강연|기념행사)(?:을|를|가)?\s*(?:개최|진행)")) if re.search(pattern, t)]
    if len(matches) == 1:
        return matches[0]
    return "other" if re.fullmatch(r"\s*(?:대표 분야|분야)\s*[:：]\s*기타\s*", t) else None


def _audience(text: str, *, role: str) -> str | None:
    """Evidence signals for discovery, not applicant eligibility or an age gate.

    Keep a default 'other' separate from an explicit contrary audience. Birth
    years need no inferred age when the primary child audience is already clear.
    """
    if type(text) is not str:
        return "unknown"
    if not text.strip():
        return None
    if re.fullmatch(r"\s*(?:[-—]|없음|미기재|N/?A)\s*", text, re.I):
        return None
    if not re.search(r"[가-힣A-Za-z0-9]", text):
        return None
    incomplete = r"불명확|미확인|미정|확인\s*필요|자료\s*(?:없음|부족)|정보\s*부족|(?:본문|내용)\s*[:：]?\s*(?:없음|소실|누락)"
    if (role != "body" and not re.search(r"출생|기준일", text) and re.search(incomplete, text)
            or role == "body" and re.fullmatch(r"\s*(?:" + incomplete + r")[.。…]*\s*", text)):
        return "unknown"
    if re.search(r"(?:어린이|아동|초등학생)\s*(?:주\s*대상)?\s*(?:여부|인지).*?(?:불명확|미확인)", text):
        return "unknown"
    children = r"(?:어린이|아동|초등학생)"
    # Participation by a child/family member is not the activity's main audience.
    incidental = bool(re.search(children + r"\s*(?:도\s*)?(?:참여|동반)\s*가능|(?:동반\s*)?(?:자녀|어린이\s*참가자)\s*[:：]", text))
    main = re.sub(children + r"\s*(?:도\s*)?(?:참여|동반)\s*가능[^\n.]*", "", text)
    negative = children + r"\s*(?:제외|불가|아님|대상\s*아님)"
    main = re.sub(negative, "", main)
    broad = bool(re.search(r"가족|전\s*연령|누구나", main)) if role == "target" else bool(re.search(
        r"(?:전\s*연령|누구나)\s*(?:이|가|은|는)?\s*(?:참여|대상)|가족\s*(?:이|과|은|는)?\s*(?:프로그램|활동|체험|참여|함께)", main))
    explicit_child = bool(re.search(
        r"(?:주(?:요)?\s*대상|(?:참여\s*)?대상)\s*(?:[:：]|은|는|이)\s*" + children +
        r"|" + children + r"(?:을|를)?\s*(?:위한|대상(?:으로)?|전용)\s*(?:프로그램|교육|수업|활동|체험)?", main))
    primary_target = bool(re.match(r"\s*(?:(?:외국인|일본인)\s*)?" + children + r"(?=\s|$|[(:,·]|와|과)", main))
    child = explicit_child or (role == "target" and not broad and not incidental and primary_target)
    if re.search(children + r"\s*(?:의\s*|자녀를\s*둔\s*)?(?:보호자|부모)(?!\s*동반)", main):
        child = False  # The child's parent, not the child, is the stated target.
    opposite = bool(re.search(negative + r"|(?:성인|청년|청소년)\s*(?:전용|만\s*(?:신청|참여|대상))", text))
    if role == "target" and not broad:
        # An accompanying adult guardian is not an adult-only program.
        without_guardian = re.sub(r"(?:성인\s*)?보호자\s*동반", "", main)
        opposite |= bool(re.search(r"성인|청년|청소년", without_guardian))
    ages = list(re.finditer(r"(?:만\s*)?(\d+)\s*(?:~|-|부터)\s*(\d+)\s*세|(?:만\s*)?(\d+)\s*세\s*이하", text))
    bounds = [(int(m[1]) if m[1] else 0, int(m[2] or m[3])) for m in ages]
    exact_age = re.fullmatch(r"\s*(?:만\s*)?(\d+)\s*세\s*", text) if role == "age" else None
    if exact_age:
        bounds.append((int(exact_age[1]), int(exact_age[1])))
    if any(low > high for low, high in bounds):
        return "conflict"
    if not incidental and role in {"target", "age"}:
        child |= bool(bounds) and all(high <= 12 for _, high in bounds) and not broad
        opposite |= any(low >= 13 for low, _ in bounds)
        lower = re.search(r"(?:만\s*)?(\d+)\s*세\s*이상", text)
        opposite |= bool(lower and int(lower[1]) >= 13)
    if child and opposite:
        return "conflict"
    if child:
        return "children"
    if opposite:
        return "opposite"
    if broad:
        return "broad"
    if role != "body" and re.search(r"출생|기준일", text) or role == "age" and not bounds and not incidental:
        return "age_unknown"
    return "material"  # Valid retained material, no positive child evidence.


def _program_audience(materials: list[tuple[str, str, str, str]]) -> tuple[str, int] | None:
    signals = [_audience(text, role=role) for _, text, _, role in materials]
    if "conflict" in signals or "unknown" in signals:
        return None
    child = [i for i, value in enumerate(signals) if value == "children"]
    if child:
        if "opposite" in signals:
            return None
        # An unqualified program age bound contradicts an explicit all-age
        # audience. A labelled child's incidental age never enters this branch.
        if "broad" in signals and all(materials[i][3] == "age" for i in child):
            return None
        return "children", child[0]
    if "age_unknown" in signals:
        return None
    usable = [i for i, value in enumerate(signals) if value in {"opposite", "broad", "material"}]
    return ("other", usable[0]) if usable else None


def _location(text: str) -> dict | None:
    if re.search(r"거주|주민등록|기관\s*주소|집결|만나는\s*장소|미정|불명확", text):
        return None
    if re.search(r"전국\s*(?:시설|공간|지점)(?:에서|을)?\s*(?:이용|운영)|실제\s*이용\s*지역\s*[:：]\s*전국", text):
        return {"scope": "nationwide", "venues": []}
    venues = []
    for part in re.split(r"[;\n]", text):
        provinces = [code for code, pattern in (("11", r"(?<![가-힣])서울(?:특별시|시)?(?![가-힣])"), ("41", r"(?<![가-힣])경기(?:도)?(?![가-힣])"), ("28", r"(?<![가-힣])인천(?:광역시|시)?(?![가-힣])")) if re.search(pattern, part)]
        if len(provinces) != 1 or re.search(r"부산|대구|대전|제주|강원|충청|전라|경상|수도권", part):
            return None
        province = provinces[0]
        districts = [d for d in DISTRICTS[province] if re.search(r"(?<![가-힣])" + d + r"(?![가-힣])", part)]
        if len(districts) > 1:
            return None
        if len(part.strip()) > 500 or re.search(r"[\x00-\x1f]", part):
            return None
        venues.append({"province": province, "district": districts[0] if districts else None,
                       "facility": "", "address": part.strip()})
    return {"scope": "specific", "venues": venues} if 1 <= len(venues) <= 20 else None


def _schedule(text: str) -> dict | None:
    """One bounded full-year ISO schedule line; unsupported forms stay unknown."""
    t = text.strip()
    full = r"(\d{4}-\d{2}-\d{2})"
    repeat = re.fullmatch(full + r"\s*~\s*" + full + r"\s+매주\s+([일월화수목금토])요일(?:\s+([0-2]\d:[0-5]\d)\s*~\s*([0-2]\d:[0-5]\d))?(?:\s+제외일\s*:\s*([\d, -]+))?", t)
    if repeat:
        a, b, day, at, bt, exceptions = repeat.groups()
        r = {"from": a, "through": b, "weekdays": ["일월화수목금토".index(day)],
             "startTime": at, "endTime": bt, "precision": "minute" if at else "day",
             "exceptions": [d.strip() for d in exceptions.split(",")] if exceptions else []}
        try:
            return {"kind": "occurrences", "occurrences": expand_recurrence(r), "recurrence": r}
        except ValueError:
            return None
    # Never turn repeated days into a continuous interval.
    if re.search(r"매주|요일|회차|집결|반\s*[:：]|과정\s*[:：]", t):
        return None
    def ep(s):
        precision = "day" if len(s) == 10 else "minute"
        return endpoint({"value": s if precision == "day" else s.replace(" ", "T") + ":00+09:00", "precision": precision})
    token = r"\d{4}-\d{2}-\d{2}(?: [0-2]\d:[0-5]\d)?"
    occurrences = []
    try:
        for part in t.split(","):
            m = re.fullmatch(r"\s*(" + token + r")(?:\s*~\s*(" + token + r"))?\s*", part)
            if not m:
                return None
            occurrences.append({"start": ep(m[1]), "end": ep(m[2] or m[1])})
        result = {"kind": "continuous" if len(occurrences) == 1 and "~" in t else "occurrences", "occurrences": occurrences, "recurrence": None}
        check = empty_filters("event")
        check["schedule"] = field(result)
        validate_filters(check)
        return result
    except ValueError:
        return None


def extract_filter_facts(source: str, payload: dict, facts: dict | None = None) -> dict | None:
    """Use revision-bearing source fields only; category proposals do not confirm it."""
    if source not in {"myseoul_program", "seoul_reservation", "youthcenter_content"}:
        return None
    facts = facts or {}
    body_key = {"myseoul_program": "description", "seoul_reservation": "program_text", "youthcenter_content": "plain_text"}[source]
    body = payload.get(body_key) or ""
    if type(body) is not str:
        raise ValueError("invalid_content_filter_source")
    category = facts.get("public_category") if source == "myseoul_program" else "program" if source == "seoul_reservation" else None
    if source == "youthcenter_content":
        from ingest.gate_facts import extract_delivery_mode
        main = _primary(body)
        categories = []
        if re.search(r"(?:교육|수업|강좌|훈련)(?:을|를|가)?\s*(?:진행|운영)|프로그램\s*(?:내용|목적)\s*[:：]", main):
            categories.append("program")
        if re.search(r"(?:행사|축제|공연|전시회|강연|교류회)(?:을|를|가)?\s*개최", main) and extract_delivery_mode(body) != "online" and not re.search(r"온라인\s*(?:전용|행사|강연)", main):
            categories.append("event")
        if re.search(r"청년\s*공간\s*(?:소개|소식|홍보|활동\s*후기)", main):
            categories.append("youth_space")
        category = categories[0] if len(categories) == 1 else None
    if category not in {"program", "event", "youth_space"}:
        return None  # No unknown category in v1; retain existing category review.
    d, evidence = empty_filters(category), {}
    def put(k, value, key=body_key, excerpt=None, prefix="payload"):
        if value is None:
            return
        material = (facts if prefix == "facts" else payload).get(key)
        if type(material) is not str:
            material = json.dumps(material, ensure_ascii=False) if material is not None else ""
        quote = excerpt if excerpt is not None else material
        if not quote or len(quote) > 1000 or quote not in material or re.search(r"[<>]", quote):
            return
        d[k] = field(value)
        evidence[k] = {"sourceField": prefix + "." + key, "excerpt": quote}
    topic_text = facts.get("purpose") or _primary(body)
    if type(topic_text) is not str:
        topic_text = body
    if category != "youth_space":
        put("topic", _topic(topic_text, category), "purpose" if facts.get("purpose") else body_key,
            topic_text[:1000] if len(topic_text) <= 1000 else None, "facts" if facts.get("purpose") else "payload")
    if category == "program":
        mode = facts.get("delivery_mode")
        if mode in {"online", "offline", "hybrid", "mixed"}:
            put("delivery", {"offline": "onsite", "hybrid": "mixed"}.get(mode, mode), "delivery_mode", prefix="facts")
        else:
            lines = _lines(body, "진행 방식|교육 방식")
            if len(lines) == 1:
                mode = {"온라인": "online", "현장": "onsite", "온라인·현장 혼합": "mixed", "혼합": "mixed"}.get(lines[0])
                put("delivery", mode, excerpt=lines[0])
        materials = []
        target_key = "target" if facts.get("target") else "target_raw" if facts.get("target_raw") else None
        if target_key:
            materials.append((target_key, facts[target_key], "facts", "target"))
        else:
            materials.extend((body_key, t, "payload", "target") for t in _lines(body, "대상|참여 대상|주 대상"))
        ages = facts.get("age") if source == "myseoul_program" else _lines(body, "연령|대상 연령")
        if isinstance(ages, (list, tuple)):
            materials.extend(("age" if source == "myseoul_program" else body_key, age,
                              "facts" if source == "myseoul_program" else "payload", "age") for age in ages)
        materials.append((body_key, body, "payload", "body"))
        audience = _program_audience(materials)
        if audience is not None:
            value, index = audience
            key, quote, prefix, _ = materials[index]
            put("audience", value, key, quote[:1000], prefix)
        # Structured application dates have a server-authoritative reuse path.
        # Keep unknown here when no direct source excerpt exists; SQL fills it
        # from current confirmed facts without inventing a source quotation.
        # Generic deadline facts still supply the end only. The follow-up SQL
        # preserves a separately confirmed filter start; do not overwrite it
        # with a fresh extraction. Existing facts extraction owns source dates.
    if category == "youth_space":
        main = _primary(body)
        intro = bool(re.search(r"청년\s*공간\s*소개", main))
        news = bool(re.search(r"청년\s*공간\s*(?:소식|홍보|활동\s*후기)", main))
        if intro != news:
            put("spaceKind", "introduction" if intro else "news", excerpt=main if len(main) <= 1000 else None)
    if d["delivery"] == field("online") or d["spaceKind"] == field("news"):
        d["location"] = field(status="not_applicable")
    else:
        venues = _lines(body, "개최 장소|개최지|교육 장소|운영 장소|이용 장소|장소")
        venue = facts.get("venue") if source == "myseoul_program" else None
        activity = facts.get("activity_evidence") if source == "seoul_reservation" else None
        if venue:
            put("location", _location(venue), "venue", prefix="facts")
        elif type(activity) in {list, tuple} and activity and all(type(v) is str for v in activity):
            # Existing Seoul place extraction, not provider institution/address.
            put("location", _location("\n".join(activity)), "activity_evidence", prefix="facts")
        elif venues:
            value = _location(";".join(venues))
            # One evidence entry can quote a contiguous block containing all venues.
            block = body[body.find(venues[0]):body.rfind(venues[-1]) + len(venues[-1])]
            put("location", value, excerpt=block)
    if category == "event":
        schedules = _lines(body, "행사 기간|행사 일정|개최 일정|개최 기간|운영일시|운영기간")
        if len(schedules) == 1:
            put("schedule", _schedule(schedules[0]), excerpt=schedules[0])
    # Conflicts/unparsed values never become a fallback 'other' or fake facts.
    return {"data": validate_filters(d), "evidence": evidence}
