"""제품 relevance. 키워드는 후보이며 자격·문맥·부정문을 같이 본다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ingest.models import (
    REASON_RELEVANCE_UNCONFIRMED,
    REASON_REGION_SCOPE_UNKNOWN,
    RegionScope,
)
from ingest.region import (
    classify_eligibility,
    classify_operator,
    classify_region_scope,
    region_reason_codes,
)

RULE_VERSION = "relevance-capital-v1"

AXIS_JP_RESIDENTS_IN_KR = "jp_residents_in_kr"
AXIS_FOREIGN_RESIDENTS_IN_KR = "foreign_residents_in_kr"
AXIS_KR_JAPAN_ACTIVITY = "kr_japan_activity"
AXIS_KR_JP_EXCHANGE = "kr_jp_exchange"

POLICY_AXES = (
    AXIS_JP_RESIDENTS_IN_KR,
    AXIS_FOREIGN_RESIDENTS_IN_KR,
    AXIS_KR_JAPAN_ACTIVITY,
    AXIS_KR_JP_EXCHANGE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=다\.)|\n+|。")

_NEGATION_GENERAL = (
    "불가",
    "제외",
    "해당 없음",
    "대상이 아님",
    "대상 아님",
    "참여할 수 없",
    "신청할 수 없",
    "해당하지 않",
)

_NATIONALITY_LOCK = (
    "내국인만",
    "대한민국 국적만",
    "한국 국적만",
    "국적 소지자만",
    "외국인 제외",
    "일본인 제외",
    "외국인 참여 불가",
    "외국인 신청 불가",
    "대한민국 국민만",
    "한국 국민만",
    "대한민국 국민에 한함",
    "한국 국민에 한함",
    "대한민국 국민 한정",
    "한국 국민 한정",
)
_NATIONAL_EXCLUSIVE_LIMITS = (
    "대한민국 국민만",
    "한국 국민만",
    "대한민국 국민에 한함",
    "한국 국민에 한함",
    "대한민국 국민 한정",
    "한국 국민 한정",
)

_JP_RESIDENT_POS = (
    re.compile(r"한국\s*거주\s*일본인.{0,24}(참여|신청|대상|이용|참석).{0,8}가능"),
    re.compile(r"재한\s*일본인.{0,24}(참여|신청|대상|이용|참석)"),
    re.compile(
        r"일본\s*국적.{0,16}(한국|국내)\s*거주.{0,24}(참여|신청)\s*가능"
    ),
)

_FOREIGN_RESIDENT_POS = (
    re.compile(r"외국인.{0,12}(도\s*)?(참여|신청|이용|참석)\s*가능"),
    re.compile(r"국적\s*제한\s*없음"),
    re.compile(r"외국인\s*청년.{0,16}(대상|참여|신청|이용)"),
    re.compile(r"체류\s*자격과\s*무관"),
)

_KR_JAPAN_ACTIVITY_POS = (
    re.compile(r"일본\s*(유학|취업|연수|워킹홀리데이|어학연수)"),
    re.compile(r"일본어\s*(학습|교육|수업|과정|연수|교실)"),
    re.compile(r"일본\s*문화\s*(교류|체험|이해|강좌)"),
)

_EXCHANGE_POS = (
    re.compile(r"한일\s*(교류|청년|포럼|공동|설명회)"),
    re.compile(r"한·일\s*(교류|청년|포럼)"),
    re.compile(r"양국\s*관계"),
)

_CONTENT_JP_RESIDENT_POS = _JP_RESIDENT_POS + (
    re.compile(r"한국\s*거주\s*일본인.{0,16}(위한|대상|안내|생활)"),
)
_CONTENT_FOREIGN_POS = _FOREIGN_RESIDENT_POS
_CONTENT_KR_JAPAN_POS = _KR_JAPAN_ACTIVITY_POS + (
    re.compile(r"일본\s*(생활|어학|유학|취업)\s*(정보|안내)"),
)
_CONTENT_EXCHANGE_POS = _EXCHANGE_POS


@dataclass(frozen=True)
class RelevanceResult:
    confirmed_axes: tuple[str, ...]
    reason_codes: tuple[str, ...]

    @property
    def confirmed(self) -> bool:
        return bool(self.confirmed_axes)


@dataclass(frozen=True)
class ScreeningResult:
    region_scope: RegionScope
    relevance: RelevanceResult
    disposition: str
    job_stage: str | None
    reason_codes: tuple[str, ...]


def _sentences(text: str) -> tuple[str, ...]:
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(text or "") if part.strip()]
    if not parts and (text or "").strip():
        return ((text or "").strip(),)
    return tuple(parts)


def _has_any(sentence: str, needles: tuple[str, ...]) -> bool:
    return any(needle in sentence for needle in needles)


def _has_national_exclusive_limit(text: str) -> bool:
    return any(phrase in (text or "") for phrase in _NATIONAL_EXCLUSIVE_LIMITS)


def _positive_without_negation(
    text: str,
    patterns: tuple[re.Pattern[str], ...],
    extra_negation: tuple[str, ...] = (),
) -> bool:
    for sentence in _sentences(text):
        if not any(pattern.search(sentence) for pattern in patterns):
            continue
        if _has_any(sentence, _NEGATION_GENERAL + extra_negation):
            continue
        return True
    return False


def _resident_axis_allowed(text: str) -> bool:
    return not _has_national_exclusive_limit(text)


def classify_policy_relevance(text: str) -> RelevanceResult:
    body = text or ""
    axes: list[str] = []
    if _resident_axis_allowed(body) and _positive_without_negation(
        body, _JP_RESIDENT_POS, _NATIONALITY_LOCK
    ):
        axes.append(AXIS_JP_RESIDENTS_IN_KR)
    if _resident_axis_allowed(body) and _positive_without_negation(
        body, _FOREIGN_RESIDENT_POS, _NATIONALITY_LOCK
    ):
        axes.append(AXIS_FOREIGN_RESIDENTS_IN_KR)
    if _positive_without_negation(body, _KR_JAPAN_ACTIVITY_POS):
        axes.append(AXIS_KR_JAPAN_ACTIVITY)
    if _positive_without_negation(body, _EXCHANGE_POS):
        axes.append(AXIS_KR_JP_EXCHANGE)
    confirmed = tuple(axes)
    reasons: list[str] = []
    if not confirmed:
        reasons.append(REASON_RELEVANCE_UNCONFIRMED)
    return RelevanceResult(confirmed_axes=confirmed, reason_codes=tuple(reasons))


def classify_content_relevance(title: str, body: str) -> RelevanceResult:
    text = f"{title or ''}\n{body or ''}"
    axes: list[str] = []
    if _resident_axis_allowed(text) and _positive_without_negation(
        text, _CONTENT_JP_RESIDENT_POS, _NATIONALITY_LOCK
    ):
        axes.append(AXIS_JP_RESIDENTS_IN_KR)
    if _resident_axis_allowed(text) and _positive_without_negation(
        text, _CONTENT_FOREIGN_POS, _NATIONALITY_LOCK
    ):
        axes.append(AXIS_FOREIGN_RESIDENTS_IN_KR)
    if _positive_without_negation(text, _CONTENT_KR_JAPAN_POS):
        axes.append(AXIS_KR_JAPAN_ACTIVITY)
    if _positive_without_negation(text, _CONTENT_EXCHANGE_POS):
        axes.append(AXIS_KR_JP_EXCHANGE)
    confirmed = tuple(axes)
    reasons: list[str] = []
    if not confirmed:
        reasons.append(REASON_RELEVANCE_UNCONFIRMED)
    return RelevanceResult(confirmed_axes=confirmed, reason_codes=tuple(reasons))


def region_allows_mvp(scope: RegionScope) -> bool:
    return scope in {"capital", "nationwide_or_online"}


def screen_policy(
    policy: dict[str, Any],
    text: str,
    *,
    body_usable: bool,
) -> ScreeningResult:
    eligibility = classify_eligibility(policy.get("zipCd"))
    operator = classify_operator(policy)
    scope = classify_region_scope(
        eligibility=eligibility, text=text, operator=operator
    )
    relevance = classify_policy_relevance(text)
    return _combine(
        scope=scope,
        relevance=relevance,
        body_usable=body_usable,
        review_stage="region_review",
    )


def screen_content(
    title: str,
    body: str,
    *,
    body_usable: bool,
) -> ScreeningResult:
    scope = classify_region_scope(eligibility="unknown", text=f"{title}\n{body}")
    relevance = classify_content_relevance(title, body)
    return _combine(
        scope=scope,
        relevance=relevance,
        body_usable=body_usable,
        review_stage="content_review",
    )


def _combine(
    *,
    scope: RegionScope,
    relevance: RelevanceResult,
    body_usable: bool,
    review_stage: str,
) -> ScreeningResult:
    if scope == "noncapital":
        return ScreeningResult(
            region_scope=scope,
            relevance=relevance,
            disposition="non_target",
            job_stage=None,
            reason_codes=(),
        )
    if scope == "unknown":
        reasons = region_reason_codes(scope)
        return ScreeningResult(
            region_scope=scope,
            relevance=relevance,
            disposition="region_review_required",
            job_stage=review_stage,
            reason_codes=reasons or (REASON_REGION_SCOPE_UNKNOWN,),
        )
    if not region_allows_mvp(scope):
        return ScreeningResult(
            region_scope=scope,
            relevance=relevance,
            disposition="region_review_required",
            job_stage=review_stage,
            reason_codes=(REASON_REGION_SCOPE_UNKNOWN,),
        )
    if not body_usable:
        return ScreeningResult(
            region_scope=scope,
            relevance=relevance,
            disposition="region_review_required",
            job_stage=review_stage,
            reason_codes=(REASON_RELEVANCE_UNCONFIRMED,),
        )
    if relevance.confirmed:
        return ScreeningResult(
            region_scope=scope,
            relevance=relevance,
            disposition="target",
            job_stage=None,
            reason_codes=(),
        )
    reasons = relevance.reason_codes or (REASON_RELEVANCE_UNCONFIRMED,)
    return ScreeningResult(
        region_scope=scope,
        relevance=relevance,
        disposition="region_review_required",
        job_stage=review_stage,
        reason_codes=reasons,
    )
