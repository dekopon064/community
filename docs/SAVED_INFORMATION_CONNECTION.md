# 사용자 이름·로그인 복귀 후 저장 연결 (Stage 2)

지정 작업 공간의 미커밋 구현이다. Stage 1의 SAVED_INFORMATION.md와 migration은 보존했다. 운영 DB 적용, 실제 Google/Kakao 인증, 병합·배포는 수행하지 않았다. 승인 디자인 적용은 다음 단계다.

## 계정과 이름

각 개인 요청은 새 서버 Auth client의 `getUser()`로 사용자 UUID를 검증한다. 표시 이름은 검증된 user_metadata의 full_name/name/nickname/preferred_username 중 유효한 문자열을 사용한다. 제어문자를 제거하고 최대 128 code point로 제한하며 이메일 및 @ 포함 후보는 표시하지 않는다. 이름이 없으면 한국어 ‘내 계정’, 일본어 ‘マイアカウント’를 표시한다. React 텍스트로 출력한다.

GET /api/auth/session은 private/no-store이며 signed_in/signed_out/expired/unavailable과 displayName, accountId를 반환한다. accountId는 계정 전환 시 UI 초기화용이다. 브라우저가 전송한 소유자나 표시 이름은 API 입력으로 받지 않는다. 저장 소유자는 DB의 auth.uid()이고 기존 관리자 UUID allowlist와 운영자 정책은 변경하지 않았다.

## HTTP 계약

모든 개인 응답과 오류에 private/no-store를 적용한다. 변경 요청은 same-origin POST만 받는다. 사용자 ID, 역할, 이름 등 지정하지 않은 body 필드는 거절한다. UUID는 저장 식별자이며 slug는 공개 상세 복귀 경로 확인에만 사용한다.

| 경로 | 방법·입력 | 결과 |
|---|---|---|
| /api/saved/state | GET id | 본인 saved 여부, 미인증 401 |
| /api/saved/list | GET locale, offset (25개) | 기존 list_saved_information 결과; 실패는 503 |
| /api/saved/save | POST id | 검증된 공개 정책·프로그램을 명시적으로 저장 |
| /api/saved/request | POST id, slug, locale | 로그인 상태이면 저장; 미인증이면 공개/slug/6번역 필드 검증 후 401 + loginUrl |
| /api/saved/remove | POST id | 본인 저장 해제, 반복해도 saved=false |
| /api/saved/continue | POST id, token | 다른 탭에서 이미 로그인한 경우 명시적 계속 행동. pending 의도를 본인에 묶고 상세로 303. 저장 자체는 안 함 |
| /api/saved/resume | POST id, token | ready cookie와 본인·TTL 일치 후 기존 저장 함수로 1회 소비 |
| /api/saved/cancel | POST JSON 또는 locale,next form | 의도 cookie 제거; 로그인 상태면 본인 취소 시점 기록. form은 안전한 앱 페이지로 303 |

일반 헤더 로그인에는 saveIntent를 넣지 않는다. 일반 인증 시작은 남은 cookie를 제거한다. 저장 목적 인증 시작만 서버가 확인한 nonce를 callback에 전달한다.

## 의도와 결과

HttpOnly, SameSite=Lax, Production에서 Secure인 machimoa-save-intent cookie에 nonce, UUID, slug, 언어, 발급 시각, pending/ready 단계와 검증 후 계정 UUID를 보관한다. TTL 15분, 미래 시각 허용 5초다. 이는 인증 자격이나 추가 권한이 아니며 cookie 필드는 모두 입력 검사를 거친다. 인증은 Auth, 소유자·공개 범위는 DB에서 별도로 확인한다. cookie 서명용 새 비밀값이나 환경 파일을 추가하지 않는다.

외부 callback GET은 인증 검증 및 ready cookie 준비만 한다. 페이지 GET은 DB를 변경하지 않는다. 상세 client가 URL nonce를 제거한 뒤 별도 POST를 보낸다. React Strict Mode 초기화 중복도 처리한다. 취소·실패는 cookie를 제거하며 fragment 오류도 POST 취소 처리한다. 늦은 callback/만료는 성공이 아닌 안내로 복귀한다.

신규 migration 20261001000200은 private resume_receipts(소비 기록), resume_fences(계정·게시물 취소 시점), resume_saved_information, cancel_saved_information_resume를 추가한다. 두 테이블은 RLS 활성화 및 직접 접근 차단, 함수는 authenticated만 실행한다. 원문·제목·이름·이메일 snapshot은 저장하지 않는다.

저장/해제/복귀/취소는 계정별 advisory transaction lock으로 직렬화한다. remove_saved_information은 취소 시점을 쓰기 위해 제한된 SECURITY DEFINER로 바꾸되, 고정 search_path와 auth.uid() 본인 WHERE를 유지한다. API 저장/해제 계약은 동일하다. 게시물 공개성 검증과 FOR SHARE 잠금도 유지한다. 새 함수에 전달한 ID가 익명/비공개 내용을 읽게 하지 않는다.

resume는 nonce당 한 번만 소비한다. 이미 소비된 요청은 현재 저장이 해제되었어도 성공을 다시 알리지 않는다. 해제/계정 취소보다 오래된 미소비 요청도 차단한다. SQL 저장 실패는 하위 transaction을 rollback하고 소비 기록은 남겨 자동 재실행을 막는다. 사용자가 ‘다시 시도’를 누르면 새 명시적 save를 수행한다. 응답 유실은 확인 실패로 표시하고 성공이라고 추정하지 않는다.

실제 saved=true/false 응답 이후에만 성공 문구를 표시한다. 체크 아이콘 없이 3초이며 빈 상태에서 성공 문구 공간을 예약하지 않는다. 오류는 자동으로 사라지지 않고 재시도할 수 있다. 로그인 성공과 저장 실패는 별도 문구다.

## 캐시·초기화

서비스워커는 auth/admin/saved GET·POST 및 저장 RPC를 NetworkOnly로 제외한다. 기존 HTML/RSC 및 no-store 캐시 방어도 유지한다. 로그인/저장 목록 및 의도 cookie가 있는 페이지에 private/no-store를 적용한다. 계정 변경, focus/pageshow, 확정된 로그아웃 후 BroadcastChannel로 다른 탭에서도 재검증하고 개인 UI를 초기화한다. 늦은 목록·상태 응답은 요청 버전으로 무시한다. 계정 메뉴는 로그아웃 응답을 확인한 다음 초기화·이동하므로 제출 전에 form이 사라지지 않는다.

Auth 또는 저장 DB 장애 중에는 로그인 상태/목록을 성공으로 추정하지 않는다. 저장 취소 DB가 장애인 경우에도 보안상 로컬 로그아웃을 막지 않는다. cookie는 제거되지만 장애와 이미 진행 중인 다른 요청의 경합은 실제 다중 연결 환경에서 추가 확인해야 한다. 브라우저 BroadcastChannel 미지원 환경은 같은 탭 및 focus/pageshow 재검증을 사용한다.

## 검증 및 다음 준비

- scripts/test_saved_information_sql.mjs: 이전 기반 103개 검증을 유지한다.
- scripts/test_saved_flow.mjs: 새 메모리 PGlite, 합성 계정/게시물, loopback HMAC 가짜 Auth 및 실제 SQL RPC를 연결한다. .env나 외부 DB 연결 문자열을 읽지 않는다. 기존 canonical migration 21개를 동일한 최소 pre-P0 fixture에 적용한다.
- --serve는 127.0.0.1:54339에 로컬 가짜 제공자 선택과 합성 공개 데이터를 제공한다. 실제 제공자를 호출하지 않는다. 실행마다 DB를 새로 만든다. 종료하면 데이터는 사라진다.
- 가짜 인증 흐름·취소/실패·중복·해제 후 오래된 nonce·SQL 실패 rollback·계정 분리·비공개/삭제 masking·조회 실패 구분·캐시 분류·위조 metadata/JWT·비파괴 rollback 검증.
- 로컬 Next 앱 브라우저에서 한국어/일본어, 데스크톱/390px, 라이트/다크, 저장 목적 복귀·해제·3초 안내 소멸·목록·긴 이름·취소/비로그인 복귀·로그아웃·뒤로/앞으로 이동을 확인했다. 전체 승인 디자인은 적용하지 않았다.
- 실제 Google/Kakao, 운영/공유 Supabase, 실제 JWT/PostgREST/schema cache, 독립 DB 연결 경합, 실제 PWA offline 갱신은 미검증이다. 로컬 build의 Google Fonts는 기존 저장 font fixture를 재사용하고 피드백 공개 설정은 무효한 시험 문자열을 process 환경에만 넣었다. 운영 설정 완료로 확대하지 않는다.

별도 운영 적용 전에 실제 schema/default grants/migration history와 두 migration의 순서, getUser 비용/실제 provider metadata, 인증 callback URL 및 RPC schema cache를 확인해야 한다. 기존 서비스의 비밀값을 사용자에게 대화로 요청하지 않는다. 사용자는 지금 새 키를 준비할 필요가 없다.

Rollback은 Stage 2 down을 먼저 적용한 뒤 필요한 경우 Stage 1 down을 적용한다. Stage 2 down은 기존 save/remove 정의를 복원하고 새 endpoint 함수를 제거하며 테이블·데이터·소비 기록은 남긴다. 재활성화는 별도 forward migration으로 준비한다. 소비/취소 기록 보관·정리 정책은 이후 운영 규모를 확인한 뒤 정하며 이번에는 삭제 작업이나 cron을 만들지 않았다.

다음 복귀 지점: **승인 디자인 적용**. 전체 헤더·로그인·저장 목록 디자인 및 공식 제공자 버튼 보완은 이 구현 이후 별도 승인 범위로 적용한다. 저장 혜택 문구의 공개는 실제 저장 기능과 함께 한다.
