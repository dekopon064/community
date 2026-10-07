"""Source-specific discovery selection; never re-evaluates persisted items.

Only retained API text is evidence. No link fetching, clock guessing or AI.
Review means the proposal is not ready to auto-confirm, not a invented fact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from ingest.application_deadline import (
    DEADLINE_KIND_CLOSED, DEADLINE_KIND_FIXED, DEADLINE_KIND_NONE, _leading_date,
    parse_content_application_deadline,
)
from ingest.models import ObservationRecord
from ingest.sanitize import is_http_url
from ingest.source_identity import CANONICAL_CONTENT_SOURCE, CANONICAL_POLICY_SOURCE

RULE_VERSION = "youthcenter-discovery-v3"


@dataclass(frozen=True)
class SourceSelectionPolicy:
    require_direct_target: bool
    require_use_information: bool


# Opt in by canonical identity, never by a generic policy/content source kind.
SOURCE_POLICIES = {
    CANONICAL_POLICY_SOURCE: SourceSelectionPolicy(True, False),
    CANONICAL_CONTENT_SOURCE: SourceSelectionPolicy(False, True),
}


@dataclass(frozen=True)
class DiscoverySelection:
    source_id: str
    decision: Literal["include", "exclude", "review"]
    reason_codes: tuple[str, ...]
    evidence: tuple[str, ...]
    proposed_type: str | None
    region_scope: str
    region_codes: tuple[str, ...]
    region_evidence: str

    def to_payload(self) -> dict:
        return {
            "source_id": self.source_id, "rule_version": RULE_VERSION,
            "decision": self.decision, "reason_codes": list(self.reason_codes),
            "evidence": list(self.evidence), "proposed_type": self.proposed_type,
            "eligibility_scope": self.region_scope,
            "eligibility_region_codes": list(self.region_codes),
            "eligibility_region_evidence": self.region_evidence,
        }


def discovery_today() -> date:
    return datetime.now(timezone(timedelta(hours=9))).date()


_TARGET = r"(?:외국인|일본인|일본\s*국적자|외국\s*국적자|다문화\s*(?:가족|주민)|결혼\s*이민자)"
_APPLICANT = re.compile(r"(?:지원|신청|참여|참가|수강|이용)\s*(?:대상|자격)|대상\s*[:：]")
_LABELED_TARGET = re.compile(r"(?:(?:지원|신청|참여|참가|수강|이용)\s*(?:대상|자격)|대상\s*[:：])[^\n.!?。]{0,35}" + _TARGET)
_DIRECT = re.compile(
    _TARGET + r"\s*(?:청년|주민|학생|근로자|유학생|가족)?\s*(?:은|는|도|이|을|를|에게|만)?\s*(?:(?:지원|신청|참여|참가|수강|이용)\s*대상|대상|신청\s*가능|지원\s*가능|참여\s*가능|참가\s*가능|수강\s*가능|모집|지원합니다)"
)
_ONLY_TARGET = re.compile(_TARGET + r"\s*(?:주민|청년)?\s*(?:이외|외)(?:에는|는)?\s*(?:신청|지원|참여|참가)\s*불가")
_NEGATIVE = re.compile(
    _TARGET + r"\s*(?:청년|주민|학생|근로자|유학생|가족)?\s*(?:은|는|도|이|을|를|에게)?\s*(?:(?:신청|지원|참여|참가|수강|이용)(?:은|이)?\s*)?(?:대상(?:에서|이|은)?\s*)?(?:제외|불가|불가능|금지|아닌|아니어야|(?:신청|지원|참여)하지|할\s*수\s*없)"
)
_PURPOSE_NEGATIVE = re.compile(_TARGET + r"[^\n.!?。]{0,50}(?:위한|대상)[^\n.!?。]{0,60}(?:아닌|아닙니다|아니며|아니다|관계없|관련없)")
_TARGET_UNCERTAIN = re.compile(_TARGET + r"[^\n.!?。]{0,60}(?:확인\s*필요|불명확|미확인|확인되지|명확하지|검토\s*중)")
_NATIONAL_LOCK = re.compile(r"(?:내국인|한국인|한국\s*국적자|대한민국\s*국적자)[^\n.!?。]{0,20}(?:만|한정)|(?:한국|대한민국)\s*국적(?:을)?\s*(?:보유|필수)")
_UNRESTRICTED = re.compile(r"국적\s*(?:제한\s*[:：]?\s*없음|제한\s*없이|무관|불문)|국적(?:에)?\s*관계없이")
_ORGANIZATION = re.compile(r"(?:기관|기업|업체|법인|단체|센터|고용주)(?:을|를|만|에게|은|는|이|도)?\s*(?:대상|모집|신청\s*가능|지원\s*가능)|(?:지원|신청)\s*대상\s*[:：]?[^\n.!?。]{0,60}(?:기관|기업|업체|법인|단체|센터|고용주)")
_JOB_TRAINING = re.compile(r"(?:취업|구직|직무|채용|이력서|면접)[^\n.!?。]{0,60}(?:교육|훈련|강좌|과정|아카데미|부트캠프)|(?:교육|훈련|강좌|과정|아카데미|부트캠프)[^\n.!?。]{0,60}(?:취업|구직|직무|채용|이력서|면접)")
_JOB_EVENT = re.compile(r"(?:직무|채용)\s*설명회|취업\s*(?:준비|지원)?\s*(?:행사|콘서트|설명회)")
_TARGET_PURPOSE = re.compile(_TARGET + r"[^\n.!?。]{0,35}(?:위한|대상)[^\n.!?。]{0,45}(?:취업|구직|직무|교육|훈련)|" + _TARGET + r"(?:의)?\s*(?:취업|구직)\s*(?:지원|역량)[^\n.!?。]{0,35}(?:교육|훈련|설명회|행사|콘서트)")
_USE = re.compile(r"(?:신청|접수|참여|참가|예약|방문|시설\s*이용|수강)\s*(?:방법|기간|링크|주소|안내|가능|하기|하세요|받|대상|문의)|(?:운영|이용|개방)\s*시간\s*[:：]|참가자\s*모집")
_PROMOTION = re.compile(r"후기|성과\s*(?:소개|보고)|성료|홍보|실적\s*소개|(?:기관|센터|공간|사업)\s*소개")
_LIVING = re.compile(r"청년\s*공간|시설\s*이용|생활\s*(?:안내|정보)|도서관|공간\s*(?:이용|안내)|주민\s*센터")
_EVENT = re.compile(r"행사|축제|공연|전시|박람회|설명회|체험|교류회|프로그램|교육|훈련|강좌|투어")
_CURRENT = re.compile(r"상시\s*(?:신청\s*가능|접수\s*중|모집\s*중|이용\s*가능)|신청(?:은)?\s*상시\s*가능|연중\s*이용\s*가능|현재\s*(?:운영|시행)\s*중|(?:운영|이용|개방)\s*시간\s*[:：]")
_REGIONS = (
    ("서울", "11"), ("인천", "28"), ("경기", "41"),
    ("부산", "26"), ("대구", "27"), ("광주광역시", "29"),
    ("대전", "30"), ("울산", "31"), ("세종", "36"),
    ("강원", "51"), ("충북", "43"), ("충청북도", "43"),
    ("충남", "44"), ("충청남도", "44"), ("전북", "52"),
    ("전라북도", "52"), ("전남", "46"), ("전라남도", "46"),
    ("경북", "47"), ("경상북도", "47"), ("경남", "48"),
    ("경상남도", "48"), ("제주", "50"),
)
_CAPITAL = {"11", "28", "41"}
_RESIDENCE = re.compile(r"거주|주민|주소지|주민등록")
_EXCLUSIVE = re.compile(r"거주자만|주민만|거주[^\n.!?。]{0,20}(?:한정|필수)|(?:대상|자격)\s*[:：][^\n.!?。]{0,50}거주")
_NATIONWIDE = re.compile(r"(?:거주\s*)?지역\s*제한\s*없음|전국\s*(?:거주자|거주|청년|대상|어디서나)|전국[^\n.!?。]{0,25}(?:신청|참여|이용)\s*가능")
_EVENT_PERIOD = re.compile(r"(?:^[ \t]*|(?<=[.!?。])\s+)(?:행사|교육|운영|이용)\s*(?:기간|일자|일)\s*[:：]\s*([^\n]{1,100})", re.MULTILINE)


def _excerpt(text: str, *patterns: re.Pattern) -> str:
    """Bound diagnostics only; classification and retained body use full text."""
    matches = [match for pattern in patterns if (match := pattern.search(text))]
    start = max(0, min(match.start() for match in matches) - 64) if matches else 0
    return text[start:start + 512]


def _sentences(text: str) -> tuple[str, ...]:
    return tuple(s.strip() for s in re.split(r"\n|[;。!?]|\.(?=\s|$)", text) if s.strip())


def _use_evidence(text: str) -> tuple[str, ...]:
    return tuple(
        s for s in _sentences(text) if _USE.search(s)
        and (not re.search(r"당시|지난|종료된|했던|이었습니다|참여했습니다|방문했습니다", s)
             or re.search(r"현재|지금", s))
    )


def _target_evidence(text: str, *, allow_unrestricted: bool) -> tuple[str, ...]:
    sentences = _sentences(text)
    # Any explicit applicant restriction blocks automatic inclusion, including conflicts.
    if _target_blocked(text):
        return ()
    found = []
    for sentence in sentences:
        if _ORGANIZATION.search(sentence):
            continue
        direct = _LABELED_TARGET.search(sentence) or _DIRECT.search(sentence) or _ONLY_TARGET.search(sentence)
        unrestricted = allow_unrestricted and _UNRESTRICTED.search(sentence) and (
            _APPLICANT.search(sentence)
            or re.search(r"(?:신청|지원|참여|참가|이용)\s*가능", sentence)
            or _UNRESTRICTED.fullmatch(sentence)
        )
        if direct or unrestricted:
            found.append(sentence)
    return tuple(found)


def _target_blocked(text: str) -> bool:
    return any(
        pattern.search(sentence) for sentence in _sentences(text)
        for pattern in (_NEGATIVE, _NATIONAL_LOCK, _PURPOSE_NEGATIVE, _TARGET_UNCERTAIN)
    )


def _training_nature(title: str, body: str) -> str | None:
    # A job-focused event is subject to the same audience gate as training.
    # Incidental body mentions remain uncertain instead of becoming exclusions.
    if _JOB_TRAINING.search(title) or _JOB_EVENT.search(title):
        return "training"
    matches = [s for s in _sentences(body) if _JOB_TRAINING.search(s) or _JOB_EVENT.search(s)]
    if not matches:
        return None
    for sentence in matches:
        if re.match(r"(?:취업|구직|직무|채용|이력서|면접)", sentence) or re.search(
            r"교육\s*(?:내용|과정)|훈련\s*내용|커리큘럼|수강생\s*모집|주된\s*활동|(?:행사|프로그램)의?\s*(?:목적|주요\s*내용)", sentence
        ):
            return "training"
    return "uncertain"


def _region(text: str, *, living: bool) -> tuple[str, tuple[str, ...], str, str | None]:
    national = []
    residence = []
    exclusive = False
    for sentence in _sentences(text):
        if re.search(r"수도권\s*거주[^\n.!?。]{0,25}(?:제외|불가|신청할\s*수\s*없)", sentence):
            return "unknown", (), sentence, "capital_residence_excluded"
        if _RESIDENCE.search(sentence) and re.search(r"제외|불가|아닌", sentence):
            return "unknown", (), sentence, "region_evidence_conflict"
        nationwide_role = (
            _APPLICANT.search(sentence)
            or re.search(r"(?:신청|참여|이용)\s*가능|전국\s*(?:거주자|청년)\s*(?:대상|모집)", sentence)
            or _NATIONWIDE.fullmatch(sentence)
        )
        if _NATIONWIDE.search(sentence) and nationwide_role and not re.search(r"불가|제외|아님|없지", sentence):
            national.append(sentence)
        if _RESIDENCE.search(sentence) and (_APPLICANT.search(sentence) or re.search(r"대상|신청|참여|이용|자격", sentence)):
            codes = set()
            for name, code in _REGIONS:
                for match in re.finditer(re.escape(name), sentence):
                    rest = sentence[match.end():]
                    resident = _RESIDENCE.search(rest)
                    if resident is not None and not re.search(
                        r"개최|장소|주소\s*[:：]|위치|기관|방문|행사장|신청\s*대상", rest[:resident.start()]
                    ):
                        codes.add(code)
            if "수도권" in sentence and "비수도권" not in sentence:
                codes.update(_CAPITAL)
            if codes:
                residence.append((sentence, codes))
                exclusive = exclusive or bool(
                    _EXCLUSIVE.search(sentence)
                    and not re.search(r"우선|포함|예시|거주\s*제한\s*없음", sentence)
                )
    codes = set().union(*(c for _, c in residence)) if residence else set()
    if national and exclusive:
        return "unknown", (), "\n".join(national + [s for s, _ in residence]), "region_evidence_conflict"
    if national:
        return "nationwide", (), "\n".join(national), None
    if codes:
        evidence = "\n".join(s for s, _ in residence)
        if not codes & _CAPITAL:
            if exclusive:
                return "specific", tuple(sorted(codes)), evidence, "noncapital_residence_only"
            return "unknown", (), evidence, "region_scope_unknown"
        return "specific", tuple(sorted(codes)), evidence, None
    # A venue is use-region evidence only for space/living information, not eligibility.
    if living:
        for sentence in _sentences(text):
            if re.search(r"주소|위치|소재지|장소", sentence):
                codes = {code for name, code in _REGIONS if name in sentence} & _CAPITAL
                if codes:
                    return "specific", tuple(sorted(codes)), sentence, None
    return "unknown", (), "", "region_scope_unknown"


def _period(record: ObservationRecord, text: str, today: date, *, living: bool) -> str | None:
    deadline = record.application_deadline
    body_deadline = parse_content_application_deadline(text)
    if body_deadline is not None:
        if deadline is None or deadline.kind == DEADLINE_KIND_NONE:
            deadline = body_deadline
        elif body_deadline != deadline:
            return "period_evidence_conflict"
    event_ends = []
    uncertain = False
    for match in _EVENT_PERIOD.finditer(text):
        chunk = match[1].strip()
        parts = re.split(r"[~∼～]|부터", chunk, maxsplit=1)
        parsed = _leading_date(parts[-1].split("까지", 1)[0].strip())
        if len(parts) == 2:
            start = _leading_date(parts[0].strip())
            if start is None or parsed is None or start > parsed:
                uncertain = True
        if parsed is None:
            uncertain = True
        else:
            event_ends.append(parsed)
    if len(set(event_ends)) > 1:
        uncertain = True
    if uncertain:
        return "period_meaning_uncertain"
    if re.search(r"(?:행사|교육)(?:가|이)?\s*(?:종료되었습니다|끝났습니다)|행사\s*종료", text):
        if event_ends and event_ends[0] >= today:
            return "period_evidence_conflict"
        return "event_ended"
    if deadline is not None:
        if deadline.kind == DEADLINE_KIND_CLOSED:
            if living and _CURRENT.search(text):
                return "period_evidence_conflict"
            return "application_closed"
        if deadline.kind == DEADLINE_KIND_FIXED:
            if date.fromisoformat(deadline.on) < today:
                if living and _CURRENT.search(text):
                    return "period_evidence_conflict"
                return "application_ended"
            if event_ends and event_ends[0] < today:
                return "period_evidence_conflict"
            return None
    if event_ends:
        if event_ends[0] < today and living and _CURRENT.search(text):
            return "period_evidence_conflict"
        return "event_ended" if event_ends[0] < today else None
    if _CURRENT.search(text):
        if deadline is None or deadline.kind == DEADLINE_KIND_NONE:
            return None
    # The API's 'none' and the word '상시' do not prove current validity.
    return "period_meaning_uncertain"


def _has_other_use_information(source_id: str, record: ObservationRecord) -> bool:
    """Only explicit retained use fields; a title/detail URL is not use evidence.

    This prevents an empty-item exclusion, not an inclusion or facts proposal.
    Empty-body review still requires the existing store contract.
    """
    payload = record.normalized_payload or {}
    if _use_evidence(str(payload.get("activity_location_text") or "")):
        return True
    if source_id == CANONICAL_POLICY_SOURCE:
        deadline = record.application_deadline
        return is_http_url(payload.get("aplyUrlAddr")) or (
            deadline is not None and deadline.kind != DEADLINE_KIND_NONE
        )
    return False


def select_discovery(
    source_id: str, record: ObservationRecord, *, today: date,
) -> DiscoverySelection | None:
    policy = SOURCE_POLICIES.get(source_id)
    if policy is None:
        return None
    payload = record.normalized_payload or {}
    body = str(payload.get("plain_text") or "")
    title = str(payload.get("plcyNm") or payload.get("pstTtl") or "")
    activity = f"{title}\n{body}"
    direct = _target_evidence(body, allow_unrestricted=True)
    evidence = list(direct)
    reasons = []
    decision: Literal["include", "exclude", "review"] = "include"
    title_living = bool(_LIVING.search(title))
    title_event = bool(_EVENT.search(title))
    proposed_type = None
    if policy.require_direct_target and not direct:
        reasons.append("policy_direct_target_unconfirmed")
        decision = "exclude"
    elif policy.require_use_information:
        use_evidence = _use_evidence(body)
        if not body.strip():
            use_evidence += _use_evidence(str(payload.get("activity_location_text") or ""))
        training_nature = _training_nature(title, body)
        job_training = training_nature == "training"
        if training_nature == "uncertain":
            reasons.append("activity_type_uncertain")
        relevant_job = _target_evidence(body, allow_unrestricted=False)
        if not relevant_job and not _target_blocked(body):
            relevant_job = tuple(s for s in _sentences(body) if _TARGET_PURPOSE.search(s) and not _ORGANIZATION.search(s))
        if job_training and not relevant_job:
            reasons.append("job_training_target_unconfirmed")
            decision = "exclude"
        elif not use_evidence:
            reasons.append("use_information_missing")
            decision = "exclude" if _PROMOTION.search(activity) else "review"
        else:
            evidence.extend(use_evidence)
            evidence.extend(relevant_job if job_training else ())

    if not body.strip() and not record.attachment_present and not _has_other_use_information(source_id, record):
        reasons.append("empty_item_no_use_information")
        decision = "exclude"

    if (source_id == CANONICAL_CONTENT_SOURCE and not body.strip()
            and not _has_other_use_information(source_id, record)
            and not is_http_url(payload.get("source_url"))):
        # No attachment link/content survives the connector's existing contract.
        # Retained presence/length/data metadata is provenance, not review material.
        reasons.append("no_reviewable_material")
        if record.attachment_present:
            reasons.append("attachment_removed_no_reviewable_material")
        decision = "exclude"

    if title_event and title_living:
        reasons.append("activity_type_uncertain")
    elif title_event:
        proposed_type = "event_program"
    elif title_living:
        proposed_type = "living_guide"
    elif _LIVING.search(body) and _EVENT.search(body):
        reasons.append("activity_type_uncertain")
    elif _LIVING.search(body):
        proposed_type = "living_guide"
    elif _EVENT.search(body):
        proposed_type = "event_program"
    elif policy.require_direct_target and re.search(r"정책|제도|지원\s*자격|혜택", activity):
        proposed_type = "policy_reference"
    else:
        reasons.append("activity_type_uncertain")
    if "activity_type_uncertain" in reasons:
        proposed_type = None
    living = proposed_type == "living_guide"
    scope, codes, region_evidence, region_reason = _region(body, living=living)
    if region_reason:
        reasons.append(region_reason)
        if region_reason in {"noncapital_residence_only", "capital_residence_excluded"}:
            decision = "exclude"
    period_reason = _period(record, body, today, living=living)
    if period_reason:
        reasons.append(period_reason)
        if period_reason in {"application_closed", "application_ended", "event_ended"}:
            decision = "exclude"
    # No character threshold: useful but incomplete items remain reviewable.
    if not body.strip() or not record.has_source_url:
        reasons.append("content_information_insufficient")
    if decision != "exclude" and reasons:
        decision = "review"
    return DiscoverySelection(
        source_id, decision, tuple(dict.fromkeys(reasons)),
        tuple(dict.fromkeys(_excerpt(s, _LABELED_TARGET, _DIRECT, _ONLY_TARGET, _USE, _TARGET_PURPOSE) for s in evidence))[:6],
        proposed_type, scope, codes, _excerpt(region_evidence, _NATIONWIDE, _RESIDENCE),
    )


def attach_selection(record: ObservationRecord, selection: DiscoverySelection) -> ObservationRecord:
    """Keep source body, revision and facts intact; add only derived diagnostics."""
    normalized = dict(record.normalized_payload or {})
    normalized["discovery_selection"] = selection.to_payload()
    return replace(record, normalized_payload=normalized, discovery_selection=selection)
