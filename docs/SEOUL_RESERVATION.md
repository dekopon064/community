# 서울 공공서비스예약 — 로컬 연결 기반

2026-10-01 실제 50행 조사 보고 `RPT-20261001T091711Z-codex-build-progress-b6907ee9`에 근거합니다.
시험 데이터는 보고의 조건을 반영해 재구성한 **합성 응답**입니다. 실제 API 원문 전체를 저장한 fixture가 아닙니다.

## 구현·실행 경계

- `SeoulReservationConnector`: 새 source ID `seoul_reservation`, provider `seoul`, kind `content`, rest, untrusted ordering.
- 기존 `HttpClient`, `BatchResult`, `Checkpoint`, `ObservationRecord`, `EvaluationResult`, `JobPlan` 형식을 재사용합니다.
- SQL에 `seoul_reservation`을 **enabled=false / testing_only**로 추가했습니다. 운영 CLI/예약에는 등록하지 않았습니다. 기존 두 수집원과 `capital_v1`은 그대로 유지합니다.
- `normalize_seoul_item()`은 **observe_only, jobs 없음, v1 gate_facts 없음**인 원문 관측을 반환합니다.
- `assess_seoul_program(record, now=시간대있는_datetime)`은 별도 `ProgramAssessment`를 반환합니다. 새 SQL evaluator가 동일한 구조화 facts를 판정하며, 아래 별도 adapter/RPC로 격리 DB의 저장·review·재평가·AI **대기**를 연결했습니다.
- `preview_seoul()`은 명시적으로 호출하는 제한 읽기/정규화 함수입니다. DB·AI 모듈을 import하지 않습니다. 테스트에서는 가짜 HTTP transport만 사용합니다.
- 실제 API HTTP 호출은 이번 구현 검증에서 하지 않았습니다. 운영 scheduler·환경설정·기존 `.env.local`은 변경하지 않았습니다.

## 정규화

SVCID·제목·공식 상세 링크·분류·대상·원문 장소/지역·비용·접수상태·신청/운영기간·이용시간·이미지 참조·좌표를 보존합니다.
본문은 plain text와 프로그램 설명을 분리하고, 표는 행/열·header·rowspan/colspan·중첩 표 연결을 보존합니다.
원문 HTML과 본문 href/src는 내부 비실행 `source_body_html`에 보존하며 재파싱 근거로 사용합니다. HTML로 렌더링하거나 브라우저 DTO에 그대로 보내면 안 됩니다.
주의사항의 개인 신청 제한·서류·마감 조건도 판정에 포함합니다.
스크립트·스타일·iframe/object 내용은 plain text 사실로 읽지 않습니다. 표의 언어·회차 관계를 전체 프로그램의 단일 언어로 바꾸지 않습니다.
공통 이용안내만 있거나 설명이 이미지/첨부에 의존하면 설명 부족을 구분합니다. OCR·첨부 다운로드는 하지 않습니다.

API 날짜의 시간대 해석은 Asia/Seoul(+09:00)입니다. `.0`를 포함한 timestamp를 파싱하며 날짜만 있는 값은 날짜 그대로 유지합니다.
00:02 종료를 23:59로 바꾸지 않습니다. 신청기간과 운영기간을 별도 유지하고 실패/누락 상태를 보존합니다.
source_created/updated_at은 없으며 접수 시각이나 SVCID로 만들어 넣지 않습니다.
revision hash는 허용한 의미 있는 원문 필드·본문의 안정적 직렬화에 기반합니다. 조회 시각·페이지·전체 건수는 제외합니다.

## 로컬 판정 계약과 최소 DB 추가안

schema `program-scope-v1-local`, profile `program_capital_v1_local`은 **로컬 계약**이며 기존 SQL에서 지원하지 않습니다.

`ProgramFacts`는 다음 사실을 분리합니다.

- 콘텐츠 목적과 개인/개인·단체/기관 전용 신청 주체
- 실제 진행 방식, 개최 지역과 원문 근거
- 거주 조건과 근거, 원문 대상 문자열, 명시 조건
- 인터넷/현장/전화 신청 방식
- 무료·유료·미확인, 확인된 비용 표현
- 원문 모집 상태, 부족값, 충돌, 미확정 노출 정책

판정 결과:

| 결과 | 기존 표현과의 로컬 대응 | 의미 |
|---|---|---|
| in_scope | target, jobs 없음 | 필요한 근거가 확보된 서비스 범위 후보. AI 실행·공개 승인 아님 |
| out_of_scope | non_target, jobs 없음 | 명확한 취업/기관/국적/지역 범위 밖. 외국인 자격 사실로 저장하지 않음 |
| review_required | observe_only + content_review JobPlan | 목적·장소·대상·문서조건 부족이나 실제 충돌. 아직 enqueue하지 않음 |
| not_currently_available | observe_only, jobs 없음 | 예약마감·접수종료·신청기간 종료/미시작·운영 종료. 서비스 범위 밖과 구분 |

일반 프로그램 국적 미표기는 review 사유가 아닙니다. 기관 소재지와 개최지, 인터넷 예약과 온라인 진행을 구분합니다.
개최지는 본문에 명시된 장소를 우선 사용하며 제공자 장소/지역은 본문 장소와 연결될 때만 보조 근거로 사용합니다. 온라인 참여 불가를 온라인 진행으로 추출하지 않습니다.
온라인은 전국/수도권 포함 거주 조건을 확인하고, 비수도권 현장/혼합·비수도권 거주자 전용은 제외합니다.
제한없음 대상 필드가 있어도 개인 신청불가/기관 전용 조건은 우선 확인합니다. 명시 개인 신청 가능과 단체에만 필요한 서류는 구분합니다.
성인도 가능한 아동·가족 프로그램은 단어 하나로 아동 전용 제외하지 않습니다. 조건은 그대로 보존합니다.
유료·가족·아동 프로그램도 포함합니다. `editorial_pending`은 빈 배열로 유지하며 세부 가족 유형·카테고리·우선순위를 추가하지 않습니다. 무료/유료 충돌은 review 사유지만 금액 미표기 자체를 모두 review로 보내지는 않습니다.
학교·기관 이름이나 단체 서류만으로 제외하지 않습니다. 명확한 개인 신청 불가/학교·기관 전용 근거가 있어야 하며, 개인 허용 안내가 함께 있으면 충돌로 보존합니다.
정책/금융·주민등록등본 같은 확인되지 않은 중요 증빙 조건은 일반 공개 프로그램처럼 자동 추정하지 않습니다.

추출기는 제한된 규칙 기반입니다. 모든 한국어 조건·주소·국적·회차를 이해하는 일반 자연어 파서가 아닙니다. 지원하지 않는 표현은 부족/불명으로 남기는 방향이며 추가 표본으로 보완해야 합니다.
본문의 확정 마감·명시 신청/운영기간과 API 값의 충돌을 확인합니다. 지원하는 기간은 연도까지 명시된 두 날짜이며 안전하게 연결하지 못하는 명시 기간은 확인 필요로 남깁니다.
상세 페이지를 자동으로 추가 읽지 않습니다. API 밖 최신 모집 상태 비교는 다음 연결 단계의 명시적 상세 근거 계약이 필요합니다.

현재 v1 facts는 `activity_region`·`application_actor`·충돌 근거를 표현하지 못하고 SQL에서도 허용하지 않습니다.
새 SQL은 `program-scope-v1-local / program_capital_v1_local` 계약을 별도 revision facts 테이블에서 사용합니다. 기존 strict v1 facts에 개최지를 넣지 않습니다.
Python의 로컬 결과만 v1 RPC에 보내면 안 됩니다. 기존 두 수집원의 v1을 바꾸거나 기존 데이터를 일괄 재평가하는 변경도 이번 구현에 포함하지 않았습니다.
로컬 SQL 파일과 서버 계약을 작성하고 격리 메모리 PostgreSQL에서 실행했습니다. Production 적용·실제 관리 입력 화면·AI claim 계약 연결은 완료하지 않았습니다.

## 제한 조회와 실패

기본값은 50행 × 1페이지, 페이지당 HTTP 최대 3회 예산, 기존 15초 timeout·8MB 응답 제한입니다.
설정 검증 범위는 요청당 1~1,000행, 최대 5페이지입니다. 이는 구현 안전값이며 공식 호출 빈도 한도가 아닙니다.
키는 `SEOUL_OPEN_DATA_API_KEY` 서버 환경 또는 테스트 주입으로 받습니다. 파일을 자동 로드/변경하지 않습니다.
API URL의 경로 키는 에러 메시지에 담지 않고 HttpClient 로그의 응답 헤더에도 비노출 처리합니다. credential echo 응답은 거부합니다.
HTTP 리다이렉트는 따르지 않습니다. 오류 JSON·응답 파손·조기 빈 페이지·미완성 페이지·반복/일부 중복 페이지·중복 ID·동일 ID 변경은 성공 빈 결과로 바꾸지 않습니다.

`page_limit`은 incomplete입니다. natural_end는 그 관측에서 목록 끝을 확인했다는 뜻이며 변경 가능한 API의 완전 동기화를 보장하지 않습니다.
전체 건수 변경은 incomplete/listing_changed로 반환합니다. 기존 원문 3건을 이유로 종료하지 않습니다.
행 checkpoint는 snapshot cursor가 아니며, 다음 실행은 fresh_from_origin을 사용합니다. 누락 항목을 삭제·마감 처리하지 않습니다.

## 로컬 검증

작업 폴더 `scripts`에서 `python -m unittest test_seoul_reservation test_ingest_assessment test_ingest test_ingest_common_run`.
첫 파일은 가짜 transport로 정상/빈 결과/오류/예산/크기/키 비노출, 정규화·표·날짜·조건·지역·충돌·신청 상태를 검증합니다.
나머지는 기존 두 connector·HTTP·capital_v1·공통 실행의 관련 회귀 검증입니다. 실제 API·Supabase·AI를 호출하지 않습니다.

## DB·관리자 입력 계약 (2026-10-01 추가)

- Migration: `supabase/migrations/20261001000000_seoul_program_contract.sql`.
- `ProgramObservationAdapter`는 주입받은 서버 RPC transport만 사용합니다. 환경파일 로딩·실API 호출·runner 활성화는 없습니다. 기존 run lease와 최대 40건 batch를 재사용합니다.
- `public.observe_seoul_program`은 기존 base 관측 RPC로 저장하고 같은 transaction에서 facts·판정·review/AI 대기를 갱신합니다. `upsert_source_observations_v4`에는 보내지 않습니다.
- `source_item_program_facts`는 원문 snapshot·최초 추출 facts·수정 facts·facts_version·결과를 revision별 보존합니다. 재관측은 운영자 facts를 덮지 않고 가용성만 재평가합니다. 새 원문 revision은 새 facts로 판정하고 과거 대기는 취소합니다. claimed job은 충돌로 차단하며 처리 완료 AI를 다시 대기시키지 않습니다.
- queue는 서비스 범위 통과 + 현재 신청 가능 + source enabled + 승인된 permission일 때만 생성합니다. 기본 비활성/testing_only 상태에서는 AI 대기를 생성하지 않습니다.
- 새 wrapper 5개(`observe_seoul_program`, `admin_program_list/detail/save/exclude`)만 service_role 실행 가능. 새 private 함수·테이블은 anon/authenticated/service_role 직접 접근을 허용하지 않습니다. 기존 private RPC 권한과 v1 함수는 변경하지 않았습니다.
- 관리자 endpoint는 `/api/admin/program-review`와 `/api/admin/program-review/[id]`입니다. 모든 요청은 requireAdmin 확인 후에만 기존 별도 service client를 생성합니다. POST는 same-Origin·JSON·200KB 제한·no-store를 유지하고, actor는 서버 검증 UUID입니다.
- `save_facts` 입력은 revision/version/note/patch/resolve입니다. actor·missing/conflicts 배열 자체는 받지 않습니다. 열린 사유에 필요한 patch 필드만 허용하고, 사실 보충·근거 기록·이력·재평가를 원자적으로 처리합니다. 미지원 사유는 해소하지 않습니다. 제외는 서비스 범위 제외 플래그·이력이며 외국인 자격 불가 사실로 바꾸지 않습니다.
- 매 평가 때 개최지·온라인 거주 범위의 실제 근거, 설명·링크·기간 부족, 기간 순서·비용 모순을 다시 확인합니다. 사유 삭제나 불가능한 enum 조합만으로 AI 대기 전환하지 않습니다. 날짜 단위 종료일은 당일 포함입니다.
- DTO는 원문 제목/공식 링크/plain text, 검토 facts·최초 facts·기간·조건·사유별 한국어 입력 안내·이력만 반환합니다. 원문 HTML/raw payload/provider response는 반환하지 않습니다. 본문과 조건은 HTML 실행 없이 일반 텍스트로 표시해야 합니다.

**관리 화면 후속 필드**: 진행 방식, 실제 개최지/수도권 여부·근거, 온라인 거주 범위·근거, 신청 주체/조건, 신청/운영 기간·정밀도·충돌 근거, 접수 상태, 확인한 비용, 부족한 설명/공식 링크와 사실 수정 근거입니다. `editableFields`에 해당하는 칸만 활성화하고 `reasonGuidance`로 안내해야 합니다. 이번에는 기존 11칸 v1 UI를 확장하거나 새 화면을 만들지 않았습니다. 새 source의 운영 활성화 전에 새 DTO/입력 UI를 연결해야 합니다.

**AI 미연결 경계**: processing_jobs의 대기 행 생성만 확인했습니다. 기존 worker의 capital_v1 claim/gate·canonical source/후보 source 허용 계약은 그대로입니다. 새 profile을 worker가 소비하거나 후보를 만드는지 검증하지 않았으며, 대기 행이 있다는 것을 AI 실행 가능/후보 생성 성공으로 해석하면 안 됩니다. 이 연결은 별도 후속 설계·승인이 필요합니다.

격리 SQL 테스트는 기존 설치 PGlite의 새 메모리 PostgreSQL을 사용하며 DB URL·키·`.env.local`을 읽지 않습니다. 원본 curations CREATE가 저장소에 없어 최소 합성 pre-P0 table을 만든 뒤 canonical migration을 적용합니다. 실제 Supabase/PostgREST·여러 독립 연결의 lock 경쟁은 미검증입니다.

로컬 실행 예(각 변수에는 **설치된 도구 경로만** 지정):
`MACHIMOA_PGLITE_MODULE=<PGlite index.js 경로>`, `MACHIMOA_TEST_PYTHON=<requests가 설치된 Python 경로>` 후 `node scripts/test_seoul_program_sql.mjs`.
독립 검토 교정 회귀: 같은 환경으로 `node scripts/test_seoul_program_sql.mjs --review-fixes`.
서버 대역: `node scripts/test_program_review.mjs`.

Rollback `supabase/rollback/20261001000000_seoul_program_contract_down.sql`은 source 비활성·queued 취소·신규 함수 제거만 합니다. source/관측 snapshot/facts/관리 이력은 삭제하지 않습니다. 활성 claim이 있으면 중단합니다. 원문/이력 데이터 손실은 없지만 실행 API를 되돌리므로 UI/adapter 사용도 중단해야 합니다. 재적용은 기존 테이블/등록 행을 검토한 별도 recovery migration이 필요하며 원 CREATE를 반복 실행하면 안 됩니다. 취소된 대기를 자동 복구하거나 과거 facts를 이전 의미로 변환하지 않습니다.

지금 사용자 환경설정 변경은 필요 없습니다. Production migration·permission 승인·source 활성화·실제 Supabase 연결은 후속 UI/worker 계약 검토와 별도 운영 적용 승인 후 진행합니다.

## 관리자 사실 입력 UI 연결 (2026-10-01 후속)

위 DB 계약 단계에서 미연결이었던 입력 UI를 기존 `/ko/admin`의 사람 사실 review에 연결했습니다. 기존 사실 목록 RPC가 서울 예약 항목도 반환하므로 새 목록을 합치지 않습니다. `sourceName=seoul_reservation`일 때만 새 program 상세/저장 API를 사용하며, 기존 온통청년·후보 경로는 유지합니다. SQL/DTO/서버 권한 계약은 이번 UI 작업에서 변경하지 않았습니다.

- `ProgramReviewPanel`은 원문 일반 텍스트·조건, 최초 추출 facts와 현재 저장 facts를 구분합니다. 보완한 공식 링크도 수집된 원문 링크와 구분해 열 수 있습니다. HTML은 React 일반 텍스트로만 표시합니다.
- `editableFields`의 입력만 만들고 그 외 값은 비교 영역에서 읽기 전용으로 표시합니다. `reasonGuidance`를 한국어로 안내합니다. 해소 체크는 알려진 사유 중 실제 해당 facts 입력을 지원하는 경우만 표시합니다.
- 변경된 필드만 patch로 보내며 revision/version/note/resolve 계약을 유지합니다. missing/conflicts·actor는 브라우저가 지정하지 않습니다. 성공 표시·남은 사유·이력·AI 대기는 서버 응답을 사용합니다. 대기는 실행·후보·게시 성공이 아닙니다.
- 원문 접수 상태와 신청/운영 기간을 판정 결과와 별도로 표시합니다. 다른 review 사유가 남아도 예약 마감은 확인할 수 있습니다. 날짜만 명시된 종료일은 당일 포함이며 임의 시간을 만들지 않습니다.
- 미저장 값이 있으면 목록/단계 이동을 막고 취소하거나 저장하도록 안내합니다. 실패/충돌 시 입력을 유지하며 최신 값 불러오기는 명시적으로 입력을 버리는 동작입니다. 처리 완료 시 편집을 닫고, 제외는 사유와 최종 확인 후 요청합니다.

### 안전한 합성 UI 시험 실행

실제 DB·OAuth·API를 호출하지 않는 시험입니다. 아래 값은 모두 합성 값이며 `.env.local`을 수정하지 않습니다. 세 터미널의 작업 위치는 현재 worktree입니다.

1. 첫 터미널: `node scripts/test_auth.mjs --serve` (가짜 인증, 54329).
2. 둘째 터미널: 아래 Python 경로를 설정한 뒤 `node scripts/test_program_ui.mjs --serve` (합성 RPC, 54330). 실제 SQL 평가기가 아니며 충돌/실패 주입은 이 시험 서버에만 있습니다.
3. 셋째 터미널: 아래 환경변수를 프로세스에만 지정하고 `npm run dev -- --webpack --port 3105`.

```powershell
# 둘째 터미널: 이 PC에 이미 설치된 requests 지원 Python입니다.
$env:MACHIMOA_TEST_PYTHON='C:\manga-translator\Miniconda3\python.exe'
node scripts/test_program_ui.mjs --serve
```

```powershell
# 셋째 터미널: Production 값 대신 아래 합성/loopback 값만 사용합니다.
$env:NEXT_PUBLIC_SUPABASE_URL='http://127.0.0.1:54330'
$env:NEXT_PUBLIC_SUPABASE_ANON_KEY='local-test-publishable-key'
$env:SUPABASE_SERVICE_ROLE_KEY='sb_secret_local-test-only-fake'
$env:MACHIMOA_REVIEW_MODE='database'
$env:MACHIMOA_ADMIN_USER_IDS='00000000-0000-4000-8000-000000000001'
$env:AUTH_SITE_URL='http://localhost:3105'
$env:NEXT_PUBLIC_TURNSTILE_SITE_KEY='synthetic-build-site-key'
$env:NEXT_PUBLIC_TURNSTILE_SUBMIT_ACTION='feedback_submit'
$env:NEXT_PUBLIC_TURNSTILE_DELETE_ACTION='feedback_delete'
$env:NEXT_TELEMETRY_DISABLED='1'
npm run dev -- --webpack --port 3105
```

`http://localhost:3105/ko/admin` → Google로 로그인 → **가짜 운영자 계정** 선택. 일반 시험 계정으로 이미 로그인했다면 로그인 상태 화면에서 로그아웃한 뒤 선택합니다. 실제 Google 계정을 입력하는 과정은 없습니다.

첫 합성 항목에서 개최지/근거를 보충하고 해소를 체크해 저장 결과를 확인합니다. 둘째 항목에서 신청 종료일·기간 근거만 보충하면 개최지 사유는 남고 기간 입력은 읽기 전용으로 전환됩니다. 셋째 항목은 미지원 사유 유지, 공식 링크 보충/예약 마감 표시, 사유를 남긴 제외를 확인하는 자료입니다. 수정 근거를 정확히 `충돌 시험` 또는 `실패 시험`으로 입력하면 시험 서버가 오류를 반환하고 편집값 유지 여부를 볼 수 있습니다. 서버 재시작은 합성 상태를 초기화합니다. 종료 시 각 터미널에서 Ctrl+C를 누릅니다.

단위/서버 대역 시험: 위 Python 도구 변수만 지정한 뒤 `node scripts/test_program_ui.mjs`, `node scripts/test_program_review.mjs`. 기존 사실·후보 회귀는 `node scripts/test_admin_review.mjs`입니다. 실제 DB 저장/SQL 평가/실제 계정/AI 연결을 이 UI 시험으로 검증했다고 해석하면 안 됩니다.

다음은 새 profile에 대한 AI worker 입력·gate·claim·canonical source/후보 source 계약 검토입니다. source는 여전히 비활성/testing_only이며 이 문서의 UI 연결은 운영 활성화 승인이 아닙니다.


## Program AI 연결 (2026-10-01 로컬 구현)

- `20261001000001_seoul_program_ai.sql`은 서울 전용 `claim_seoul_program_ai`, `finish_seoul_program_ai`, `fail_seoul_program_ai`와 최소 `program_candidate_inputs`를 추가합니다. 새 public wrapper만 service_role 실행 가능하며 새 private 함수/테이블의 직접 권한은 없습니다. source 비활성/testing_only 및 기존 두 source의 claim/enqueue/publish/lease 함수는 유지합니다.
- 문화체험(`MAXCLASSNM`)만 공개 `user_category=program`으로 투영하고 원문 분류를 보존합니다. 다른 API 분류의 claim은 반환하지 않으며 이를 서비스 부적격 판정으로 바꾸지 않습니다. 기존 program 범위/자격/기관/지역/기간 gate는 별도로 통과해야 합니다.
- `scripts/ingest/program_ai.py`는 RPC와 provider callback을 주입받습니다. 환경파일/키 로딩·client/provider 생성·실API·CLI 활성화는 없습니다. `ProgramAIAdapter.from_supabase(client)`는 호출자가 제공한 서버 client의 RPC만 사용합니다.
- 기존 `process_ai_jobs`에 명시적 `program_adapter`와 정확한 단일 target/revision을 주면 새 경로를 사용합니다. 일반 호출·정기 workflow는 기존 경로입니다. 서울을 legacy payload 경로로 처리하는 요청은 거부합니다. source identity를 추가하는 것만으로 실행 권한이 생기지 않습니다.
- 실제 provider adapter의 bound `summarize_ko`를 전달하면 `summarize_program_ko`와 별도 program 시스템 프롬프트를 사용합니다. 기존 provider의 출력 schema·비용 상한·번역 단위 검증을 재사용합니다. 현재 검증 facts를 입력하고, 원문에서 최초 추출된 값과의 변경 필드를 표시합니다. 원문 normalized_payload는 수정하지 않습니다.
- 한국어 상세에 현재 facts의 조건·비용·신청/운영기간 안내를 결정적으로 보존하여 번역 입력에도 전달합니다. 일본어 형식/지역명/숫자 누락을 검사하지만 조건 의미 전체의 번역 품질 보장은 아닙니다. 실제 후보를 사람이 검토해야 합니다. provider 반환 facts는 DB 사실로 저장하지 않습니다.
- claim은 source/revision/profile/facts_version/현재 시각 판정/permission/열린 review를 검사하고 지정 항목만 잠금 아래 선택합니다. 현재 facts의 설명/링크를 사용하므로 원문 부족값을 사람이 보완할 수 있습니다. 획득 시각/lease 만료값으로 같은 worker ID의 과거 시도를 구별합니다.
- 만료된 서울 AI claim은 gate 검사 전에 queued로 회수합니다. queued 자체는 실행 권한이 아니며 재평가·권한 gate를 통과해야 다시 claim할 수 있습니다. 이 때문에 마감/비활성 상태의 abandoned claim이 관리자 수정·원문 갱신을 영구 차단하지 않습니다. 활성 lease는 회수하지 않습니다.
- finish는 current revision/facts version/claim 시도/lease/permission/판정을 다시 확인하여 후보 pending·입력 이력·job 완료를 한 transaction으로 처리합니다. 같은 완료 packet의 재요청은 기존 candidate ID를 반환하고 덮어쓰지 않습니다. 통신 결과 불명은 success/fail RPC 추가 호출로 대체하지 않습니다. fail 역시 획득 시도를 확인한 뒤 기존 retry 함수를 사용합니다.
- program 후보에는 기존 신청 마감 날짜를 투영합니다. 원래 신청/운영기간과 day/second 정밀도는 입력 메타데이터에 둘 다 보존합니다. 기존 공통 program/event 기간 제약을 완화하지 않습니다.
- canonical mapping은 서울 한 쌍만 추가합니다. 후보 digest는 서울에서만 current program facts/input metadata를 포함합니다. 기존 후보 편집 6개 값·반려·검증 actor/이력은 유지합니다. 화면에는 입력/현재 facts 버전과 두 기간 및 게시 불가 안내만 추가합니다. payload/원문 HTML은 추가 노출하지 않습니다.
- facts가 후보 생성 후 변경되면 수정 저장/반려는 가능하지만 게시를 차단하며 자동 AI 재실행은 하지 않습니다. 수동 재생성/사실 재대조 완료 기능은 아직 없고 후속 과제입니다. source 권한·마감·제외·판정 역시 게시 직전에 검사합니다. 기존 overwrite=false와 공개/승인 이력 transaction은 유지합니다.

### 새 로컬 시험

- `scripts`에서 `python -X utf8 -m unittest test_program_ai`: 합성 SQL 형태 context와 가짜 RPC/provider. 실제 번역 품질 검증이 아닙니다.
- `node scripts/test_program_ai_sql.mjs`: 기존 설치된 `MACHIMOA_PGLITE_MODULE` 및 `MACHIMOA_TEST_PYTHON` 도구 경로만 지정합니다. 새 메모리 PostgreSQL과 합성 pre-P0 curations schema를 사용합니다. DB URL·키·환경파일을 읽지 않습니다. SQL DTO를 Python 가짜 provider 입력/완료 packet으로 연결하고 실제 격리 SQL로 후보/job/버전/rollback을 확인합니다. PostgREST·독립 세션 경쟁·실제 AI 실행은 아닙니다.
- `node scripts/test_program_candidate.mjs`: 후보 DTO의 명시적 projection, program 버전/기간, 인증 차단·actor 위조·오류/no-store의 테스트 대역 검증입니다.
- source activation, permission 승인, migration 운영 적용, 정기 수집/AI 연결, 실제 콘텐츠 1건 시험 및 게시는 별도 승인 단계입니다.

### Rollback 한계

`20261001000001_seoul_program_ai_down.sql`은 worker 서울 호출을 먼저 중지한 뒤 사용합니다. program 입력 메타데이터·서울 후보·claimed job 참조가 있으면 실행을 거부하며 임의 삭제하지 않습니다. 무참조 상태에서만 공통 source 매핑/관리자 함수의 이전 정의를 복구하고 신규 계약을 제거합니다. 후보/처리 이력·공개 데이터를 되돌리는 파일이 아니며 운영 자료가 생기면 별도 보존/복구 계획이 필요합니다.

### 독립 PostgreSQL 연결 시험 (2026-10-01)

`scripts/test_program_ai_postgres.py`는 명시적으로 전달한 Docker CLI와 고유 시험 컨테이너만 사용합니다. `machimoa-program-ai-<8자리 hex>` 이름, 시험 목적 label, network none, 공개 포트/기존 bind 없음을 연결 전에 검사합니다. DB 이름은 `machimoa_ai_concurrency`로 고정하며 환경파일·DB URL·운영 키를 읽지 않습니다. 승인된 새 컨테이너의 tmpfs와 기존 `postgres:17.6-bookworm` 이미지로 실행했습니다. 재시작하면 시험 자료가 소실될 수 있습니다.

- 기본 실행: `python -X utf8 scripts/test_program_ai_postgres.py <docker.exe 절대경로> <시험 컨테이너명>`. 기존 schema가 있으면 거부합니다. 합성 pre-P0 curations bootstrap과 관련 migration을 준비하고 독립 psql 연결로 50개 검사를 수행했습니다. claim skip-locked, 중복 완료 idempotency, facts/revision/마감/제외/permission 변경 대 완료, 후보 편집/반려/게시 guard 대 facts 변경, 원자 rollback, bounded lock timeout을 확인했습니다.
- 후속 `--extra`: 같은 격리 schema에서 새로 추가한 14개 검사만 실행했습니다. 실제 Python adapter→PostgreSQL 호출과 가짜 provider, 원문 관측 RPC의 활성 claim 보호/rollback, 관리자 사실 저장의 동시 버전 충돌/이력/재평가, 실패 대 완료 및 완료 후 facts 변경을 확인했습니다. 앞선 합성 수집 lease가 종료돼야 새 시험 run을 시작하며 활성 lease를 강제로 지우지 않습니다.
- 통제된 두 시험 행의 역순 잠금으로 PostgreSQL deadlock `40P01`과 피해 transaction 해제를 확인했습니다. 이는 제품 RPC에서 deadlock을 발견했다는 뜻이 아니며, 시험한 제품 요청 경쟁에서는 deadlock이 관측되지 않았습니다. 모든 조합의 무교착을 보장하지 않습니다.
- PostgREST 경유·실제 Supabase schema 전체 일치·실제 번역 품질·실제 콘텐츠 게시는 미검증입니다. 후보 게시 guard는 합성 자료로만 검사했고 공개 baseline 행 수가 유지됨을 확인했습니다.
- 독립 검토에서 `--mount`의 명시적 mount 검사 누락을 교정했습니다. 이제 `HostConfig.Binds`, `HostConfig.Mounts`와 실제 `Mounts` 모두를 거부합니다. `--isolation-check`는 실제 무마운트 컨테이너와 합성 bind/volume/socket 거부 5개만 확인하며 SQL 검사를 반복하지 않습니다. 이번 실제 컨테이너에는 기존 mount가 없었습니다.
- 실행 후 새 시험 컨테이너만 중지합니다. 기존 컨테이너/volume은 삭제하거나 초기화하지 않으며 이 파일 자체도 컨테이너를 생성/삭제/시작하지 않습니다.
