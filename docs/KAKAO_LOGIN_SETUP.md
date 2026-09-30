# 카카오 로그인 설정과 적용

2026-10-01 작업 범위: 기존 Google/Supabase SSR 인증에 카카오를 추가합니다.
같은 `/api/auth/start`, `/api/auth/callback`, 쿠키 세션·검증·복귀·로그아웃을 사용합니다.
LINE은 연결 방식 조사만 했고 구현하지 않았습니다. 네이버는 보류입니다.

## 설정 순서

1. [Kakao Developers](https://developers.kakao.com/)의 앱에서 마치모아 앱을 생성/선택합니다.
   서비스 이름·아이콘·웹 도메인 `https://community-app-drab.vercel.app`을 실제 서비스 정보로 등록합니다.
   카카오 로그인 → 사용 설정의 상태를 ON으로 저장합니다.
2. 기존 Supabase 프로젝트 → Authentication → Sign In / Providers → Kakao의 Callback URL을 복사합니다.
   `https://<project-ref>.supabase.co/auth/v1/callback` 형태이며 카카오에 등록할 주소입니다.
   카카오 앱 → 앱 → 플랫폼 키 → REST API 키 편집의 카카오 로그인 Redirect URI에 등록합니다.
3. REST API 키를 Supabase Kakao의 Client ID로, 활성화된 Client Secret을 Secret으로 입력합니다.
   Supabase Kakao를 활성화하고 저장합니다. 키는 설정 화면에만 보관하고 앱의 공개 변수·코드·Git·채팅에 넣지 않습니다.
4. 카카오 로그인 → 동의항목에서 닉네임·프로필 사진 항목을 설정합니다.
   이메일은 앱 기능상 필수가 아닙니다. 이메일을 요청하지 않으면 Supabase Kakao의
   **Allow users without an email**을 켭니다. 이메일 동의 권한이 없는 일반 앱에 이를 필수로 요구하지 않습니다.
   친구·메시지·성별·생일·전화번호 권한은 추가하지 않습니다.
5. 기존 Supabase URL Configuration의 Production Site URL과
   `https://community-app-drab.vercel.app/api/auth/callback**`, 로컬 callback 허용 주소를 유지합니다.
   Google과 카카오가 같은 앱 callback을 사용하므로 새 앱 callback 경로는 필요하지 않습니다.
6. Vercel → community-app → Settings → Environment Variables → Production에
   `MACHIMOA_KAKAO_LOGIN_ENABLED=true`를 저장합니다. 검증된 새 코드 배포 후 버튼이 나타납니다.
   값이 없거나 정확히 `true`가 아니면 버튼을 숨기고 서버의 카카오 시작도 차단합니다.
   이 변수는 기능 활성화 설정이며 Supabase provider 구성 완료를 자동으로 증명하지 않습니다.

카카오/Supabase 메뉴가 바뀐 경우 아래 공식 문서의 현재 설정 경로를 따릅니다.
이메일 동의 없는 설정에서 카카오 `KOE205`가 나오면 요청된 scope와 앱 동의항목을 확인합니다.
로그인 성공을 위해 임의로 추가 개인정보 동의를 늘리거나 비밀값을 보고하지 않습니다.

### KOE205와 이메일 없는 로그인

Supabase의 **Allow users without an email**은 이메일 없는 계정을 허용하는 설정이며,
카카오 인가 요청에서 이메일 동의항목을 자동으로 제거하지 않습니다.
기본 제공자의 요청은 `account_email profile_image profile_nickname`이므로,
앱의 시작 handler에서 카카오에만 `queryParams.scope=profile_nickname,profile_image`를 지정합니다.
SDK의 `options.scopes`는 기본값에 항목을 추가하므로 이 용도로 사용하지 않습니다.
이 값은 서버에서 고정하며 브라우저의 scope 입력을 받지 않습니다. Google 요청은 그대로 유지합니다.

2026-10-01 사용자 실계정 시험에서 KOE205가 보고됐고, 에이전트는 배포된 시작 경로의
기본 이메일 요청과 제한한 scope가 실제 카카오 인가 URL에 반영되는 것을 확인했습니다.
이는 인가 요청 검증이며 실제 계정의 동의·callback·세션 성공을 대신하지 않습니다.

## 로컬 검증

- `npm run test:auth`: 가짜 loopback Auth와 실제 SSR SDK로 Google/Kakao 선택, PKCE, 쿠키,
  복귀·취소·실패·로그아웃·no-store 및 UUID 관리자 경계를 검증합니다. 실제 OAuth 성공이 아닙니다.
- 화면 시험은 기존 `node scripts/test_auth.mjs --serve`와 가짜 공개 데이터 서버를 사용합니다.
  프로세스 환경에서만 가짜 URL/공개 키 및 `MACHIMOA_KAKAO_LOGIN_ENABLED=true`를 설정합니다.
  사용자 `.env.local`은 자동으로 바꾸거나 출력하지 않습니다.
- 실제 로컬 카카오 확인은 사용자가 `.env.local`에 위 활성화 변수만 직접 추가하고
  기존 실제 Supabase 설정으로 `http://localhost:3100`에서 실행합니다. 로컬 origin 설정을 유지합니다.
  실제 로그인은 Supabase Auth 사용자/identity 생성 가능성이 있으며 review 데이터 저장 시험과 다릅니다.

## 실제 확인 기준

2026-10-01 로컬 결과: 인증/운영자 대역 테스트, 변경 파일 lint, 타입 검사와 Production 빌드를 통과했습니다.
빌드 초기 실패는 실행 환경의 Fonts 네트워크 제한과 가짜 우체통 공개 설정 누락이었으며,
네트워크 허용/프로세스 시험 설정 보완으로 해결했습니다. 사용자 설정 파일·무관한 코드는 변경하지 않았습니다.
빌드된 Next.js의 Google/Kakao 시작·callback·세션·로그아웃·no-store·일반 계정 관리자 거부,
공개 KO/JA·CSRF·취소를 가짜 Auth로 확인했습니다. 브라우저에서 데스크톱 양 테마와 일본어 390px 양 테마,
카카오 선택·일반 계정 복귀/새로고침·관리자 차단을 확인했습니다. 독립 검토는 필요한 교정 사항 없이 완료됐습니다.
실제 카카오 OAuth·원격 provider 설정·이 변경의 Production 배포 결과는 이 기록 시점에 미확인입니다.

한국어·일본어 로그인 화면 → 카카오 동의 → 원래 공개 화면 복귀 → 새로고침·페이지 이동 유지 →
로그아웃 후 공개 열람을 확인합니다. 취소 시 공통 취소 안내가 표시돼야 합니다.
Google 흐름도 유지돼야 합니다. 실제 제공자 왕복 확인과 에이전트 HTTP/대역 확인은 보고에서 구분합니다.

카카오 로그인 성공 자체는 운영자 권한을 부여하지 않습니다. 검증된 Supabase UUID만 기존
서버 허용 목록과 비교합니다. 이메일이 같더라도 Supabase가 연결한 identity에 따라 계정이 달라질 수 있습니다.
이번에는 별도의 계정 병합/수동 연결 기능을 만들거나 기존 허용 목록을 자동 변경하지 않습니다.

## 되돌리기

카카오를 일시 중지하려면 Vercel 활성화 변수를 `false`로 저장하고 재배포합니다.
이 조치는 신규 카카오 로그인 시작만 차단하며 이미 로그인한 세션·사용자를 삭제하지 않습니다.
Google·관리자·DB migration/권한에는 변경이 없습니다. provider 자체 중지는 Supabase에서 별도로 수행합니다.

## LINE 후속 조사

Supabase는 기본 제공자 외에 `custom:` 식별자의 OAuth2/OIDC 제공자와 email-optional 설정을 제공합니다.
LINE Login은 OAuth2/OIDC 및 PKCE S256을 지원하므로 Supabase 공식 기능으로 연결하는 경로를 검토할 수 있습니다.
후속 시작점은 LINE Login 채널 생성, 제공자 endpoint/discovery와 claims/email 매핑,
Supabase 프로젝트의 실제 custom provider 설정 지원 및 로그인 왕복 검증입니다.
이번에는 채널·provider 생성, LINE 버튼·코드, 실제 OAuth를 실행하지 않았으며 호환성 완료로 보고하지 않습니다.

## 공식 근거와 버튼 자산

- [Supabase Kakao](https://supabase.com/docs/guides/auth/social-login/auth-kakao)
- [Kakao KOE205 해결](https://developers.kakao.com/docs/ko/kakaologin/trouble-shooting)
- [Supabase Kakao 기본 scope](https://github.com/supabase/auth/blob/master/internal/api/provider/kakao.go)
- [Supabase 인가 파라미터 전달](https://github.com/supabase/auth/blob/master/internal/api/external.go)
- [Supabase SSR](https://supabase.com/docs/guides/auth/server-side/creating-a-client?queryGroups=framework&framework=nextjs)
- [Kakao 설정](https://developers.kakao.com/docs/ko/kakaologin/prerequisite)
- [Kakao 버튼 규정](https://developers.kakao.com/docs/ko/kakaologin/design-guide)
- [Kakao 공식 SVG](https://developers.kakao.com/tool/images/resource/preview/login-complete-ko.svg):
  첫 번째 심볼 path의 형태·비율을 유지해 사용합니다. 배경 `#FEE500`, 심볼 검정,
  레이블 검정 85%, radius 12px을 적용합니다. 사이트 전체 팔레트를 변경하지 않습니다.
- [Supabase custom providers](https://supabase.com/docs/guides/auth/custom-oauth-providers)
- [LINE 웹 로그인](https://developers.line.biz/en/docs/line-login/integrate-line-login/)

배포·실계정 결과는 확인한 후 별도 작업 보고에 기록합니다. 이 파일 생성만으로 실제 적용 완료를 의미하지 않습니다.
