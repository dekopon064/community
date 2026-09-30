# 운영자 검토 관리 — 로컬 구현과 DB 연결 기반

2026-09-30. 작업 기준 main: `c6cb7b0b39f80291527b6cea9fc2f625acdc0e19`.
사용자가 실제 Google 로그인·로그아웃 및 운영자 허용·일반 계정 차단을 확인했습니다.
에이전트의 이번 review 검증은 가짜 인증과 로컬 테스트 대역으로 수행합니다.

## 현재 제공하는 화면

`/ko/admin`의 두 검토 단계는 한국어 관리 UI이며 공개 한·일 화면의 디자인 토큰을 상속합니다.
데스크톱은 목록과 상세를 나란히, 모바일은 목록 다음 상세를 표시합니다.
원문·확인 사유 → 사실 입력 또는 후보 편집 → 저장/최종 처리 → 결과·이력 순서입니다.

- 사람 사실 review: 원문과 출처, 내부 코드의 한국어 설명, 정보 성격·공개 카테고리·대상 지역/근거·외국인 신청 자격·진행 방식·신청 마감 또는 개최 기간 입력, 제외 사유.
- AI 후보: 한국어·일본어 제목/요약/상세, 비공개 수정 저장, 저장본 확인 후 승인하고 게시, 사유를 남기는 반려.
- 미저장 내용이 있으면 다른 항목 이동과 최종 처리를 막고 저장/수정 취소를 안내합니다.
- 저장 결과의 남은 사유와 AI 대기 여부, 처리 상태와 작업 계정 UUID·한국 시간·사유 이력을 표시합니다.
- 사실 저장은 실제 AI 실행·재번역을 호출하지 않습니다. DB 모드의 승인하고 게시는 공개 DB 변경을 수행하므로 적용·연결 승인 전에는 실행하지 않습니다.

**실제 DB adapter와 최소 SQL 계약을 로컬에 작성했습니다.** migration은 적용하지 않았고 PostgreSQL 실행 검증도 하지 못했습니다. 서버 모드/키 설정이 없으면 API는 `503 not_connected`로 차단합니다. 사용자 화면 확인은 실제 DB 저장·게시 검증이 아닙니다.
DB 연결 실패를 빈 목록이나 저장 성공으로 바꾸지 않습니다.

## 확인한 기존 계약

최신 main의 누적 migration 정의를 기준으로 확인했습니다. 실제 운영 catalog/ACL은 조회하지 않았습니다.

| 업무 | 기존 수단 | 앱 연결에 필요한 부분 |
| --- | --- | --- |
| 정보 성격 확인 | `resolve_source_item_product_type` | 원문 revision과 열린 review 확인, 기존 확인값의 수정 허용 범위 구분 |
| 대상 지역·외국인 자격 사실 입력·재평가 | `resolve_source_item_gate_facts` | `gate-facts-v1` 필드로 매핑, 현재 상태에서 입력 가능한 사실 검증 |
| 공개 카테고리·행사 기간 | `resolve_source_item_user_category` | 열린 해당 사유 확인. 기존 RPC는 일반 자유 편집 함수가 아님 |
| 정책·프로그램 신청 마감 | `resolve_source_item_application_deadline` | `fixed / none / closed`, 열린 마감 review 및 AI lease 확인 |
| 수동 제외 | `resolve_ingest_review_decision` → 기존 private 처리 | `manual_non_target` 또는 `insufficient_evidence`와 현재 review 종류·규칙 버전을 서버에서 결정. 브라우저가 임의 코드/판정 주체를 정하지 않음 |
| 후보 수정 저장 | 해당 RPC 없음 | 비공개 pending 후보의 여섯 언어 필드만 수정하는 새 wrapper 작성 |
| 반려 | private `reject_curation_candidate(uuid,text,text)` | 일반 JWT/service_role에 실행 권한 없음. expected 원문 revision·후보 버전 추가 검사 필요 |
| 승인하고 게시 | private `publish_curation_candidate(uuid,text,text,bool)` | 별도 approved 상태 없이 published와 reviewer/time/publication lineage를 함께 기록. expected 원문 revision·후보 버전 검사 필요 |
| 관리자 목록·상세 | 앱용 경로 없음 | private 테이블의 제한된 조회/DTO 경로 필요 |

관련 정의:
`20260923000000_ingest_min_review_workflow.sql`, `20260925000000_ingest_manual_non_target.sql`,
`20260928000000_ingest_user_category_period.sql`, `20260928000001_ingest_application_deadline_rpc_conflict.sql`,
`20260827121818_p1_bilingual_curations.sql`, `20260913000001_publish_permission_lineage.sql`.

공개 fact adapter 중 일부는 service_role 전용이지만 서버 로그인 클라이언트는 일반 사용자의 JWT를 사용합니다.
private 반려·게시 함수를 그 클라이언트나 service_role로 바로 호출할 수 있다고 가정하지 않습니다.
기존 게시 함수의 source permission·기간·공개 lineage·덮어쓰기 금지 등 검사를 우회하지 않습니다.

## 이번에 작성한 연결 계약

이번 변경 파일: `app/lib/review/database-config.ts`, `database-store.ts`, `database-dto.ts`, `server.ts`,
`contracts.ts`, `local-fixture.ts`, `handlers.ts`, `validation.ts`, `presentation.ts`,
`app/components/admin/ReviewEditors.tsx`, `ReviewWorkspace.tsx`, `scripts/test_admin_review_database.mjs`,
`scripts/test_admin_review.mjs`, `package.json`, 이 문서, 아래 migration/rollback입니다.
기존 Google 로그인·운영자 권한 코드와 사용자의 환경 파일은 보존했습니다.

사용자는 `requireAdmin()` 다음에만 별도 service role 클라이언트를 사용하는 방향을 승인했습니다.
`supabase/migrations/20260930000000_admin_review_rpc.sql`은 아직 적용하지 않은 로컬 초안입니다.
기존 private 함수 본문·ACL·AI 처리 정책·공개 RLS는 변경하지 않습니다.

- public 관리자 wrapper 7개: `admin_review_list`, `admin_review_detail`, `admin_review_save_facts`,
  `admin_review_exclude`, `admin_review_save_candidate`, `admin_review_publish`, `admin_review_reject`.
  신규 public wrapper만 service_role에 EXECUTE를 부여하고 PUBLIC/anon/authenticated에서는 회수합니다.
  신규 private helper와 이력 테이블/sequence는 service_role에서도 직접 사용할 수 없습니다.
  기존 service_role RPC 권한은 유지합니다. service role 키 자체의 기존 넓은 권한을 줄였다는 뜻은 아닙니다.
- 목록은 열린 현재 revision review 또는 pending/current revision 후보를 25개씩 반환합니다.
  후보는 canonical source + 외부 원문 ID로 source_items에 연결합니다. 관계 없는 옛 후보는 목록에 넣지 않습니다.
  원문은 필요한 title/source_url/plain_text만 투영하고 본문은 200,000자로 제한합니다.
  raw_payload, provider 응답, 전체 normalized_payload, 작업 lease/claimant는 브라우저에 반환하지 않습니다.
- 충돌 version은 source/fact/category/deadline/period/job/decision/candidate/permission 및 마지막 처리 이력의
  내부 snapshot SHA-256입니다. 같은 revision 내 변경도 잡습니다. source → permission → jobs → 기존 advisory key → candidate 순서로 잠근 뒤 다시 검사합니다.
  새로운 원문 revision, 다른 저장, terminal 상태, AI의 활성/비정상 lease는 처리하지 않습니다.
- 사실 저장은 필요한 기존 confirm/category/deadline/gate-facts RPC만 호출합니다.
  source normalized_payload와 revision은 wrapper에서 수정하지 않습니다. 평가 결과의 남은 review reason과 실제 AI job 상태를 반환합니다.
  입력·기존 RPC·이력·결과를 한 transaction에서 처리하며 지원하지 않는 사유가 사라지면 전체 저장을 거절합니다.
- 최초 product type은 legacy product_type_review 및 현재 content_review의 분류 미확정 사유에 한해 confirm합니다.
  확정 type override는 없습니다. gate-facts는 미확정/현재 관련 사유에서만 허용합니다.
  카테고리·행사 기간은 열린 user_category_unconfirmed에, 마감은 열린 application_deadline_unknown에 대응합니다.
  카테고리 저장 후 마감 입력이 새로 열리면 다음 저장에서 보완합니다.
  이미 확정된 카테고리의 행사 기간만 수정하는 일반 계약은 이번에 추가하지 않았습니다.
- 제외는 현재 열린 content/product_type review의 manual_non_target 계약을 재사용합니다.
  legacy 지역/관련성 review만 있는 경우에는 제외 버튼을 제공하지 않습니다.
- 후보 수정은 pending의 한·일 제목/요약/상세 여섯 필드만 변경합니다.
  제목 300자, 요약 1,000자, 상세 200,000자 제한이며 한국어 legacy title/summary/content를 함께 맞춥니다.
  메타데이터, source, slug, AI 값, 확정된 기간은 편집하지 않습니다.
- 반려/게시 wrapper는 source current revision·pending·snapshot을 검사한 뒤 기존 private 함수를 호출합니다.
  게시 overwrite=false 고정, payload에 편집값 없음. 별도 approved 대기 상태 없음.
  기존 공개 저장·candidate reviewer/time/state·publication lineage와 신규 이벤트가 같은 transaction에 있습니다.
  실패는 rollback되고 중복 처리/오래된 저장본은 409로 차단합니다. 통신 실패 후에는 최신 상태를 확인합니다.
- `admin_review_events`는 actor UUID·시각·action·note·changed_fields만 추가합니다.
  기존 review decision과 최종 candidate 기록을 우선 표시하고 반복 편집 등 부족한 기록을 보충합니다.
  전체 콘텐츠 복사본을 감사 테이블에 쌓지 않으며 화면 이력은 최신 100건입니다.

## 서버·환경 경계

`app/lib/review/server.ts`는 server-only 모듈입니다. 요청마다 `requireAdmin()`을 먼저 실행한 후
쿠키/SSR 인증 클라이언트와 독립된 Supabase client를 만듭니다. 세션 저장·자동 갱신을 끄고 no-store/15초 제한을 사용합니다.
작업 주체는 서버가 확인한 UUID만 전달합니다. 브라우저 actor/추가 필드를 거절합니다.
POST의 같은 Origin·JSON·2MiB 제한, 모든 응답 private/no-store, 서비스 워커 관리자 캐시 차단을 유지합니다.
SQL/SDK 상세 오류·토큰·키를 로그나 응답에 출력하지 않습니다. DTO를 서버에서 한 번 더 필요한 필드만 투영합니다.

실제 DB 모드는 `MACHIMOA_REVIEW_MODE=database`일 때만 활성화됩니다. 연결/설정 실패를 fixture나 성공으로 바꾸지 않습니다.
local-fixture는 development + loopback Auth URL + 명시적 local-fixture 설정일 때만 동작하며 production build/start에서는 차단됩니다.
DB 응답과 fixture 응답의 UI 문구도 구분합니다. 테스트 서버가 database 모양의 DTO를 돌려주더라도 실제 DB 검증은 아닙니다.

사용자 `.env.local`은 읽거나 수정하지 않았습니다.
사용자가 직접 입력할 서버 전용 변수 (배포 시 Vercel Production 환경에도 지정):

```dotenv
MACHIMOA_REVIEW_MODE=database
SUPABASE_SERVICE_ROLE_KEY=
```

- 기존 `NEXT_PUBLIC_SUPABASE_URL`은 동일한 인증/데이터 프로젝트 URL이어야 합니다.
- Supabase 프로젝트 Settings → API Keys에서 서버 전용 Secret key 또는 legacy service_role 키를 확인하여 위 빈 위치에 직접 입력합니다.
  publishable/anon 키는 이 변수에 넣지 않습니다. NEXT_PUBLIC_ 이름으로 복사하지 않습니다.
- 기존 `MACHIMOA_ADMIN_USER_IDS`는 유지합니다. 실제 UUID나 키를 코드/예제/Git/채팅에 넣지 않습니다.
- 격리 로컬 DB 시험에서는 별도 로컬 Supabase URL/시험 키를 프로세스 환경에만 지정하세요.
  시험 검증을 Production에 연결된 CLI/DB URL로 실행하지 않습니다.

## 검증 범위

- `npm run test:admin-review`: 기존 fixture의 처리/충돌/중복/실패/권한/입력/no-store 검증.
- `npm run test:admin-review:database`: 실제 SDK를 loopback RPC 응답 대역에 연결해 RPC 이름/인수,
  서버 actor, 세션 쿠키 미전달, no-store, 설정 실패, DTO 비밀 필드 제거, 오류 비노출과 접근 차단 검증.
  SQL 권한/기존 RPC 재사용/rollback 보호는 정적 검사입니다. PostgreSQL 실행 검증이 아닙니다.
- `npm run test:auth`: 기존 가짜 Auth 인증·관리자 판정 검증. 실제 Google OAuth 결과는 사용자의 확인입니다.
- 최초 로컬 구현 단계에서는 pglast 구문 검사만 수행했습니다. 이후 사용자의 Production 적용 지시에 따라
  임시 폴더의 PGlite PostgreSQL 17.5로 실제 SQL 실행 검증을 추가했습니다.
- `npm run test:admin-review:sql`: `MACHIMOA_PGLITE_MODULE`에 별도로 설치한 PGlite의 `dist/index.js` 경로를 지정합니다.
  프로젝트 의존성이나 `.env.local` 변경 없이 관련 canonical migration 21개를 그대로 실행하고 46개 검증을 통과했습니다.
  저장·제외·재평가·AI queued 결과, 여섯 후보 필드와 legacy 일치, 반려·게시·행위자·publication 이력,
  source/동일 revision 충돌·중복 요청·unsupported reason 보존·payload 불변, 실제 role 권한을 검증했습니다.
  공개 저장 및 감사 기록 실패를 주입하여 candidate/public/event 기록의 transaction rollback을 확인했습니다.
  원래 curations CREATE 문이 저장소에 없어 최소 합성 pre-P0 테이블과 합성 baseline만 bootstrap했습니다.
  단일 PGlite 세션의 경쟁 요청 검증은 독립 연결 간 advisory lock 경합이나 전체 원본 DB bootstrap의 증명이 아닙니다.
- 타입, 변경 파일 ESLint, 가짜 로컬 URL/key/Turnstile 값을 사용한 최종 빌드 통과.
  첫 빌드의 Google Fonts 연결 제한과 누락된 시험용 Turnstile action은 빌드 환경을 보완해 해결했습니다.
- Production 빌드를 로컬에서 실행하고 loopback 가짜 인증/RPC DTO로 readonly 필드,
  지원되지 않는 제외 숨김, 두 언어 후보 및 저장본 게시 확인 문구를 확인했습니다. 실제 SQL은 실행하지 않았습니다.
- 독립 검토 1회에서 현재 content_review 분류 입력과 AI 상태 안내의 결함을 발견해 교정했습니다.
  지적된 입력 조건·한국어 사유 설명·상태 문구를 좁게 재검증했습니다.
- 실제 Google 로그인 및 일반 사용자 차단은 사용자의 로컬 확인 결과입니다.
- 실제 review 저장/게시, 수집/AI 실행은 Production 배포 검증에서 실행하지 않습니다.

## Production DB 적용 (2026-09-30)

- 사용자가 DB migration과 웹 배포를 명시적으로 승인했습니다. Vercel Production 서버 환경변수 입력은 사용자가 완료했다고 확인했습니다.
- 최신 main `8ff162a409ef39771c9887d080f50563f2aa4e42`의 공개 원문 링크 변경을 작업 브랜치에 fast-forward로 보존했습니다.
- 공식 Supabase CLI의 dry-run에서 새 migration 한 건만 확인한 후 `20260930000000_admin_review_rpc.sql`만 적용했습니다.
  Vault, seed, 기존 역할과 기존 private 함수 권한은 변경하지 않았습니다.
- 적용 후 migration 기록 `20260930000000`, 신규 public wrapper 7개, service_role 실행 가능 함수 7개,
  anon/authenticated 실행 가능 함수 0개, audit RLS 활성화, admin 이력 0건을 읽기 전용으로 확인했습니다.
  기존 private publish/reject의 service_role 직접 실행은 차단 상태입니다.
- Supabase Site URL과 Production callback 허용 주소 추가는 사용자가 완료했다고 확인했습니다. localhost callback은 유지합니다.
- 웹 Production 주소는 `https://community-app-drab.vercel.app`입니다. 실제 OAuth 복귀와 운영자 목록/상세는 이 주소에서 별도로 확인합니다.
  이번 SQL 실행 테스트는 격리 DB 결과이며 실제 운영 데이터 저장·게시 결과로 해석하지 않습니다.

## 적용 전 검토 순서와 rollback

아래는 적용 전에 사용한 검토 순서입니다. 현재 적용 결과는 위 Production DB 적용 절을 따릅니다.

1. 운영과 분리된 시험 DB를 준비하고 최신 main의 기존 migration을 순서대로 반영합니다.
   실행할 DB가 Production이 아님을 연결 대상/프로세스로 확인한 후 새 migration을 적용합니다.
2. 합성 데이터로 관계/DTO, 입력 가능한 사유별 사실 저장/제외/남은 사유/AI queued 상태를 검사합니다.
   anon/authenticated 신규 RPC 차단, service_role 신규 public wrapper 허용과 private 직접 실행 차단도 실제 role로 확인합니다.
3. 후보 비공개 편집·legacy 일치·반려·게시/publication 이력, 동일 revision의 두 동시 저장·원문 변경·중복 요청,
   강제 게시/이력 실패에서 public/candidate/event/lineage 전체 rollback을 확인합니다.
   원문 payload 불변, unsupported reason 보존, actor UUID와 시각도 실제 SQL로 확인합니다.
4. 사용자가 실제 환경 적용 범위·백업·이력 보존·rollback 계획을 검토한 뒤 별도로 운영 적용을 지시합니다.
   이후에만 해당 환경의 키/모드를 설정하고 실계정·별도 시험 항목으로 확인합니다.

`supabase/rollback/20260930000000_admin_review_rpc_down.sql`은 사용 이력이 없을 때 신규 객체만 제거합니다.
한 건이라도 admin_review_events가 있으면 적용을 거절하여 이력을 보존합니다.
이미 저장한 사실/반려/게시/공개 내용/publication 이력은 되돌리지 않습니다.
실사용 이후 되돌릴 때는 앱의 DB 모드를 먼저 비활성화하고 이력을 보존하는 별도 rollback안을 승인받아야 합니다.
기존 private 함수와 공개/AI 정책은 migration/rollback 모두 수정하지 않습니다.
