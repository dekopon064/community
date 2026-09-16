"""1차 지역 범위. 중앙기관만으로 전국이라고 추정하지 않는다."""

from __future__ import annotations

import re
from typing import Any, Literal

from ingest.models import (
    REASON_REGION_SCOPE_UNKNOWN,
    RegionScope,
)

Eligibility = Literal[
    "capital_only",
    "non_capital_only",
    "mixed_capital_and_non_capital",
    "unknown",
]
OperatorKind = Literal[
    "central",
    "capital_operator",
    "non_capital_operator",
    "unknown",
]
Disposition = Literal["target", "non_target", "region_review_required"]

CAPITAL_ZIP_PREFIXES = ("11", "28", "41")
CENTRAL_PROVIDER_GROUP = "0054001"
CAPITAL_INCLUDED = frozenset({"capital_only", "mixed_capital_and_non_capital"})

# Explicit nationwide / online-participation evidence. Application URLs are not enough.
_NATIONWIDE_PHRASES = (
    "전국 대상",
    "전국대상",
    "전국 거주",
    "전국거주",
    "전국 청년",
    "전국청년",
    "거주 지역 제한 없음",
    "거주지역 제한 없음",
    "지역 제한 없음",
    "지역제한 없음",
    "전국 어디서나",
)
_ONLINE_PARTICIPATION_PHRASES = (
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

_CAPITAL_PLACE_RE = re.compile(
    r"서울(?:특별시|시)?|인천(?:광역시|시)?|경기도|경기\s*광주"
)
_AMBIGUOUS_GWANGJU_RE = re.compile(r"(?<![가-힣])광주(?:광역시|시|군)?(?![가-힣])")
_GWANGJU_METRO_RE = re.compile(r"광주광역시")
_GYEONGGI_GWANGJU_RE = re.compile(r"경기(?:도)?\s*광주")
_NONCAPITAL_PLACE_RE = re.compile(
    r"부산(?:광역시|시)?|대구(?:광역시|시)?|대전(?:광역시|시)?|"
    r"울산(?:광역시|시)?|세종(?:특별자치시|시)?|강원(?:특별자치도|도)?|"
    r"충청?북도|충북|충청?남도|충남|전라?북도|전북|전라?남도|전남|"
    r"경상?북도|경북|경상?남도|경남|제주(?:특별자치도|도|시)?|서귀포|"
    r"화순군|화순"
)
_EXCLUSIVE_NONCAPITAL_RE = re.compile(
    r"(거주자만|주민만|현장\s*한정|현장만|전용|해당\s*지역만)"
)


def _five_digit_tokens(raw: object) -> tuple[str, ...]:
    text = str(raw or "")
    tokens: list[str] = []
    current: list[str] = []
    for char in text:
        if char.isdigit():
            current.append(char)
            if len(current) == 5:
                tokens.append("".join(current))
                current = []
        else:
            current = []
    return tuple(tokens)


def _prefix_kind(zip_code: str) -> Literal["capital", "non_capital"]:
    return "capital" if zip_code.startswith(CAPITAL_ZIP_PREFIXES) else "non_capital"


def classify_eligibility(zip_cd: object) -> Eligibility:
    """zipCd 지원지역. 수도권/비수도권 혼합은 기관 충돌이 아니다."""
    tokens = _five_digit_tokens(zip_cd)
    if not tokens:
        return "unknown"
    kinds = {_prefix_kind(token) for token in tokens}
    if kinds == {"capital"}:
        return "capital_only"
    if kinds == {"non_capital"}:
        return "non_capital_only"
    return "mixed_capital_and_non_capital"


def _code_operator_kind(raw: object) -> OperatorKind | None:
    tokens = _five_digit_tokens(raw)
    if not tokens:
        text = str(raw or "").strip()
        if len(text) >= 2 and text[:2] in CAPITAL_ZIP_PREFIXES and text[:2].isdigit():
            return "capital_operator"
        return None
    kinds = {_prefix_kind(token) for token in tokens}
    if kinds == {"capital"}:
        return "capital_operator"
    if kinds == {"non_capital"}:
        return "non_capital_operator"
    return None


def classify_operator(policy: dict[str, Any]) -> OperatorKind:
    group = str(policy.get("pvsnInstGroupCd") or "").strip()
    if group == CENTRAL_PROVIDER_GROUP:
        return "central"

    for key in (
        "operInstCd",
        "operInstCdNm",
        "sprvsnInstCd",
        "sprvsnInstCdNm",
        "rgtrInstCd",
        "rgtrInstCdNm",
        "rgtrInstNm",
    ):
        kind = _code_operator_kind(policy.get(key))
        if kind is not None:
            return kind

    oper_name = str(policy.get("operInstNm") or policy.get("operInstCdNm") or "").strip()
    sprvsn = str(
        policy.get("sprvsnInstNm") or policy.get("sprvsnInstCdNm") or ""
    ).strip()
    rgtr = str(policy.get("rgtrInstNm") or policy.get("rgtrInstCdNm") or "").strip()
    if not oper_name and not sprvsn and not rgtr:
        return "unknown"
    if not oper_name and (sprvsn or rgtr):
        return "unknown"
    return "unknown"


def _has_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def explicit_nationwide_or_online(text: str) -> bool:
    """본문 명시만 인정. 온라인 신청/접수만으로는 부족하다."""
    compact = re.sub(r"\s+", " ", text or "")
    if _has_phrase(compact, _NATIONWIDE_PHRASES):
        return True
    if _has_phrase(compact, _ONLINE_PARTICIPATION_PHRASES):
        return True
    return False


def _has_capital_place(text: str) -> bool:
    return bool(_CAPITAL_PLACE_RE.search(text or ""))


def _has_noncapital_place(text: str) -> bool:
    return bool(_NONCAPITAL_PLACE_RE.search(text or ""))


def _has_ambiguous_gwangju(text: str) -> bool:
    raw = text or ""
    if _GYEONGGI_GWANGJU_RE.search(raw) or _GWANGJU_METRO_RE.search(raw):
        return False
    return bool(_AMBIGUOUS_GWANGJU_RE.search(raw))


def _exclusive_noncapital(text: str) -> bool:
    raw = text or ""
    if not _has_noncapital_place(raw):
        return False
    if _has_capital_place(raw):
        return False
    if _has_ambiguous_gwangju(raw) and not _GWANGJU_METRO_RE.search(raw):
        return False
    return bool(_EXCLUSIVE_NONCAPITAL_RE.search(raw)) or bool(
        re.search(r"화순군|서귀포|제주(?:특별자치도|도|시)", raw)
    )


def classify_region_scope(
    *,
    eligibility: Eligibility,
    text: str,
    operator: OperatorKind | None = None,
) -> RegionScope:
    """operator는 증거일 뿐 전국/수도권 추정에 쓰지 않는다."""
    del operator
    body = text or ""
    nationwide = explicit_nationwide_or_online(body)
    exclusive_noncapital = _exclusive_noncapital(body)
    capital_place = _has_capital_place(body)
    noncapital_place = _has_noncapital_place(body)
    ambiguous_gwangju = _has_ambiguous_gwangju(body)

    if nationwide and not exclusive_noncapital:
        return "nationwide_or_online"

    if eligibility == "non_capital_only" and not nationwide:
        return "noncapital"

    if exclusive_noncapital:
        if eligibility == "capital_only":
            return "unknown"
        if eligibility == "mixed_capital_and_non_capital":
            return "unknown"
        return "noncapital"

    if ambiguous_gwangju and not capital_place and not nationwide:
        return "unknown"

    if eligibility == "capital_only":
        return "capital"

    if eligibility == "mixed_capital_and_non_capital":
        if noncapital_place and not capital_place:
            return "unknown"
        return "capital"

    if capital_place and not exclusive_noncapital:
        return "capital"

    return "unknown"


def classify_content_region_scope(title: str, body: str) -> RegionScope:
    text = f"{title or ''}\n{body or ''}"
    return classify_region_scope(eligibility="unknown", text=text, operator="unknown")


def region_reason_codes(scope: RegionScope) -> tuple[str, ...]:
    if scope == "unknown":
        return (REASON_REGION_SCOPE_UNKNOWN,)
    return ()


def classify_policy_disposition(policy: dict[str, Any]) -> Disposition:
    """zip·본문 1차 지역만. relevance가 없으면 target이 되지 않는다."""
    eligibility = classify_eligibility(policy.get("zipCd"))
    operator = classify_operator(policy)
    text = "\n".join(
        str(policy.get(key) or "")
        for key in ("plcyNm", "plcyExplnCn", "plcySprtCn")
    )
    scope = classify_region_scope(
        eligibility=eligibility, text=text, operator=operator
    )
    if scope == "noncapital":
        return "non_target"
    return "region_review_required"
