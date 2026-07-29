"""자동 데이터 수집 및 DB 저장 파이프라인.

온통청년 청년정책 오픈 API 에서 정책 데이터를 수집하고, Gemini 로 읽기 쉬운
마크다운 요약으로 가공한 뒤 Supabase `curations` 테이블에 저장한다.
"""

import os
import re
import sys

import requests
from supabase import Client, create_client

# google-genai 미설치 등 임포트 실패 시에도 파이프라인이 죽지 않도록 방어한다
try:
    from google import genai
    from google.genai import types

    _GENAI_AVAILABLE = True
except ImportError:
    genai = None
    types = None
    _GENAI_AVAILABLE = False

# 앱과 동일한 테이블을 사용한다 (app/lib/types.ts 의 Curation 스키마 참고)
TABLE_NAME = "curations"

# 온통청년 청년정책 오픈 API 엔드포인트 (최신 JSON 스펙)
YOUTH_API_URL = "https://www.youthcenter.go.kr/go/ythip/getPlcy"

# API 에서 한 번에 조회할 정책 개수
MAX_ITEMS = 5

# API 응답 대기 최대 시간(초)
REQUEST_TIMEOUT = 15

# 수도권 청년 타겟: 중앙부처(전국) + 서울/경기/인천만 수집
TARGET_REGION_KEYWORDS = (
    "중앙부처",
    "전국",
    "서울",
    "경기",
    "인천",
)
# 온통청년 지역코드(polyBizSecd / zipCd) — 중앙부처·수도권
TARGET_REGION_CODES = (
    "003001",  # 중앙부처(전국)
    "003002001",  # 서울
    "003002004",  # 인천
    "003002008",  # 경기
)

# Gemini 요약 모델 및 지시사항(시스템 프롬프트)
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

# Gemini API 키를 읽어 클라이언트를 초기화한다 (키가 없으면 요약을 건너뛴다)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = None
if _GENAI_AVAILABLE and GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)


def get_supabase_client() -> Client:
    """환경 변수를 읽어 Supabase 클라이언트를 초기화한다.

    GitHub Actions 에서는 Secrets 로 주입되며, 로컬에서는 셸 환경 변수로 전달한다.
    쓰기 작업이 필요하므로 service role 키를 사용한다.
    """
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
    # <br>, <p> 등 태그를 제거하고, 연속 공백/개행을 하나로 정리
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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
    # 지역코드 필드 결합 (콤마로 여러 코드가 올 수 있음)
    region_codes = " ".join(
        str(policy.get(key) or "")
        for key in ("polyBizSecd", "zipCd", "rgLcnCd")
    )
    if any(code in region_codes for code in TARGET_REGION_CODES):
        return True

    # 기관명·기관그룹·지역명 텍스트에서 타겟 키워드 탐색
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

    # 지역 메타가 전혀 없으면 API 필드 누락으로 보고 통과시킨다
    if not region_codes.strip() and not region_text.strip():
        return True

    return False


def summarize_with_gemini(raw_text: str, url: str) -> str:
    """정책 원문과 URL 을 Gemini 로 읽기 쉬운 마크다운 요약으로 가공한다.

    키가 없거나(패키지 미설치 포함) 호출 중 에러가 나면, 파이프라인을 멈추지 않고
    원본 텍스트(raw_text)를 그대로 반환한다.
    """
    if not raw_text:
        return raw_text

    if not _GENAI_AVAILABLE or not client:
        print("[pipeline] 경고: Gemini 사용 불가(키/패키지 없음), 원본을 사용합니다.")
        return raw_text

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"[원문]\n{raw_text}\n\n[URL]\n{url}",
            config=types.GenerateContentConfig(
                system_instruction=GEMINI_SYSTEM_PROMPT
            ),
        )
        summary = (getattr(response, "text", "") or "").strip()
        # 응답이 비어 있으면(안전 필터 등) 원본을 그대로 사용
        return summary or raw_text
    except Exception as e:  # noqa: BLE001 - 요약 실패 시 원본으로 폴백
        print(f"Gemini API 에러 발생: {e}")
        return raw_text


def fetch_real_policies() -> list[dict]:
    """온통청년 청년정책 오픈 API(최신 JSON 스펙)를 호출해 정책 데이터를 가져온다.

    응답은 JSON 이며, result.youthPolicyList 배열을 순회한다.
    각 정책의 고유번호(plcyNo), 제목(plcyNm), 카테고리(plcyTpNm/lclsfNm),
    정책설명(plcyExplnCn) + 지원내용(plcySprtCn), 신청/참고 URL, 지역/기관
    메타데이터를 추출해 원본 형태로 반환한다.
    (지역 필터·중복 검사·Gemini 요약은 save_policies 단계에서 수행한다.)
    API 키가 없으면 에러 대신 경고를 출력하고 빈 리스트를 반환한다.
    """
    api_key = os.environ.get("YOUTH_API_KEY")
    if not api_key:
        print(
            "[pipeline] 경고: 환경 변수 YOUTH_API_KEY 가 설정되지 않아 수집을 중단합니다."
        )
        return []

    params = {
        "apiKeyNm": api_key,
        "pageNum": 1,
        "pageSize": MAX_ITEMS,
        "pageType": 1,
        "rtnType": "json",
    }

    # 온통청년 방화벽이 python-requests 기본 User-Agent 를 차단하므로
    # 일반 크롬 브라우저처럼 보이도록 헤더를 위장한다
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/xml, text/xml, */*; q=0.01",
    }

    # allow_redirects=False: 잘못된 요청 시 서버가 8080 포트로 리다이렉트하는데
    # 해당 포트는 외부(GitHub Actions)에서 접근이 막혀 타임아웃되므로 따라가지 않는다
    response = requests.get(
        YOUTH_API_URL,
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
        allow_redirects=False,
    )
    response.raise_for_status()

    data = response.json()
    policy_list = data.get("result", {}).get("youthPolicyList", [])

    policies: list[dict] = []
    for policy in policy_list:
        plcy_no = policy.get("plcyNo")
        title = policy.get("plcyNm", "").strip()
        # 정책설명 + 지원내용을 합쳐 본문을 구성한 뒤 HTML 태그를 제거한다
        raw_content = (
            f"{policy.get('plcyExplnCn', '')}\n\n{policy.get('plcySprtCn', '')}"
        )
        content = strip_html(raw_content).strip()

        # 고유번호/제목/내용이 비어 있으면 저장 가치가 없으므로 건너뛴다
        if not plcy_no or not title or not content:
            continue

        # 온통청년 응답에서 신청 URL 또는 참고 URL 을 순서대로 확보한다
        url = (
            policy.get("aplyUrlAddr")
            or policy.get("refUrlAddr1")
            or policy.get("refUrlAddr2")
            or "링크 없음"
        )

        # 지역 필터용 원본 필드와 카테고리를 함께 보관한다
        policies.append(
            {
                "plcy_no": plcy_no,
                "title": title,
                "category": extract_category(policy),
                "content": content,
                "url": url,
                "polyBizSecd": policy.get("polyBizSecd") or "",
                "zipCd": policy.get("zipCd") or "",
                "rgLcnCd": policy.get("rgLcnCd") or "",
                "pvsnInstGroupNm": policy.get("pvsnInstGroupNm") or "",
                "cnsgNmor": policy.get("cnsgNmor") or "",
                "mngtMsonNm": policy.get("mngtMsonNm") or "",
                "sprvsnInstNm": policy.get("sprvsnInstNm") or "",
                "operInstNm": policy.get("operInstNm") or "",
                "rgtrInstCdNm": policy.get("rgtrInstCdNm") or "",
            }
        )

        if len(policies) >= MAX_ITEMS:
            break

    return policies


def save_policies(supabase: Client, policies: list[dict]) -> int:
    """타겟 지역의 신규 정책만 Gemini 로 요약해 curations 테이블에 저장한다.

    각 정책의 고유번호(plcyNo)로 변하지 않는 slug 를 만들고, Gemini 호출 전에
    (1) Supabase 중복 검사, (2) 수도권·중앙부처 지역 필터를 거친다.
    중복이거나 타겟 외 지역이면 요약/저장을 건너뛴다. 저장 성공 행 수를 반환한다.
    """
    rows = []
    for policy in policies:
        title = policy["title"]
        # plcyNo 기반의 영구 불변 고유 slug (정책마다 항상 동일)
        slug = f"policy-{policy['plcy_no']}"

        # 중복 검사: 이미 수집된 정책이면 Gemini 호출 없이 건너뛴다
        existing_data = (
            supabase.table("curations")
            .select("slug")
            .eq("slug", slug)
            .execute()
        )
        if existing_data.data:
            print(f"⏭️ 이미 수집된 정책입니다 (스킵): {title}")
            continue

        # 지역 필터: 중앙부처·서울·경기·인천이 아니면 Gemini 호출 없이 건너뛴다
        if not is_target_region(policy):
            print(f"🚫 타겟 지역 아님 (스킵): {title}")
            continue

        # 새로운 정책만 Gemini 로 마크다운 요약 가공 (실패 시 원본 그대로 사용)
        ai_content = summarize_with_gemini(policy["content"], policy["url"])

        rows.append(
            {
                "slug": slug,
                # API 정책 유형/대분류 기반 자동 할당 (없으면 '기타')
                "category": policy["category"],
                "title": title,
                # 요약본 앞부분을 목록용 요약으로 사용
                "summary": ai_content[:60],
                "content": ai_content,
            }
        )

    # 저장할 신규 정책이 없으면 조기 종료
    if not rows:
        return 0

    # slug 가 겹치면 기존 행을 덮어쓰도록 upsert 사용 (unique 제약 위반 방지)
    response = (
        supabase.table(TABLE_NAME).upsert(rows, on_conflict="slug").execute()
    )
    saved = len(response.data or [])
    return saved


def main() -> None:
    print("[pipeline] Supabase 클라이언트 초기화 중...")
    supabase = get_supabase_client()

    print("[pipeline] 온통청년 API 정책 데이터 수집 중...")
    policies = fetch_real_policies()
    print(f"[pipeline] {len(policies)}건의 정책 데이터를 수집했습니다.")

    if not policies:
        print("[pipeline] 수집된 데이터가 0건입니다")
        return

    print("[pipeline] Supabase 저장 중...")
    saved = save_policies(supabase, policies)
    print(f"[pipeline] 저장 완료: {saved}건")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - 파이프라인 실패를 명확히 로깅
        print(f"[pipeline] 실행 실패: {exc}", file=sys.stderr)
        sys.exit(1)
