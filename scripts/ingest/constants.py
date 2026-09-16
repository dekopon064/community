"""수집 구현 설정. 숫자는 공식 API 제한이 아니다.

SQL RPC 기본값과 의미를 맞출 때 이 모듈을 기준으로 한다.
"""

from __future__ import annotations

DEFAULT_LEASE_SECONDS = 120
LEASE_SECONDS_MIN = 30
LEASE_SECONDS_MAX = 3600
DEFAULT_JOB_LEASE_SECONDS = 600
AI_CLAIM_LIMIT = 10
# 첫 실패와 재시도를 포함한 AI processing 총 시도 횟수.
# SQL fail_processing_job의 v_ai_max_attempts와 같아야 한다.
AI_MAX_ATTEMPTS = 3
AI_RETRY_BACKOFF_SECONDS = 30
MAX_BATCH_BYTES = 65536
