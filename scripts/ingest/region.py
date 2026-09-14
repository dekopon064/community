"""정책 지역 판정. 003 부분 문자열과 기관명 키워드로 결과를 뒤집지 않는다."""

from __future__ import annotations

from typing import Any, Literal

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


def classify_policy_disposition(policy: dict[str, Any]) -> Disposition:
    eligibility = classify_eligibility(policy.get("zipCd"))
    operator = classify_operator(policy)
    capital_included = eligibility in CAPITAL_INCLUDED

    if operator == "unknown":
        return "region_review_required"
    if operator == "central":
        return "target" if capital_included else "region_review_required"
    if operator == "capital_operator":
        return "target" if capital_included else "region_review_required"
    if operator == "non_capital_operator":
        if eligibility == "non_capital_only":
            return "non_target"
        return "region_review_required"
    return "region_review_required"
