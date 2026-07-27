"""자동 데이터 수집 및 DB 저장 파이프라인 (1단계 뼈대).

현재는 샘플 청년 정책 데이터를 생성하여 Supabase `curations` 테이블에 저장한다.
AI 가공(요약/카테고리 분류 등) 로직은 추후 이 스크립트에 추가될 예정이다.
"""

import os
import re
import sys
from datetime import datetime, timezone

from supabase import Client, create_client

# 앱과 동일한 테이블을 사용한다 (app/lib/types.ts 의 Curation 스키마 참고)
TABLE_NAME = "curations"


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


def slugify(title: str) -> str:
    """제목을 기반으로 URL 친화적인 slug 를 생성한다.

    한글 등 영숫자가 아닌 문자는 제거되므로, 뒤에 타임스탬프를 붙여 고유성을 확보한다.
    """
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{base or 'policy'}-{suffix}"


def fetch_sample_policies() -> list[dict]:
    """샘플 청년 정책 데이터를 생성한다.

    추후 실제 공공데이터 API 호출로 교체될 함수이다.
    각 항목은 원본 제목(title)과 원본 내용(content)만 담고 있으며,
    요약/카테고리 등의 가공은 이후 단계에서 채워진다.
    """
    return [
        {
            "title": "청년월세 특별지원",
            "content": (
                "만 19~34세 무주택 청년을 대상으로 월 최대 20만원의 임대료를 "
                "최대 12개월간 지원하는 사업입니다. 소득 및 재산 요건 충족 시 "
                "복지로 또는 주소지 관할 주민센터를 통해 신청할 수 있습니다."
            ),
        },
        {
            "title": "청년내일저축계좌",
            "content": (
                "근로 중인 저소득 청년이 매월 일정 금액을 저축하면 정부가 "
                "동일하거나 그 이상 금액을 매칭 지원하여 목돈 마련을 돕는 자산형성 "
                "사업입니다. 가입 기간 동안 근로를 유지해야 지원금을 받을 수 있습니다."
            ),
        },
        {
            "title": "국민취업지원제도",
            "content": (
                "취업을 희망하는 청년에게 취업지원 서비스와 함께 구직촉진수당을 "
                "제공하는 제도입니다. 유형에 따라 소득·재산 요건이 다르며, "
                "고용센터 또는 워크넷을 통해 신청할 수 있습니다."
            ),
        },
    ]


def save_policies(supabase: Client, policies: list[dict]) -> int:
    """샘플 데이터를 curations 테이블 스키마에 맞춰 저장한다.

    테이블은 slug, category, title, summary, content 컬럼을 요구한다.
    category / summary 는 AI 가공 전이므로 임시 값으로 채운다.
    저장에 성공한 행 수를 반환한다.
    """
    rows = []
    for policy in policies:
        title = policy["title"]
        content = policy["content"]
        rows.append(
            {
                "slug": slugify(title),
                # AI 가공(카테고리 분류) 전 임시 값
                "category": "청년정책",
                "title": title,
                # AI 가공(요약) 전 임시 값 - 원본 내용 앞부분을 사용
                "summary": content[:60],
                "content": content,
            }
        )

    response = supabase.table(TABLE_NAME).insert(rows).execute()
    saved = len(response.data or [])
    return saved


def main() -> None:
    print("[pipeline] Supabase 클라이언트 초기화 중...")
    supabase = get_supabase_client()

    print("[pipeline] 샘플 청년 정책 데이터 수집 중...")
    policies = fetch_sample_policies()
    print(f"[pipeline] {len(policies)}건의 샘플 데이터를 생성했습니다.")

    print("[pipeline] Supabase 저장 중...")
    saved = save_policies(supabase, policies)
    print(f"[pipeline] 저장 완료: {saved}건")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - 파이프라인 실패를 명확히 로깅
        print(f"[pipeline] 실행 실패: {exc}", file=sys.stderr)
        sys.exit(1)
