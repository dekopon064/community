"""자동 데이터 수집 및 DB 저장 파이프라인 (1단계 뼈대).

현재는 샘플 청년 정책 데이터를 생성하여 Supabase `curations` 테이블에 저장한다.
AI 가공(요약/카테고리 분류 등) 로직은 추후 이 스크립트에 추가될 예정이다.
"""

import os
import re
import sys
import uuid
from datetime import datetime, timezone

import feedparser
from supabase import Client, create_client

# 앱과 동일한 테이블을 사용한다 (app/lib/types.ts 의 Curation 스키마 참고)
TABLE_NAME = "curations"

# 대한민국 정책브리핑 정책 RSS 피드
POLICY_RSS_URL = "https://www.korea.kr/rss/policy.xml"

# 한 번에 수집할 최신 글 개수
MAX_ITEMS = 5


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
    """정책브리핑 RSS 피드를 파싱해 최신 정책 글을 가져온다.

    RSS 의 title(제목)과 description(내용)을 추출하며,
    description 에 포함된 HTML 태그는 정규식으로 제거해 순수 텍스트만 남긴다.
    """
    feed = feedparser.parse(POLICY_RSS_URL)

    policies: list[dict] = []
    for entry in feed.entries[:MAX_ITEMS]:
        title = strip_html(getattr(entry, "title", "")).strip()
        content = strip_html(getattr(entry, "description", "")).strip()

        # 제목이나 내용이 비어 있으면 저장 가치가 없으므로 건너뛴다
        if not title or not content:
            continue

        policies.append({"title": title, "content": content})

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

    print("[pipeline] 정책브리핑 RSS 피드 수집 중...")
    policies = fetch_real_policies()
    print(f"[pipeline] {len(policies)}건의 정책 데이터를 수집했습니다.")

    if not policies:
        print("[pipeline] 수집된 데이터가 없어 저장을 건너뜁니다.")
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
