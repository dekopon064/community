"""자동 데이터 수집 및 DB 저장 파이프라인.

온통청년 청년정책 오픈 API 에서 정책 데이터를 수집해 Supabase `curations`
테이블에 저장한다. AI 가공(요약/카테고리 분류 등) 로직은 추후 추가될 예정이다.
"""

import os
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests
from supabase import Client, create_client

# 앱과 동일한 테이블을 사용한다 (app/lib/types.ts 의 Curation 스키마 참고)
TABLE_NAME = "curations"

# 온통청년 청년정책 오픈 API 엔드포인트 (공식 청년정책 목록 조회)
YOUTH_API_URL = "https://www.youthcenter.go.kr/opi/youthPlcyList.do"

# 한 번에 수집할 정책 개수
MAX_ITEMS = 5

# API 응답 대기 최대 시간(초)
REQUEST_TIMEOUT = 15


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


def slugify(title: str, index: int) -> str:
    """제목을 기반으로 URL 친화적인 slug 를 생성한다.

    한글 등 영숫자가 아닌 문자는 제거되므로, 뒤에 타임스탬프 + 루프 인덱스 +
    짧은 랜덤 텍스트를 강제로 결합해 무조건 고유한 값이 되도록 만든다.
    이렇게 하면 같은 초에 여러 건이 처리되거나, 서로 다른 실행이 같은 초에
    겹쳐도 slug 충돌이 발생하지 않는다.
    """
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    # uuid 앞 6자리로 실행 간 충돌까지 방지
    unique = uuid.uuid4().hex[:6]
    return f"{base or 'policy'}-{timestamp}-{index}-{unique}"


def strip_html(raw: str) -> str:
    """HTML 태그를 제거하고 공백을 정리해 순수 텍스트만 반환한다."""
    if not raw:
        return ""
    # <br>, <p> 등 태그를 제거하고, 연속 공백/개행을 하나로 정리
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_real_policies() -> list[dict]:
    """온통청년 청년정책 오픈 API 를 호출해 정책 데이터를 가져온다.

    응답은 XML 이며, requests 로 받아 xml.etree.ElementTree 로 파싱한다.
    각 정책의 제목(polyBizSjnm)과 소개(polyItcnCn)를 추출하고,
    소개에 포함된 HTML 태그는 strip_html 로 제거해 순수 텍스트만 남긴다.
    API 키가 없으면 에러 대신 경고를 출력하고 빈 리스트를 반환한다.
    """
    api_key = os.environ.get("YOUTH_API_KEY")
    if not api_key:
        print(
            "[pipeline] 경고: 환경 변수 YOUTH_API_KEY 가 설정되지 않아 수집을 중단합니다."
        )
        return []

    params = {
        "openApiVlak": api_key,
        "display": MAX_ITEMS,
        "pageIndex": 1,
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

    root = ET.fromstring(response.content)

    policies: list[dict] = []
    # youthPlcyList.do 응답은 <youthPolicyList> 안에 <youthPolicy> 항목이 반복된다
    for item in root.iter("youthPolicy"):
        title = (item.findtext("polyBizSjnm") or "").strip()
        content = strip_html(item.findtext("polyItcnCn") or "").strip()

        # 제목이나 내용이 비어 있으면 저장 가치가 없으므로 건너뛴다
        if not title or not content:
            continue

        policies.append({"title": title, "content": content})

        if len(policies) >= MAX_ITEMS:
            break

    return policies


def save_policies(supabase: Client, policies: list[dict]) -> int:
    """샘플 데이터를 curations 테이블 스키마에 맞춰 저장한다.

    테이블은 slug, category, title, summary, content 컬럼을 요구한다.
    category / summary 는 AI 가공 전이므로 임시 값으로 채운다.
    이미 존재하는 slug 라면 에러 대신 덮어쓰기(upsert)한다.
    저장에 성공한 행 수를 반환한다.
    """
    rows = []
    for index, policy in enumerate(policies, start=1):
        title = policy["title"]
        content = policy["content"]
        rows.append(
            {
                "slug": slugify(title, index),
                # AI 가공(카테고리 분류) 전 임시 값
                "category": "청년정책",
                "title": title,
                # AI 가공(요약) 전 임시 값 - 원본 내용 앞부분을 사용
                "summary": content[:60],
                "content": content,
            }
        )

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
