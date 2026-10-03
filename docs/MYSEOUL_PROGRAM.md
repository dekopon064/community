# My Seoul+ 최소 로컬 수집 기반

이번 구현은 운영 수집 등록이 아닙니다. `myseoul_program`은 로컬에서 직접 선택하는 connector 정의이며, 기존 source registry·기본 실행 대상·예약·DB·review·AI·공개 경로는 변경하지 않았습니다.

## 발견·전송

- 시작 URL: https://global.seoul.go.kr/hmpg/main/main.do
- 실제 관측 구조인 `div.edu-program > div.ep-head > span.ep-label`의 `교육 프로그램` 표제를 확인하고 그 컨테이너 안의 공개 상세 링크만 발견합니다. 더보기의 `span.hide`나 다른 영역의 같은 문구는 표제로 세지 않습니다. 컨테이너·표제 누락/중복/잘못된 부모 관계는 오류입니다.
- 관측 구조가 없는 경우에만 경계가 명확한 기존 h1~h4 표제 구조를 지원합니다. 관측 구조가 있으나 깨졌다면 이전 방식으로 조용히 대체하지 않습니다. 서로 다른 교육 영역을 병합하지 않습니다.
- 이 홈페이지 전용 connector는 홈페이지에 없는 프로그램을 발견하지 못합니다. 일반 수집의 제한된 전체 목록 reader는 아래 별도 계약을 사용합니다.
- identity는 `cntr_no:prgrm_no`입니다. 32자리 hex ID, 공식 HTTPS 호스트·상세 경로·허용 query를 검증합니다. 쿼리 순서/ID 대소문자/언어 링크를 중복 제거하고 상세는 한국어로 읽습니다. 같은 제목의 다른 ID는 유지합니다.
- 기본 상세 상한 8건, 요청 예산은 명시적으로 주입합니다(최대 21회). 홈페이지 1회 + 선택 상세 요청에 사용하며 자동 재시도·redirect는 없습니다. timeout 기본 15초, 각 응답 최대 1MB입니다. 이는 구현 상한이며 기관의 공식 제한이 아닙니다.
- 예산에 걸리면 `homepage_scope_complete=false`, `omitted`를 반환합니다. 성공한 경우에도 `source_complete=false`, coverage는 `homepage_education_only`입니다. 정렬은 `untrusted`이며 기존 3건 연속 발견 종료를 쓰지 않습니다.
- timeout·403/429/서버 오류·redirect·잘못된 MIME/UTF-8·템플릿 변경은 실패로 처리합니다. 확인된 빈 영역과 읽을 수 없는 목록을 구분합니다.
- 외부 신청 링크는 값만 보존하고 따라가지 않습니다. 폼·이미지·첨부도 요청하지 않습니다.

## 정규화

조사에서 확인한 `board_detail`, `program-tit`, `program-detail`, `program-content`, `program-cate`를 사용합니다. 제목·원문 분류·라벨 근거와 상세 본문을 별도로 보존합니다. 메뉴·폼·스크립트·챗봇은 본문에 섞지 않습니다. 표의 행/셀·rowspan/colspan과 목록 조건은 비실행 텍스트/객체로 유지합니다.

실제 HTML 전체 fixture는 없으며 모든 시험 HTML은 조사 보고에서 만든 **합성 자료**입니다. 2026-10-02 홈페이지에서 수정된 교육 영역 파서가 고유 상세 8개를 발견했습니다. 후속 상세 대조에서 제목 오염과 상단 라벨 추출 공백을 확인했고, 이번 보완에서는 응급처치·창덕궁 상세 두 응답을 메모리에 유지하여 보완 전후를 비교했습니다. 기념행사 요청은 연결 실패했고 재시도하지 않았습니다. 홈페이지 발견 성공은 전체 목록을 포괄한다는 뜻이 아닙니다.

`myseoul-html-v2-local`은 실제 제목 `program-tit` 안의 `p.txt-26`, 직접 모집 배지 `span.cate-st4`, 별도 `program-cate`를 읽습니다. 관측 구조가 깨졌거나 중복이면 실패하며 제목에서 단어를 일괄 삭제하지 않습니다. 상단은 `program-detail` 안의 `div.pg-det-list > div.item > em + span` 라벨/값을 추출합니다. 관측 metadata 구조가 있으나 잘못됐으면 범용 라벨 파서로 대체하지 않습니다. 알려진 라벨의 값이 없으면 부족값으로 남습니다. 이전 단순 텍스트 제목·dt/dd 형태도 제한적으로 지원합니다.

신청자격·모집 배지·신청/교육일시·신청방법·수강료·정원의 실제 상단 근거를 보존합니다. 본문 `일시`는 원문 운영일시 근거이며, `초급반` 같은 별도 반별 일정이나 `집결시간`과 합치지 않습니다. 오전/오후 + 축약 종료 시각은 현재 기간 파서의 미지원 형식으로 raw를 남기고 확인 대상으로 둡니다. 실제 두 항목에서 상단/본문 시간 차이와 신청방법 차이가 드러났으며, 임의로 한쪽을 채택하지 않았습니다.

`참가비: 3,000원 (입장료)`는 admission으로 읽고, 별도 상단 무료 수강료는 tuition으로 함께 보존합니다. 값에 명시된 단일 재료비도 구분합니다. 같은 비용 항목의 상단/본문 값 차이는 충돌로 남습니다. `신청중`/`신청마감`은 이 source의 상태 표현으로 해석하되 기간·종료·충돌 검사를 우회하지 않습니다.

확인된 모집 상태 동의어(접수중/신청중/모집중)와 같은 비용 항목의 단순 원화 금액·종류 주석은 의미가 같으면 충돌로 만들지 않습니다. 원문 문자열 자체는 모두 유지합니다. 실제 마감/접수중, 3,000원/5,000원 차이는 계속 충돌입니다. 입장료·재료비가 하나의 금액으로 함께 명시된 복합 비용은 extra_fee 근거와 `fee_components_unresolved`로 남기며 금액을 임의 분할하거나 tuition으로 추정하지 않습니다.

기념행사의 만족도 조사 문구가 실제 안내인지 공통 UI인지 이번에는 확인하지 못했으므로 추가 삭제하지 않았습니다. 기존 form 제외는 유지하며, 실제 참여 안내의 해당 단어를 일괄 삭제하지 않습니다. 이미지·첨부 내용은 읽지 않습니다.

원문 게시·수정 시각은 null입니다. 라벨로 확인되는 대상·거주·연령·동반·언어·장소·진행 방식·신청 주체·신청 방법·비용 구성·두 기간·회차/요일/시간·집결·접수 상태·조기 마감 근거를 보존합니다. 무료 수강료와 재료비/입장료는 다른 구성으로 읽으며 모든 비용을 무료로 바꾸지 않습니다. 정원 0명은 의미가 불명확하므로 raw만 남깁니다.

의미 revision은 프로그램 제목·분류·설명·조건·라벨·표·신청 링크를 사용합니다. 페이지 위치·조회수·관측 시각·번역 위젯은 제외합니다. parser 버전은 hash 밖의 참조입니다. 이번 제목/상단/비용 해석 변경으로 revision 계약도 `myseoul-semantic-v2`로 변경했습니다. 같은 HTML의 hash 차이는 파서 변경 때문일 수 있으며 운영기관의 실제 원문 변경으로 단정하지 않습니다. 로컬 판정은 현재 parser 버전만 소비하며 이전 정규화 자료의 조용한 혼합은 하지 않습니다. 운영 DB 자료 재판정은 이번 범위가 아닙니다.

연락처(전화/이메일)는 텍스트에서 생략하며 키·토큰처럼 보이는 신청 URL은 보존하지 않습니다. 원문 HTML·회원정보·응답 전체를 저장하지 않습니다.

## 로컬 판정

`assess_myseoul(record, now=시간대있는시각)`의 결과는 관측, 서비스 범위, 현재 신청 가능, 사실 충분성/충돌, 공개 카테고리의 다섯 축으로 나뉩니다. 결과의 `include/exclude/review`는 **로컬 판단**입니다. 실제 review/job 생성이나 DB facts 저장을 뜻하지 않습니다.

- 이 source의 취업·산업 교육·취업지원도 program 후보입니다. 다른 수집원의 취업 제외 규칙은 유지합니다.
- 문화·생활교육·체험·교류·주민 활동, 유료·가족·어린이를 포함합니다. 가족 분류/우선순위를 만들지 않습니다.
- 명확한 개인 신청 불가 학교·기관 전용 및 내부 운영 대상은 제외합니다. 기관명·협조기관·단체 증빙만으로 제외하지 않습니다.
- 오프라인·혼합은 실제 수도권 개최 근거를 사용합니다. 운영기관 주소를 개최지로 쓰지 않습니다. 온라인은 전국/지역 제한 없음/수도권 포함 대상, 비수도권 거주자 전용은 제외합니다.
- 일반 프로그램 국적 미표기는 확인 사유가 아닙니다. 명시된 국적·체류 조건은 보존하며, 자격 충족을 규칙으로 확정하지 못하면 확인합니다. 일본인 참여 보장은 만들지 않습니다.
- 수업·교육·체험·취업지원은 program, 축제·기념행사·공연은 event입니다. 원문 분류/제목 단어만으로 확정하지 않으며 본문의 목적 근거를 함께 봅니다. 복합·불명은 category 확인 사유입니다.
- 신청기간·운영기간은 별도입니다. 이미 시작된 수업도 추가 모집 가능하며 시작일 경과만으로 제외하지 않습니다. 날짜 단위 종료일은 당일을 포함합니다. 실제 회차·요일·시간/집결과 전체 기간은 별도 근거로 남깁니다.
- 동일 의미의 라벨·범위(운영기간/교육일시, 수강료/참가비 등)의 상단/본문 충돌은 확인 대상으로 남깁니다. 반별 일정/전체 운영범위와 집결/시작을 자동 충돌로 만들지 않습니다. 다중 과정의 온라인/현장 관계는 자동으로 전체 혼합으로 바꾸지 않습니다. 단일 날짜+두 시각 등 현재 작은 기간 파서가 지원하지 않는 형식은 원문을 보존하고 확인 대상으로 남깁니다.
- 이미지에만 있는 설명·핵심 조건은 추정하지 않습니다. 설명·대상·장소/방식·기간·신청 방법·비용의 실제 부족은 확인 사유로 남습니다. 신청 방법+공식 상세가 있으면 별도 폼 URL 부재 자체는 사유가 아닙니다.
- 제외/마감도 관측 record 자체는 유지합니다. `scope=included`, `application=closed`, `decision=exclude`는 현재 새 처리 대상으로 삼지 않는다는 의미이며 외국인 자격 불가가 아닙니다.

## 실행·검증 경계

가짜 transport를 넣은 `HttpClient`로 `MySeoulProgramConnector`를 직접 생성하여 `fetch_batch(None)`을 호출합니다. 운영 CLI·source identity DB registry에는 등록하지 않았습니다. 관측에는 jobs/gate facts가 없고 disposition은 `observe_only`입니다. SQL의 기존 v1/서울 profile로 보내면 안 됩니다.

시험: `scripts` 폴더에서 `python -X utf8 -m unittest test_myseoul_program`.

사용자는 현재 비영리 정기 수집·요약·번역·공개에 대한 기관 구두 허가를 받았다고 확인했습니다. 이는 사용자 확인이며 에이전트가 허가 내용/기관을 직접 확인한 결과가 아닙니다. 같은 허가를 다시 요청하지 않습니다. 광고 등 영리 전환 전 적용 범위 재확인은 후속 조건입니다.

## 다음 연결 전 조건

1. 별도 승인된 소량 공개 읽기로 실제 DOM/라벨 parity를 대조합니다. 실패·미지원 값은 추정하지 않습니다.
2. 기존 저장 계약과 새 source/profile을 검토하고, 비용 구성·과정/집결/회차·분류/부족/충돌의 최소 facts/관리자 입력 표현을 결정합니다. 기존 capital_v1 또는 서울 API의 문화체험 전용 guard로 우회하지 않습니다.
3. 승인된 최소 SQL/DTO/adapter를 격리 DB에서 관측·revision·facts·review·재평가로 검증합니다. 실제 운영 저장·AI·후보·게시·정기 연결은 별도 승인 단계입니다.

## 로컬 저장·관리자 서버 계약

`20261002000300_myseoul_program_contract.sql`은 기존 관측/run/lease/jobs/facts/관리자 이력을 재사용합니다. My identity는 `cntr_no:prgrm_no`, registry 종류는 `content`, connector type은 `public_homepage_partial`입니다. 새 source 기본값은 disabled/testing_only이며 기본 runner·예약에는 등록하지 않습니다.

facts schema `myseoul-program-facts-v1-local`, profile `myseoul-program-v1-local`을 기존 facts 테이블의 추가 허용 쌍으로 사용합니다. 기존 서울 default·함수·판정과 온통청년 동작은 유지합니다. parser `myseoul-html-v2-local`과 revision 계약 `myseoul-semantic-v2`는 별도 참조입니다. 다른 계약의 동일 revision을 조용히 재해석하지 않습니다.

`scripts/ingest/myseoul_db.py`는 명시적으로 주입받은 RPC를 통해 `observe_myseoul_program`과 `finish_myseoul_run`을 호출합니다. 기존 run lease와 checkpoint의 원자 저장을 재사용하며, coverage 집계는 nullable `ingest_runs.run_summary`에만 기록합니다. `homepage_education_only` / `source_complete=false`를 유지하고 부분 발견으로 bootstrap을 완료시키지 않습니다.

`source_snapshot`과 `observed_facts`는 revision별 최초 관측입니다. 운영자는 현재 `facts`만 보완하며 같은 revision의 재관측은 보완값을 덮어쓰지 않습니다. 비용은 항목별 raw 근거를 보존하고 총액·미확인 금액을 생성하지 않습니다. 기간은 신청/운영별 원문·endpoints·day/minute 정밀도를 보존합니다. 원문의 초가 제공되지 않은 minute 직렬화 `:00`은 second 정밀도가 아닙니다.

SQL/Python은 현재 structured facts의 범위·신청 상태·사실 충분성·공개 카테고리를 별도 평가합니다. 일정·상태 충돌이 남으면 신청 상태는 unknown입니다. 같은 비용 항목·전체 기간의 현재 근거에 모순이 남아 있으면 외형 변경만으로 issue를 해소하지 못합니다. 무료 수강료와 유료 입장료는 공존합니다.

`admin_myseoul_program_detail/save/exclude`와 `app/lib/review/myseoul-*`는 전용 보호된 입력 계약입니다. API는 `/api/admin/myseoul-review/[id]`이며 기존 관리자 권한·Origin·서버 actor·200KB·no-store를 유지합니다. 원문/최초 추출과 현재 facts를 구별하고 field별 issues, editableFields와 한국어 guidance를 제공합니다. unsupported reason은 읽기 전용입니다. resolve는 SQL이 관련 사실 변경과 근거 메모를 검증하는 요청입니다. revision/version·열린 queued review·active claim을 검사하고 facts/버전/이력/재평가를 같은 transaction으로 처리합니다.

공통 사람 review 목록은 그대로 사용합니다. 목록 병합이나 새 workflow 단계는 추가하지 않습니다. **입력 UI는 로컬에 연결했습니다.** `ReviewWorkspace`가 My 항목을 `MySeoulReviewPanel`의 전용 API로 분기하며 사유별 입력·수정 저장·제외·현재/최초 facts 비교를 제공합니다. 기존 11필드 상세/저장/제외 경로는 My에 한해 PT409로 거부합니다. 기존 서울의 전용 DTO/RPC 의미는 유지합니다. 브라우저에는 알려진 비실행 텍스트와 제한된 구조만 투영합니다.

**My AI 소비 경로는 로컬에 연결했습니다.** 새 AI migration 적용 후 현재 facts가 통과하고 source enabled/승인 permission 및 열린 review 차단 조건을 충족하면 전용 ai_enrichment 대기를 생성합니다. source의 기본 disabled/testing_only 상태와 정기 workflow는 유지합니다. 일반 worker는 My를 획득하지 않으며 사실 저장만으로 provider를 호출하지 않습니다.

로컬 합성 검사: `python -X utf8 -m unittest test_myseoul_db` (scripts에서 실행), `node scripts/test_myseoul_review.mjs`, `node scripts/test_myseoul_sql.mjs`. JS 시험은 `MACHIMOA_TEST_PYTHON`, SQL 메모리 시험은 기존 `MACHIMOA_PGLITE_MODULE` 경로만 명시적으로 사용하며 환경파일을 읽지 않습니다. 실제 PostgreSQL은 `--postgres --docker <CLI 경로> --container <검증된 시험명>`으로 이미 실행 중인 로컬 network-none 컨테이너만 허용합니다. 기존 volume/bind/포트가 있으면 거부하고 새 고유 시험 DB만 생성하며 기존 DB를 초기화하지 않습니다. 동일 합성 SQL 검증과 직접 RPC 왕복이며 실제 Supabase/PostgREST/계정·운영 검증은 아닙니다.

rollback은 My source 비활성화·queued/failed 중단·새 wrapper 제거 후 원문/facts/이력을 보존합니다. active run/claim이 있으면 차단합니다. My 행을 수용하는 CHECK·registry·run summary와 기존 RPC의 My 오호출 guard는 남습니다. 기존 CREATE migration의 단순 재실행은 지원하지 않으며, 복구는 실제 상태를 확인한 별도 forward migration이 필요합니다.

생활안내·이미지/OCR/첨부·전체 목록 탐색·실제 AI 호출·운영 적용은 이 연결에 포함하지 않습니다. 실제 격리 PostgreSQL 실행 여부와 검증 수치는 해당 submitted 작업 보고의 결과를 기준으로 확인하세요.

UI 최소 확인은 `node scripts/test_myseoul_ui.mjs`의 새 분기·patch·기간·비용 검사와 가짜 인증/RPC를 사용한 로컬 브라우저 확인으로 구분합니다. 저장 실패·version 충돌 때 입력을 보존하고, 최신 값 불러오기는 명시적으로 입력을 버리는 동작입니다. 편집한 여러 줄 값의 빈 줄만 저장 전에 정리하며 최초 원문과 저장 facts는 바꾸지 않습니다. `--serve`는 127.0.0.1:54331의 명시적인 합성 RPC 시험 서버이며 실제 DB/SQL 평가기가 아닙니다. 운영 실패를 시험 서버로 자동 대체하지 않습니다. 로컬 UI 확인·운영 배포·실제 관리자 계정 확인은 서로 다른 범위입니다.


## My AI 입력·후보 연결 (로컬)

`scripts/ingest/myseoul_ai.py`는 현재 revision의 운영자 facts와 facts_version을 사용하며 최초 추출과 달라진 필드만 provenance로 표시합니다. 기존 추출 conflicts/missing는 현재 미해결 사실처럼 AI에 다시 전달하지 않습니다. My 전용 프롬프트는 program/event, 취업·산업 포함, 항목별 비용과 day/minute 기간을 처리합니다. 서울 프롬프트·판정은 유지합니다.

서울의 작은 구역 처리·일정 핵심 값 검사와 공통 명시 target transport를 재사용합니다. My의 session_evidence와 meeting_evidence를 한국어 상세에 조립한 다음 전체를 일본어로 번역합니다. 집결과 진행 일정, 수강료와 입장료·재료비·기타 비용을 분리하며 총액이나 누락된 사실을 생성하지 않습니다. 자동 검사는 숫자·요일·시각 등의 누락을 일부 탐지하며 번역 의미·참여 자격의 정확성을 보장하지 않습니다. 실제 provider 품질은 이번 합성 검증 대상이 아닙니다.

`20261002000400_myseoul_program_ai.sql`은 기존 program_candidate_inputs를 두 schema/profile 쌍으로 확장하고 My 전용 claim/finish/fail public RPC 3개를 service_role에만 허용합니다. 기존 private 권한과 다른 source registry 상태는 유지합니다. 현재 source revision·facts version·명시 target·현재 판정/신청 상태·열린 review·permission을 claim/완료 시 재확인합니다. claimed_at/lease_until/worker가 함께 획득 시도를 식별합니다. 같은 worker 재획득의 과거 완료/실패 응답은 차단합니다. 만료 claim은 gate가 닫혀도 전용 claim 호출에서 정리할 수 있으며 강제 삭제는 하지 않습니다.

현재 정상 queued/failed 작업의 retry_count/next_retry_at은 재관측·refresh에서 보존합니다. 기존 retry 정책을 재사용하며 CLI는 자동 재실행하지 않습니다. `scripts/run_myseoul_program_ai.py`는 source item UUID/revision/project-ref를 필수로 요구하고 기본 validation-only(네트워크 0회)입니다. `--execute`는 별도 실제 실행 승인이 필요합니다. 기존 $0.10, KO/JA 두 생성 호출 상한과 SDK retry 0은 유지합니다.

후보는 기존 한일 6필드 pending으로 저장합니다. program은 신청 끝 날짜를 fixed 마감일로 투영하며, 신청 기간이 없고 현재 모집 근거만 있으면 기존 none 값을 사용합니다. event는 운영 시작/끝 날짜를 event 기간에 투영합니다. 상대 날짜를 추정하지 않습니다. 후보 날짜 투영과 원래 기간/정밀도는 다르며 두 기간 원본·비용 구성·revision/schema/profile/facts_version/job/claim 이력은 program_candidate_inputs.input_facts에 보존합니다. raw_payload는 작은 schema/profile/version/원문·공개 분류 metadata만 포함합니다. 후보·입력 참조·job 완료는 한 transaction입니다.

기존 후보 목록/6필드 수정/반려를 재사용합니다. 같은 revision에서 facts version이 달라지면 inputChanged/canPublish=false가 표시되고 게시는 차단됩니다. 원문 revision 자체가 바뀐 후보는 기존 공통 상세/관리자 lock의 PT409 제한을 유지합니다. 이런 후보의 상세 조회·수정·반려 및 재생성 계약은 후속 과제이며 자동으로 해결하지 않습니다. My 게시 guard는 공통 관리자 경로와 private 게시 함수의 My 분기에 적용되어 오래된 facts/lease 결과·권한·마감·제외를 우회하지 못합니다.

AI rollback은 source 비활성화·queued/failed 취소와 신규 실행 wrapper 제거까지 수행하며 claim이 있으면 중단합니다. 원문/facts/후보/입력 이력과 My 읽기·게시 guard 및 schema CHECK는 보존합니다. 이전 CREATE migration의 단순 재실행이나 DB 저장 계약 rollback의 일괄 실행은 복구 수단이 아닙니다. 복구/전체 제거는 남은 참조를 확인한 별도 forward migration이 필요합니다.

새 검사: `scripts/test_myseoul_ai.py`, `scripts/test_myseoul_candidate.mjs`, `scripts/test_myseoul_ai_sql.mjs`(명시적 격리 PostgreSQL 필수). 기존 104개 저장 검사는 반복하지 않습니다. 실제 Supabase/PostgREST·Production schema·실제 콘텐츠/provider·게시 성공은 미검증입니다. main의 관리자 AI 대기·휴지통·안내 계약을 로컬에 통합했습니다. main migration 20261002000000/00100/00200 다음에 미적용 My 저장 20261002000300, My AI 20261002000400 순서로 정리했습니다. 운영 migration 이력은 조회하거나 변경하지 않았으며 적용 전 기존 번호의 My 계약이 실제 미적용인지 확인해야 합니다. My AI 대기 목록은 현재 facts 버전으로 입력 변경을 판단합니다. My의 자체 제외 API는 유지하되 기존 휴지통 제외/복구 경로로 보내지 않으며 My 휴지통 연결은 미구현입니다. 원문 revision 변경 후보의 상세 조회 제한도 그대로 유지합니다.


## 원문 변경 확인·제한 수집 후속 계약 (로컬, 2026-10-03)

`20261003000001_myseoul_change_collection.sql`은 위의 원문 revision 변경 후보 상세 제한을 **My 경로에서만** 해소합니다. 기존 source의 snapshot/version과 권한은 유지합니다. 최초 추출과 생성 당시 `program_candidate_inputs`는 바꾸지 않습니다. 새 원문은 운영자 보완값을 필드별로 대조해 승계하고 관련 값이 바뀌면 `source_change_conflict`로 확인을 요청합니다. 신청/운영 충돌은 별도 사유입니다. 이미 미해결인 변경 충돌은 다음의 무관한 수정으로 사라지지 않습니다. parser/revision 계약이 다르면 조용히 재해석하지 않고 저장을 거부합니다. 수동 제외는 과거 revision으로 돌아와도 유지합니다.

기존 후보가 어느 revision에든 있으면 새 AI 대기/claim을 자동 생성하지 않습니다. 유효한 실행 중 claim은 보존하고 현재 revision/facts/lease fence로 과거 결과를 차단합니다. 만료된 claim은 다음 refresh에서 cancelled로 정리하며 만료 행 자체가 사람의 사실 수정·변경 확인을 막지 않습니다. provider는 수집/재평가/변경 확인에서 호출하지 않습니다.

관리자 후보 상세의 ‘생성 이후 원문이 변경됨’에서 최신 원문, 변경된 사실 항목, 신청·운영 기간을 대조합니다. `admin_myseoul_review_change`는 ‘내용 영향 없음’ 또는 한일 6필드 수정과 판단 근거를 원자 저장합니다. `myseoul_change_reviews`에 서버 actor·확인 시각·최신 revision/facts version·현재 내용 hash를 별도로 남깁니다. 다시 원문/facts/내용이 바뀌면 확인은 무효가 됩니다. 변경 확인은 마감·부적격·수동 제외·열린 review·source 권한을 우회하는 승인이 아닙니다.

공개된 My 콘텐츠의 미확인 변경도 기존 후보 목록/상세에서 접근합니다. 실제 공개 6필드와 기간·분류를 대조하며 공개 글은 자동 수정·숨김하지 않습니다. ‘공개 내용 수정·변경 확인’으로 운영자가 명시적으로 수정할 때만 공개 글과 이력을 함께 저장하고 게시 시각/노출 상태는 유지합니다. source 권한이나 현재 판정 때문에 처리가 차단된 경우 근거 확인으로 이를 우회하지 않습니다. 삭제 확정·자동 비공개·AI 재생성·이미지 기능은 추가하지 않았습니다.

당시 제한 수집은 홈페이지 1회＋신규6/재확인2였으며, 아래 신규 발견 규칙으로 대체했습니다. `20261003000001`의 이전 wrapper·cursor는 호환·rollback을 위해 유지하되 새 CLI에서는 호출하지 않습니다. 원문 변경 안전장치는 계속 사용하며 기본 수집이 기존 상세를 재확인하지 않습니다.

새 관련 검사만 `scripts/test_myseoul_collect.py`, `scripts/test_myseoul_changes.mjs`, `scripts/test_myseoul_changes_sql.mjs`로 수행합니다. SQL 시험은 기존 bootstrap 일부를 사용한 합성 PGlite와 확인된 격리 PostgreSQL 모드를 구분합니다. 실제 운영 schema/PostgREST/site/provider 검증과 독립 연결 동시성은 별도입니다.

rollback `20261003000001_myseoul_change_collection_down.sql`은 My 비활성·활성 run/claim 없음·다음 migration의 함수 재정의 없음이 선행 조건입니다. 이전 함수의 정확한 정의/ACL을 보존해 복원하고 신규 wrapper만 제거합니다. 운영자 수정 내용·확인 이력·cursor·restricted backup은 삭제하지 않습니다. 공개 내용까지 되돌리는 rollback이 아니며 forward migration의 단순 재실행은 지원하지 않습니다. 코드/CLI를 맞는 이전 버전으로 먼저 되돌리고 실제 DB 이력을 확인해야 합니다. 이번 계약은 운영 미적용입니다.

## 전체 목록 기반 신규 발견 규칙 (로컬, 2026-10-03)

대상은 `prgmListPage.do`의 전체 프로그램 목록이며 교류·체험도 포함합니다. 최초 전체 수집은 별도 승인 작업입니다. 일반 실행은 첫 페이지 10건의 ID를 모두 비교하고, 정확히 10건 모두 미발견 ID이면 2페이지를 추가합니다. 기존 원문 ID 또는 발견 대기 ID가 하나라도 있으면 다음 페이지를 읽지 않습니다. 페이지가 불완전하거나 두 페이지의 total/ID가 바뀌면 정상 종료하지 않습니다. 3건 연속 중복 종료·3페이지 조회·정기 상세 재확인은 없습니다. 정렬 보장에 대한 사용자 확인과 별개로 이번 공개 코드·두 관측에서는 공식적인 안정적 정렬 보장을 확인하지 못했습니다. reader는 정렬을 untrusted로 유지합니다.

**공개 목록 reader를 로컬로 연결했습니다.** `scripts/ingest/myseoul_list.py`가 확인된 공개 POST 응답을 내부 `ListPage`로 변환하며 `collect_myseoul`의 기본 reader로 사용됩니다. `ListPage` 자체는 사이트 응답 형식이 아닙니다. 홈페이지 fallback이나 fixture 성공 대체가 없고, 정적 목록 문서에 항목이 없다는 사실을 빈 목록으로 처리하지 않습니다.

2026-10-03 07:56:13~07:57:51 UTC(16:56:13~16:57:51 KST)에 직접 HTTP 5회로 목록 문서 1회, 직접 연결된 관련 script 2개, 공개 목록 데이터 2회를 읽었습니다. 모두 HTTP 200이며 쿠키·로그인·인증값 없이 재현했습니다. 계약 확인을 위한 둘째 페이지 읽기는 이번 조사 승인에 따른 것이며 일반 실행의 조건을 바꾸지 않습니다. 상세·신청처·이미지·첨부는 요청하지 않았습니다. 같은 응답을 메모리에서 reader로 대조하고 전체 HTML fixture를 저장하지 않았습니다.

확인한 공개 계약:
- 문서: `https://global.seoul.go.kr/hmpg/ecpr/prgm/prgmListPage.do`
- 직접 연결 코드: `/js/hmpg/ecpr/prgm/PrgmListPage.js?version=202609022_02`, `/js/comUtil.js?versoin=202609022_02`. 공개 목록 함수와 HTML 전송 함수가 아래 POST를 구성합니다. 초기 문서의 CSRF meta는 없었으며 매 실행의 문서·script·쿠키 준비 요청이 필요하지 않았습니다.
- 데이터: `POST https://global.seoul.go.kr/hmpg/ecpr/prgm/prgmListPgng.do`, URL-encoded form, `miv_pageNo=1|2`, `miv_pageSize=10`. `prgrm_se_cd`, `cntr_no`, `prgrm_nm`, `rcpt_stadt`, `rcpt_enddt`, `aply_mthd_cds`, `free_yn_cds`는 기본값 빈 문자열입니다. 정렬 파라미터는 확인되지 않았습니다.
- 응답: UTF-8 HTML fragment. 전체 건수는 `totalCnt`를 설정하는 script, 항목은 `div.counseling-list`의 직접 `a.item`, ID는 `goPrgmDetail(prgrm_no, cntr_no)`, 접수 라벨은 `span.program-state`, 현재 페이지는 PC·모바일 paging의 `aria-current=page`로 확인합니다. 공식 상세 URL은 공개 코드의 이동 방식으로 구성하고 기존 `detail_identity`로 검증합니다.
- 같은 응답 대조: 두 페이지 모두 total=62, 각 10개 고유 ID, 페이지 사이 중복 없음. 첫 페이지 명확한 마감 0건, 둘째 페이지 4건. 이는 당시 첫 두 페이지만 관측한 결과이며 최신순·전체 목록 확보를 뜻하지 않습니다.

reader는 요청 페이지·size=10·total에 맞는 항목 수·현재 페이지·ID/공식 링크·중복·상태 요소를 검증합니다. HTTP 오류·redirect·잘못된 MIME/UTF-8·크기 초과·불완전 HTML·템플릿 변경은 실패입니다. 자동 재시도나 오류를 빈 목록으로 바꾸는 동작은 없습니다. 정상 빈 페이지·오류/차단 응답은 합성 시험으로만 확인했으며 실제 사이트의 해당 응답은 관측하지 않았습니다. 공개 구조가 바뀌면 계약을 다시 확인해야 합니다.

상세는 이전 실행의 미처리 ID를 먼저 최대 10건 선택합니다. 한도 초과 항목은 목록에서 사라져도 이월됩니다. 실패 요청도 한도에 포함하고 같은 실행에서는 재시도하지 않습니다. 다음 명시적 실행에서는 미처리로 다시 선택될 수 있으며 마지막 시도 시각으로 이전 미처리 안의 순서를 순환합니다. 목록의 정확한 신청종료/신청마감/접수종료/접수마감/모집종료/예약마감 라벨만 신규 상세 대상으로 건너뛰고, 그 외 상태는 unknown으로 보존합니다. 이미 관측된 ID는 기본 상세 대상에 다시 넣지 않습니다.

후속 `20261003000100_myseoul_list_discovery.sql`은 발견 대기와 실행 집계의 제한된 두 테이블 및 service_role 전용 wrapper 4개를 추가합니다. 기존 source registry/권한/함수/원문/facts/job 의미는 수정하지 않습니다. 발견 기록은 ID·검증된 공식 링크·서버 발견/시도 시각·상태만 보존하며 원문 관측 성공과 다릅니다. 상세 성공은 기존 `observe_myseoul_program`을 사용하고 운영자 facts를 보호합니다. 응답 불명 이후 다음 실행에서는 실제 source_items 존재를 대조해 중복 상세 요청을 막습니다. source 권한이 준비되면 기존 저장 계약에 따라 AI 대기 기록이 생길 수 있지만 수집에서 claim/provider/후보 생성을 실행하지 않습니다.

확인된 reader는 목록당 공개 POST 1회만 수행하므로 목록 최대2＋상세 최대10＝HTTP 최대12입니다. 향후 추가 준비 요청이 필요해지면 별도 예산·승인이 필요하며 숨겨진 호출로 한도를 늘리지 않습니다. 집계는 `coverage=program_list_first_two_pages`, `source_complete=false`, bootstrap 미완료와 페이지수/신규/기존/마감 제외/선택/이월 선택/처리/실패/미처리 잔여/종료 사유를 구분합니다. complete는 선택한 부분 범위와 상세 처리만 뜻하며 전체 수집 완료가 아닙니다. 첫 페이지에 기존 ID가 섞여 있는데 뒷페이지에 미발견 ID가 있는 경우, 2페이지 이후 신규, 최초 확보 이전 자료는 누락될 수 있습니다.

CLI 기본 validation-only는 `details_max=10`, `list_pages_max=2`, `recheck_slots=0`, `public_list_reader_ready=true`를 표시하며 HTTP/DB 접근은 0회입니다. 명시적 `--execute`에서만 `SUPABASE_URL`과 지정 project-ref의 일치 및 `SUPABASE_SERVICE_KEY`를 검사한 뒤 기존 저장 adapter를 사용합니다. 환경파일을 읽거나 수정하지 않습니다. 이번 작업에서는 실제 `--execute` 수집·DB 접근을 하지 않았습니다. 하루1회/정기 workflow·최초 bootstrap·정보 수정 요청 UI는 연결하지 않습니다.

새 reader 관련 검사는 `scripts/test_myseoul_list.py`와 변경한 `test_myseoul_collect.py`의 관련 항목이며 최소 구조를 재현한 합성 HTML/가짜 전송·RPC를 사용합니다. reader 연결·CLI 무접근/명시 실행 분기·전송 제한 등 14개와 Python 구문 검사를 통과했습니다. 중요한 reader 변경분의 독립 검토 1회에서 수정이 필요한 지적은 없었습니다. Python lint 도구 ruff는 설치되어 있지 않아 실행하지 않았습니다. 기존 SQL 44개/49개와 전체 시험은 반복하지 않았습니다. 실제 목록 두 페이지 대조와 별개로 실제 상세/DB 저장·Production/PostgREST·독립 PostgreSQL 동시성은 이번에 검증하지 않았습니다. 새 rollback은 먼저 CLI를 중지하고 source 비활성·활성 run 없음 아래 신규 wrapper만 제거하며 발견·실행 이력/원문/facts를 보존합니다. 후속 재정의가 있으면 실행 전 별도 계약 대조가 필요합니다. 테이블이 남으므로 CREATE migration의 단순 재실행은 지원하지 않으며 선행 rollback보다 이 후속 rollback을 먼저 검토해야 합니다.

## 수집원 이미지 URL (로컬 연결, 2026-10-03)

이미지 파일을 내려받거나 DB/Storage에 저장하지 않습니다. 이미 읽은 한국어 상세의 `program-content` 안에서 포스터 표기가 있는 고유 이미지 또는 유일한 본문 이미지만 선택합니다. 여러 후보의 대표성을 구분하지 못하면 이미지 없음입니다. 로고·아이콘·배너·추적·숨김 이미지를 제외하고 상대 src는 공식 상세 URL을 기준으로 해석한 뒤 기존 `source_images.source_image_url`로 검증합니다. 별도 HTTP 요청·이미지 프록시·OCR은 없습니다.

검증한 값은 해당 `cntr_no:prgrm_no` 관측의 `normalized_payload.source_image_url`에 저장하며 선택 사유와 `source_image_contract=myseoul-body-image-v1`을 별도 참조로 남깁니다. 이미지 없음/거부는 수집 실패가 아닙니다. 유효 URL은 의미 있는 hash에 포함하고 추가·변경·제거는 revision 변경입니다. 이미지가 없으면 이전 semantic-v2 hash와 같습니다. parser/revision 계약은 유지하며 **최초 이미지 추출 기능 도입에 따른 새 관측을 기관의 실제 이미지 수정이라고 단정하지 않습니다**. 이미지 URL은 facts 필드가 아니고 AI 입력으로 사용하지 않습니다. 기존 운영자 보완 승계·후보 존재 시 자동 AI 대기 방지·사람 변경 확인·claim fence를 유지합니다. URL이 같은 이미지 파일의 내용 변경은 다운로드 없이 감지할 수 없습니다.

원격 main `bc5b99d08fed24302788cb4934261557767810d7`의 기존 이미지 validator·공개 DTO·목록/hover/상세/확대 컴포넌트를 재사용합니다. 최신 fetch 당시 이후 main 변경은 없습니다. 무관한 로그인·저장 기능은 통합하지 않습니다. Production에 이미 적용된 `20261003000000_source_images.sql`은 원격 파일 그대로 보존합니다. 이 번호와 겹친 **운영 미적용** My 원문 변경 migration/rollback만 `20261003000001_myseoul_change_collection.sql`과 `20261003000001_myseoul_change_collection_down.sql`로 이동하고 시험·문서 참조를 갱신했습니다. 적용된 SQL 이력을 바꾸는 작업이 아닙니다.

추가 `20261003000200_myseoul_source_images.sql`은 기존 projection 함수의 allowlist에 `myseoul_program`만 추가합니다. 실제 registry의 `legacy_curation_source=myseoul_program`과 external_key 및 후보 생성 당시 revision이 모두 맞아야 `public.curations.source_image_url`로 전달합니다. 오래된 revision에서 사람 변경 확인으로 게시 가능해도 당시 입력 참조를 바꾸거나 최신 이미지를 끌어오지 않으며 이미지는 null입니다. 새 My 전용 trigger는 이미 공개된 후보의 명시적 내용/기간 수정·변경 확인 시 기존 projection을 같은 transaction에서 실행합니다. 이미지 없음·거부·revision 불일치는 이전 URL을 지우며, 재관측만으로 공개 글이나 이미지를 자동 수정하지 않습니다. 기존 공유 게시/AI 함수·청년센터/서울 trigger·ACL은 변경하지 않습니다.

운영 적용 전 실제 migration 이력·함수 정의 대조가 필요합니다. 준비 순서는 My 00300/00400 → 기존 적용 image 00000 확인(재적용 금지) → 미적용 My change 00001 → list 00100 → My image 00200입니다. image 00200은 이전 projection의 정확한 본문(줄바꿈 차이는 제외)을 확인한 후 적용합니다. 새로운 함수 변경이 있으면 덮어쓰지 않고 차단합니다. rollback은 My 추가 trigger를 제거하고 이전 projection만 복원하며 원문·facts·후보·URL·공개 데이터는 지우지 않습니다. 공개 내용/이미지까지 되돌리는 복구가 아니고 후속 함수 변경이 있으면 차단합니다. 기존 My rollback은 후속 계약을 먼저 되돌릴 필요가 있습니다.

관련 좁은 시험은 `test_myseoul_source_images.py`, `test_myseoul_source_images_sql.mjs`, `test_myseoul_source_images_ui.mjs`입니다. 합성 HTML·합성 provider 출력·새 메모리 PGlite·UI state 대역이며 실제 HTML의 이미지 대표성, 독립 PostgreSQL, Production/PostgREST, 실제 이미지 응답·권리·공개 표시 성공은 검증하지 않았습니다. 공개 표시에는 이 후속 migration/관련 코드 적용, 유효 URL을 가진 현재 revision의 후보에 대한 별도 승인·게시, 원본 서버의 브라우저 이미지 제공이 필요합니다. 본문 실패/이미지 실패는 기존 대체 UI를 사용합니다. 공개 목록 reader 연결에서도 이 이미지 구현을 보존하며 이미지 때문에 추가 요청하지 않습니다.
