"""자동 데이터 수집 및 검수 대기 등록 파이프라인.

온통청년 청년정책 오픈 API에서 정책 데이터를 수집하고, 한국어 Gemini 가공과
조건부 일본어 번역 뒤 `public.enqueue_curation_candidate` RPC(16인자)로
검수 대기 후보만 등록한다. 공개 `curations` 테이블은 직접 쓰지 않는다.
요약은 검수자가 작성하므로 파이프라인이 채우지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

# google-genai 미설치 등 임포트 실패 시에도 파이프라인이 죽지 않도록 방어한다
try:
    from google import genai
    from google.genai import types

    _GENAI_AVAILABLE = True
except ImportError:
    genai = None
    types = None
    _GENAI_AVAILABLE = False

YOUTH_API_URL = "https://www.youthcenter.go.kr/go/ythip/getPlcy"
MAX_CANDIDATES_PER_RUN = 5
FETCH_PAGE_SIZE = 5
MAX_FETCH_PAGES = 10
REQUEST_TIMEOUT = 15

YOUTHCENTER_SOURCE = "youthcenter"
ENQUEUE_RPC_NAME = "enqueue_curation_candidate"
ALLOWED_ENQUEUE_OUTCOMES = frozenset({"inserted", "duplicate"})
ENQUEUE_PARAM_NAMES = (
    "p_source",
    "p_source_item_id",
    "p_source_revision_hash",
    "p_slug",
    "p_title_ko",
    "p_content_ko",
    "p_raw_payload",
    "p_ai_status_ko",
    "p_category",
    "p_summary_ko",
    "p_source_url",
    "p_ai_model",
    "p_title_ja",
    "p_content_ja",
    "p_summary_ja",
    "p_ai_status_ja",
)
REMOVED_ENQUEUE_PARAM_NAMES = frozenset(
    {
        "p_title",
        "p_content",
        "p_summary",
        "p_ai_status",
    }
)
FORBIDDEN_ENQUEUE_FIELDS = frozenset(
    {
        "review_status",
        "reviewed_at",
        "reviewed_by",
        "review_notes",
        "published_at",
        "published_curation_id",
        "superseded_at",
        "superseded_by_candidate_id",
        "revision_seq",
        "created_at",
        "updated_at",
    }
)

RAW_PAYLOAD_KEYS = (
    "plcyNo",
    "plcyNm",
    "plcyExplnCn",
    "plcySprtCn",
    "aplyUrlAddr",
    "refUrlAddr1",
    "refUrlAddr2",
    "plcyTpNm",
    "lclsfNm",
    "mclsfNm",
    "polyBizSecd",
    "zipCd",
    "rgLcnCd",
    "pvsnInstGroupNm",
    "cnsgNmor",
    "mngtMsonNm",
    "sprvsnInstNm",
    "operInstNm",
    "rgtrInstCdNm",
)

REVISION_HASH_FIELDS = (
    "plcyNm",
    "plcyExplnCn",
    "plcySprtCn",
    "plcyTpNm",
    "lclsfNm",
    "mclsfNm",
    "source_url",
    "polyBizSecd",
    "zipCd",
    "rgLcnCd",
    "sprvsnInstNm",
    "operInstNm",
)

SOURCE_URL_FIELDS = ("aplyUrlAddr", "refUrlAddr1", "refUrlAddr2")
HTTP_URL_RE = re.compile(r"^https?://")

TARGET_REGION_KEYWORDS = (
    "중앙부처",
    "전국",
    "서울",
    "경기",
    "인천",
)
TARGET_REGION_CODES = (
    "003001",  # 중앙부처(전국)
    "003002001",  # 서울
    "003002004",  # 인천
    "003002008",  # 경기
)

GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_SYSTEM_PROMPT = """너는 다정한 청년 정책 도우미야. 정책 원문과 URL을 받으면, 반드시 아래 양식을 지켜서 마크다운으로 요약해 줘.

💎 **Gemini가 요약한 청년정책입니다!** (이 문구를 맨 위에 고정으로 넣어줘)

### 🧑‍🤝‍🧑 누가 받을 수 있나요?
(대상 요약)

### 🎁 어떤 혜택이 있나요?
(지원 내용 요약)

### 🏃‍♂️ 어떻게 신청하나요?
(신청 방법과 기간 요약)

🔗 **원문 링크:** (제공된 URL 그대로 출력)
"""

GEMINI_JA_SYSTEM_PROMPT = """You translate a Korean youth-policy title and markdown body into Japanese.

Return only a JSON object with these string keys:
{"title_ja": "...", "content_ja": "..."}

Rules:
- title_ja is the Japanese title
- content_ja is the Japanese markdown body
- Do not add surrounding prose
- Do not copy Korean text into the Japanese fields
"""

_JSON_FENCE_RE = re.compile(
    r"^```(?:json)?\s*\r?\n?(.*?)\r?\n?```\s*$",
    re.IGNORECASE | re.DOTALL,
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = None
if _GENAI_AVAILABLE and GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)


class PipelineError(Exception):
    """파이프라인 처리 오류."""


class TransformError(PipelineError):
    """수집원 응답을 enqueue 파라미터로 바꾸지 못함."""


class EnqueueError(PipelineError):
    """검수 대기 RPC 호출 또는 응답이 유효하지 않음."""


@dataclass
class YouthcenterCandidate:
    source_item_id: str
    slug: str
    title: str  # cleaned plcyNm; enqueue p_title_ko
    content: str  # cleaned original body; Korean Gemini input / fallback
    category: str
    source_url: str | None
    raw_payload: dict[str, Any]
    source_revision_hash: str


@dataclass
class PipelineStats:
    pages_fetched: int = 0
    collected: int = 0
    region_excluded: int = 0
    in_run_duplicates: int = 0
    selected: int = 0
    processed: int = 0
    stop_reason: str | None = None
    transform_errors: int = 0
    rpc_inserted: int = 0
    rpc_duplicate: int = 0
    superseded: int = 0
    rpc_failures: int = 0
    ai_status_ko_counts: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    ai_status_ja_counts: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    ai_status_ja_not_called: int = 0

    @property
    def has_errors(self) -> bool:
        return self.transform_errors > 0 or self.rpc_failures > 0


def get_supabase_client() -> Any:
    """환경 변수를 읽어 Supabase 클라이언트를 초기화한다.

    GitHub Actions에서는 Secrets로 주입되며, 로컬에서는 셸 환경 변수로 전달한다.
    enqueue RPC 실행에 service role 키가 필요하다.
    """
    from supabase import create_client

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_service_key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_service_key:
        raise RuntimeError(
            "환경 변수 SUPABASE_URL / SUPABASE_SERVICE_KEY 가 설정되지 않았습니다."
        )

    return create_client(supabase_url, supabase_service_key)


def strip_html(raw: str) -> str:
    """HTML 태그를 제거하고 공백을 정리해 순수 텍스트만 반환한다."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_revision_text(raw: object) -> str:
    """revision hash 입력값을 HTML 제거·공백 정리한다."""
    if raw is None:
        return ""
    return strip_html(str(raw))


def extract_category(policy: dict) -> str:
    """온통청년 API 응답에서 정책 유형/대분류를 카테고리로 추출한다.

    plcyTpNm(정책유형명) → lclsfNm(대분류) → mclsfNm(중분류) 순으로 시도하고,
    모두 비어 있으면 기본값 '기타'를 반환한다.
    """
    for key in ("plcyTpNm", "lclsfNm", "mclsfNm"):
        value = (policy.get(key) or "").strip()
        if value:
            return value
    return "기타"


def is_target_region(policy: dict) -> bool:
    """중앙부처(전국) 또는 수도권(서울·경기·인천) 정책인지 판별한다.

    지역코드(polyBizSecd, zipCd)와 기관명/기관그룹 필드를 함께 검사한다.
    타겟에 해당하면 True, 순수 지방 자치단체 정책이면 False.
    지역 정보가 전혀 없으면(필드 공백) 오탐으로 전부 스킵하지 않도록 True.
    """
    region_codes = " ".join(
        str(policy.get(key) or "")
        for key in ("polyBizSecd", "zipCd", "rgLcnCd")
    )
    if any(code in region_codes for code in TARGET_REGION_CODES):
        return True

    region_text = " ".join(
        str(policy.get(key) or "")
        for key in (
            "pvsnInstGroupNm",
            "cnsgNmor",
            "mngtMsonNm",
            "sprvsnInstNm",
            "operInstNm",
            "rgtrInstCdNm",
        )
    )
    if any(keyword in region_text for keyword in TARGET_REGION_KEYWORDS):
        return True

    if not region_codes.strip() and not region_text.strip():
        return True

    return False


def is_http_url(value: object) -> bool:
    """운영 enqueue 계약과 같은 HTTP(S) URL인지 판별한다."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(HTTP_URL_RE.match(text)) and len(text) <= 2048


def select_source_url(policy: dict) -> str | None:
    """신청 URL → 참고 URL1 → 참고 URL2 순으로 첫 유효 HTTP(S) URL을 고른다."""
    for key in SOURCE_URL_FIELDS:
        candidate = policy.get(key)
        if isinstance(candidate, str) and is_http_url(candidate):
            return candidate.strip()
    return None


def copy_raw_payload(policy: dict) -> dict[str, Any]:
    """원본 응답에서 allowlist 19개 키만 새 dict로 복사한다."""
    return {key: policy.get(key) for key in RAW_PAYLOAD_KEYS}


def compute_source_revision_hash(
    policy: dict, source_url: str | None
) -> str:
    """고정 필드만으로 결정론적 SHA-256 소문자 hex를 계산한다."""
    payload: dict[str, str] = {}
    for key in REVISION_HASH_FIELDS:
        if key == "source_url":
            payload[key] = normalize_revision_text(source_url or "")
        else:
            payload[key] = normalize_revision_text(policy.get(key))
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def transform_youthcenter_policy(policy: dict) -> YouthcenterCandidate:
    """온통청년 응답 객체 하나를 enqueue 후보 데이터로 변환한다."""
    source_item_id = str(policy.get("plcyNo") or "").strip()
    if not source_item_id:
        raise TransformError("source_item_id(plcyNo) is missing")

    title = strip_html(str(policy.get("plcyNm") or ""))
    raw_content = (
        f"{policy.get('plcyExplnCn') or ''}\n\n{policy.get('plcySprtCn') or ''}"
    )
    content = strip_html(raw_content)
    if not title or not content:
        raise TransformError(
            f"title or content is empty for source_item_id={source_item_id}"
        )

    source_url = select_source_url(policy)
    return YouthcenterCandidate(
        source_item_id=source_item_id,
        slug=f"policy-{source_item_id}",
        title=title,
        content=content,
        category=extract_category(policy),
        source_url=source_url,
        raw_payload=copy_raw_payload(policy),
        source_revision_hash=compute_source_revision_hash(policy, source_url),
    )


def build_enqueue_params(
    candidate: YouthcenterCandidate,
    *,
    content_ko: str,
    ai_status_ko: str,
    title_ja: str | None,
    content_ja: str | None,
    ai_status_ja: str | None,
    ai_model: str | None,
) -> dict[str, Any]:
    """검수·공개 필드와 구 RPC 파라미터를 넣지 않은 enqueue 인자를 만든다."""
    params = {
        "p_source": YOUTHCENTER_SOURCE,
        "p_source_item_id": candidate.source_item_id,
        "p_source_revision_hash": candidate.source_revision_hash,
        "p_slug": candidate.slug,
        "p_title_ko": candidate.title,
        "p_content_ko": content_ko,
        "p_raw_payload": candidate.raw_payload,
        "p_ai_status_ko": ai_status_ko,
        "p_category": candidate.category,
        "p_summary_ko": None,
        "p_source_url": candidate.source_url,
        "p_ai_model": ai_model,
        "p_title_ja": title_ja,
        "p_content_ja": content_ja,
        "p_summary_ja": None,
        "p_ai_status_ja": ai_status_ja,
    }
    unexpected = FORBIDDEN_ENQUEUE_FIELDS.intersection(params)
    if unexpected:
        raise TransformError(f"forbidden enqueue fields present: {sorted(unexpected)}")
    if REMOVED_ENQUEUE_PARAM_NAMES.intersection(params):
        raise TransformError("removed enqueue params must not be sent")
    if set(params) != set(ENQUEUE_PARAM_NAMES):
        raise TransformError("enqueue params do not match the RPC contract")
    return params


def parse_enqueue_result(data: object) -> dict[str, Any]:
    """RPC 반환값이 허용된 한 행인지 검사한다."""
    row: object
    if isinstance(data, list):
        if len(data) != 1:
            raise EnqueueError(
                f"enqueue RPC must return exactly one row, got {len(data)}"
            )
        row = data[0]
    else:
        row = data

    if not isinstance(row, dict):
        raise EnqueueError("enqueue RPC row must be an object")

    outcome = row.get("outcome")
    if outcome not in ALLOWED_ENQUEUE_OUTCOMES:
        raise EnqueueError(f"unexpected enqueue outcome: {outcome!r}")
    if "candidate_id" not in row:
        raise EnqueueError("enqueue RPC row is missing candidate_id")
    return row


def enqueue_curation_candidate(supabase: Any, params: dict[str, Any]) -> dict[str, Any]:
    """검수 대기 후보 등록 RPC를 한 번 호출한다."""
    try:
        response = supabase.rpc(ENQUEUE_RPC_NAME, params).execute()
    except Exception as exc:  # noqa: BLE001 - RPC 실패를 항목 오류로 집계
        raise EnqueueError(f"enqueue RPC failed: {exc}") from None

    return parse_enqueue_result(getattr(response, "data", None))


def summarize_with_gemini(raw_text: str, url: str | None) -> tuple[str, str, str | None]:
    """정책 원문과 URL을 Gemini로 가공하고 한국어 상태와 함께 반환한다.

    호출에 실패해도 파이프라인을 멈추지 않는다. 공개 테이블로 우회하지 않고,
    검수용 원문 콘텐츠와 실패 상태를 함께 넘긴다. 원문 대체 성공 상태는 쓰지 않는다.
    """
    if not raw_text:
        return raw_text, "empty_response", None

    if not _GENAI_AVAILABLE or not client:
        print("[pipeline] Gemini unavailable (missing key or package); using source text.")
        return raw_text, "skipped_no_key", None

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"[원문]\n{raw_text}\n\n[URL]\n{url or ''}",
            config=types.GenerateContentConfig(
                system_instruction=GEMINI_SYSTEM_PROMPT
            ),
        )
        summary = (getattr(response, "text", "") or "").strip()
        if not summary:
            return raw_text, "empty_response", GEMINI_MODEL
        return summary, "success", GEMINI_MODEL
    except Exception:
        print("[pipeline] Gemini KO error: generate_content")
        return raw_text, "error", GEMINI_MODEL


def unwrap_optional_json_fence(text: str) -> str:
    """앞뒤 공백을 제거하고, 있으면 한 겹의 markdown json 펜스만 벗긴다."""
    stripped = text.strip()
    match = _JSON_FENCE_RE.fullmatch(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def parse_japanese_translation(raw: str) -> tuple[str, str] | None:
    """일본어 JSON object에서 title_ja/content_ja를 꺼낸다. 실패하면 None."""
    try:
        payload = json.loads(unwrap_optional_json_fence(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    title_ja = payload.get("title_ja")
    content_ja = payload.get("content_ja")
    if not isinstance(title_ja, str) or not isinstance(content_ja, str):
        return None
    title_ja = title_ja.strip()
    content_ja = content_ja.strip()
    if not title_ja or not content_ja:
        return None
    return title_ja, content_ja


def translate_with_gemini_ja(
    title_ko: str, content_ko: str
) -> tuple[str | None, str | None, str, str | None]:
    """한국어 제목·본문만 일본어 JSON으로 번역한다. 원본 API payload는 넣지 않는다."""
    if not title_ko or not content_ko:
        return None, None, "empty_response", None

    if not _GENAI_AVAILABLE or not client:
        print("[pipeline] Gemini JA unavailable (missing key or package); skipping Japanese.")
        return None, None, "skipped_no_key", None

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"[title_ko]\n{title_ko}\n\n[content_ko]\n{content_ko}",
            config=types.GenerateContentConfig(
                system_instruction=GEMINI_JA_SYSTEM_PROMPT
            ),
        )
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            return None, None, "empty_response", GEMINI_MODEL
        parsed = parse_japanese_translation(text)
        if parsed is None:
            print("[pipeline] Gemini JA parse_error")
            return None, None, "parse_error", GEMINI_MODEL
        title_ja, content_ja = parsed
        return title_ja, content_ja, "success", GEMINI_MODEL
    except Exception:
        print("[pipeline] Gemini JA error: generate_content")
        return None, None, "error", GEMINI_MODEL


def fetch_youth_api_page(page_num: int) -> list[dict]:
    """온통청년 API 한 페이지를 조회한다. 키와 query URL은 예외 메시지에 넣지 않는다."""
    api_key = os.environ.get("YOUTH_API_KEY")
    if not api_key:
        raise RuntimeError("환경 변수 YOUTH_API_KEY 가 설정되지 않았습니다.")

    params = {
        "apiKeyNm": api_key,
        "pageNum": page_num,
        "pageSize": FETCH_PAGE_SIZE,
        "pageType": 1,
        "rtnType": "json",
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/xml, text/xml, */*; q=0.01",
    }

    try:
        response = requests.get(
            YOUTH_API_URL,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        response.raise_for_status()
        data = response.json()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise RuntimeError(f"Youth API HTTP {status}") from None
    except ValueError:
        raise RuntimeError("Youth API returned non-JSON") from None
    except requests.RequestException:
        raise RuntimeError("Youth API request failed") from None

    policy_list = data.get("result", {}).get("youthPolicyList", [])
    if not isinstance(policy_list, list):
        raise RuntimeError("Youth API youthPolicyList is not a list")
    return [item for item in policy_list if isinstance(item, dict)]


def fetch_real_policies() -> list[dict]:
    """온통청년 청년정책 오픈 API 1페이지를 조회한다."""
    return fetch_youth_api_page(1)


def collect_target_policies(
    *,
    fetch_page: Callable[[int], list[dict]] | None = None,
    stats: PipelineStats | None = None,
) -> tuple[list[dict], PipelineStats]:
    """여러 페이지를 제한적으로 탐색해 지역 대상 정책을 최대 5건 고른다.

    Gemini와 enqueue RPC는 호출하지 않는다.
    """
    if fetch_page is None:
        fetch_page = fetch_youth_api_page
    if stats is None:
        stats = PipelineStats()

    selected: list[dict] = []
    seen: set[str] = set()

    for page_num in range(1, MAX_FETCH_PAGES + 1):
        page = fetch_page(page_num)
        stats.pages_fetched += 1
        stats.collected += len(page)
        if not page:
            stats.stop_reason = "empty_page"
            break

        for policy in page:
            if len(selected) >= MAX_CANDIDATES_PER_RUN:
                break
            source_item_id = str(policy.get("plcyNo") or "").strip()
            if not source_item_id:
                stats.transform_errors += 1
                print(
                    "[pipeline] transform error: source_item_id(plcyNo) is missing",
                    file=sys.stderr,
                )
                continue
            if source_item_id in seen:
                stats.in_run_duplicates += 1
                continue
            seen.add(source_item_id)
            if not is_target_region(policy):
                stats.region_excluded += 1
                title = strip_html(str(policy.get("plcyNm") or "")) or source_item_id
                print(f"[pipeline] region excluded: {title}")
                continue
            selected.append(policy)

        if len(selected) >= MAX_CANDIDATES_PER_RUN:
            stats.stop_reason = "candidate_cap"
            break
        if len(page) < FETCH_PAGE_SIZE:
            stats.stop_reason = "short_page"
            break
    else:
        stats.stop_reason = "max_pages"

    stats.selected = len(selected)
    return selected, stats


def process_policies(
    supabase: Any,
    policies: list[dict],
    *,
    summarize_ko: Callable[
        [str, str | None], tuple[str, str, str | None]
    ] = summarize_with_gemini,
    translate_ja: Callable[
        [str, str], tuple[str | None, str | None, str, str | None]
    ] = translate_with_gemini_ja,
    enqueue: Callable[[Any, dict[str, Any]], dict[str, Any]] = enqueue_curation_candidate,
    stats: PipelineStats | None = None,
) -> PipelineStats:
    """지역 필터 → 변환 → 한국어 AI → 조건부 일본어 AI → enqueue RPC.

    입력 리스트가 길어도 AI 처리 단계 진입은 실행당 최대 5건이다.
    한국어·일본어 Gemini는 각각 최대 5회다. 호출자가 넘긴 수집 통계는 덮어쓰지 않는다.
    """
    if stats is None:
        stats = PipelineStats()

    for policy in policies:
        source_item_id = str(policy.get("plcyNo") or "").strip()
        if not source_item_id:
            stats.transform_errors += 1
            print("[pipeline] transform error: source_item_id(plcyNo) is missing", file=sys.stderr)
            continue

        if not is_target_region(policy):
            stats.region_excluded += 1
            title = strip_html(str(policy.get("plcyNm") or "")) or source_item_id
            print(f"[pipeline] region excluded: {title}")
            continue

        try:
            candidate = transform_youthcenter_policy(policy)
        except TransformError as exc:
            stats.transform_errors += 1
            print(f"[pipeline] transform error: {exc}", file=sys.stderr)
            continue

        if stats.processed >= MAX_CANDIDATES_PER_RUN:
            break

        stats.processed += 1
        content_ko, ai_status_ko, ai_model = summarize_ko(
            candidate.content, candidate.source_url
        )
        stats.ai_status_ko_counts[ai_status_ko] += 1

        if ai_status_ko == "success" and content_ko:
            title_ja, content_ja, ai_status_ja, _ja_model = translate_ja(
                candidate.title, content_ko
            )
            stats.ai_status_ja_counts[ai_status_ja] += 1
        else:
            title_ja = None
            content_ja = None
            ai_status_ja = None
            stats.ai_status_ja_not_called += 1

        try:
            params = build_enqueue_params(
                candidate,
                content_ko=content_ko,
                ai_status_ko=ai_status_ko,
                title_ja=title_ja,
                content_ja=content_ja,
                ai_status_ja=ai_status_ja,
                ai_model=ai_model,
            )
        except TransformError as exc:
            stats.transform_errors += 1
            print(f"[pipeline] transform error: {exc}", file=sys.stderr)
            continue

        try:
            result = enqueue(supabase, params)
        except EnqueueError as exc:
            stats.rpc_failures += 1
            print(
                f"[pipeline] rpc error slug={candidate.slug}: {exc}",
                file=sys.stderr,
            )
            continue

        outcome = result["outcome"]
        if outcome == "inserted":
            stats.rpc_inserted += 1
            if result.get("superseded_candidate_id"):
                stats.superseded += 1
        elif outcome == "duplicate":
            stats.rpc_duplicate += 1

    return stats


def _format_status_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(
        f"{name}={counts[name]}" for name in sorted(counts)
    )


def print_stats(stats: PipelineStats) -> None:
    """수집·필터·RPC·분리된 AI 수치를 출력한다. 키와 payload 전문은 출력하지 않는다."""
    print(f"[pipeline] pages_fetched={stats.pages_fetched}")
    print(f"[pipeline] collected={stats.collected}")
    print(f"[pipeline] region_excluded={stats.region_excluded}")
    print(f"[pipeline] in_run_duplicates={stats.in_run_duplicates}")
    print(f"[pipeline] selected={stats.selected}")
    print(f"[pipeline] processed={stats.processed}")
    print(f"[pipeline] transform_errors={stats.transform_errors}")
    print(f"[pipeline] rpc_inserted={stats.rpc_inserted}")
    print(f"[pipeline] rpc_duplicate={stats.rpc_duplicate}")
    print(f"[pipeline] superseded={stats.superseded}")
    print(f"[pipeline] ai_status_ko: {_format_status_counts(stats.ai_status_ko_counts)}")
    print(
        "[pipeline] ai_status_ja: "
        f"{_format_status_counts(stats.ai_status_ja_counts)}; "
        f"not_called={stats.ai_status_ja_not_called}"
    )
    print(f"[pipeline] rpc_failures={stats.rpc_failures}")
    print(f"[pipeline] stop_reason={stats.stop_reason or ''}")


def main() -> int:
    print("[pipeline] Supabase client init...")
    supabase = get_supabase_client()

    print("[pipeline] Fetching Youth Center policies...")
    selected, stats = collect_target_policies()
    print(f"[pipeline] collected {stats.collected} policies from API")

    if selected:
        process_policies(supabase, selected, stats=stats)

    print_stats(stats)

    if stats.has_errors:
        print("[pipeline] completed with errors", file=sys.stderr)
        return 1

    if stats.selected == 0:
        print("[pipeline] warning: no region-matching policies selected")
        print("[pipeline] completed with warning")
        return 0

    print("[pipeline] completed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - 파이프라인 실패를 명확히 로깅
        print(f"[pipeline] 실행 실패: {exc}", file=sys.stderr)
        sys.exit(1)
