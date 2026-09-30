# Google 로그인 설정 및 로컬 검증

이 문서는 일반 로그인 기반 단계의 설정·검증 기록입니다. 이후 운영자 권한과 review 관리 DB 연결이 추가되었습니다.
현재 관리자 설정과 Production DB 적용 결과는 [ADMIN_ACCESS_SETUP.md](ADMIN_ACCESS_SETUP.md)와 [ADMIN_REVIEW.md](ADMIN_REVIEW.md)를 확인하세요.
`@supabase/ssr`의 PKCE와 쿠키 세션을 사용하며 서버에서 `getClaims()`로 사용자를 검증합니다.
로그인·로그아웃은 서버 경로에서 처리하고 인증 쿠키는 HttpOnly입니다. 공개 데이터 조회는 기존 익명 클라이언트를 유지합니다.

## 먼저 구분할 계정

Supabase 대시보드에 Google 계정으로 로그인한 것은 서비스 이용자의 Google 로그인을 활성화한 것이 아닙니다.
같은 Google 계정으로 Google Cloud 프로젝트를 관리할 수 있으며 별도의 유료 개발자 계정 가입은 필요하지 않습니다.

## 설정 순서 (사용자가 직접 입력)

현재 작업에서는 원격 Supabase 설정이나 사용자 데이터를 조회·변경하지 않았습니다.
실제 로그인 시험은 Auth 사용자 생성이 발생할 수 있으므로 먼저 개발용 Supabase 프로젝트로 진행하세요.
운영 프로젝트의 설정 변경·실제 로그인·배포는 별도의 다음 작업입니다.

1. 개발용 Supabase 프로젝트의 Authentication → Sign In / Providers → Google에서 콜백 URL을 확인합니다.
   보통 `https://<개발-프로젝트-ref>.supabase.co/auth/v1/callback`입니다. 이 값이 Google에 등록할 주소입니다.
2. Google Cloud Console → Google Auth Platform에서 프로젝트의 Branding, Audience, Data Access를 설정합니다.
   서비스 이름·지원 이메일을 입력하고 External / Testing이면 시험할 Google 계정을 Test users에 등록합니다.
   기본 로그인 범위인 `openid`, 이메일, 기본 프로필만 사용합니다.
3. Clients에서 **Web application** OAuth 클라이언트를 만듭니다.
   Authorized redirect URIs에 1번의 **Supabase 콜백 URL**을 정확히 등록합니다.
   Authorized JavaScript origins가 필요하면 `http://localhost:3100`을 입력합니다. 경로는 넣지 않습니다.
   이번 구현은 서버 리디렉션 방식이므로 브라우저용 Google SDK는 사용하지 않습니다.
4. 생성된 Client ID와 Client Secret을 Supabase의 Google Provider 설정에 직접 입력하고 활성화합니다.
   Secret은 Google/Supabase 설정 화면에만 입력합니다. 앱의 공개 환경변수, 코드, Git, 채팅에는 넣지 않습니다.
5. 개발용 Supabase Authentication → URL Configuration에서 Site URL을 `http://localhost:3100`으로 설정합니다.
   Redirect URLs에 개발용 패턴 `http://localhost:3100/api/auth/callback**`을 허용합니다.
   앱은 해당 콜백에 언어와 복귀 경로 쿼리를 함께 전달하므로 쿼리까지 매칭할 수 있어야 합니다.
   이 패턴은 지정한 로컬 콜백으로만 범위를 좁힌 것입니다.
6. 작업 checkout의 Git에서 제외되는 `.env.local`에 아래 공개 설정과 서버 설정을 직접 입력합니다.
   기존 공개 데이터 클라이언트가 사용하는 anon 키를 유지하세요. service role / secret API key는 필요하지 않습니다.

```dotenv
NEXT_PUBLIC_SUPABASE_URL=https://<개발-프로젝트-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<개발-프로젝트의-공개-anon-key>
AUTH_SITE_URL=http://localhost:3100
```

인증 클라이언트는 선택적으로 `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`도 지원합니다.
기존 공개 조회가 `NEXT_PUBLIC_SUPABASE_ANON_KEY`를 사용하므로 위 설정을 우선 유지합니다.
`AUTH_SITE_URL`은 경로 없는 앱 origin이며 브라우저에서 접속한 origin과 일치해야 합니다.
`localhost`와 `127.0.0.1`, 다른 포트를 섞지 마세요. 운영 시에는 승인된 HTTPS origin을 명시해야 합니다.

7. `npm run dev -- --port 3100`으로 실행하고 `/ko` 또는 `/ja`에서 헤더의 로그인 버튼을 누릅니다.
   Google 인증 이후 원래 페이지로 돌아오는지, 새로고침·다른 페이지 이동 후 상태가 유지되는지 확인합니다.
   헤더의 계정 버튼에서 로그아웃합니다. 취소·실패 안내와 익명 공개 열람도 확인합니다.

## 원격 연결 없이 이번에 수행하는 검증

- `npm run test:auth`: 루프백 가짜 Auth 서버와 실제 Supabase SSR SDK로 PKCE, 쿠키, 서버 검증,
  세션 갱신 및 next-intl rewrite의 쿠키 전달, 취소·실패·만료, 복귀 주소, 교차 origin POST 차단,
  로그아웃과 no-store 응답을 검증합니다. Google OAuth 자체의 성공을 의미하지 않습니다.
- `node scripts/test_auth.mjs --serve`: 브라우저 점검용 가짜 Auth/빈 공개 데이터 서버를 `127.0.0.1:54329`에 띄웁니다.
  Google 제공자로 이동하지 않고 로컬 시험 코드만 반환합니다. 개발·운영 앱 설정에 이 주소를 사용하지 마세요.
- 화면 시험 때만 프로세스 환경변수로 URL `http://127.0.0.1:54329`, anon 키 `local-test-publishable-key`,
  앱 origin `http://localhost:3100`을 사용했습니다. 실제 설정 파일은 생성하지 않았습니다.

## 다음 단계: 운영자 연결

`app/lib/auth/server.ts`의 요청별 인증 클라이언트와 `getClaims()`에서 검증한 사용자 `sub`가 시작점입니다.
서버의 지정 UUID 허용 목록 및 관리자 작업마다 권한 검사를 추가해야 합니다.
브라우저 헤더의 로그인 표시는 권한 근거가 아닙니다. 일반 로그인은 운영자 권한을 부여하지 않습니다.
기존 review RPC를 관리자 전용 서버 호출 경로에 연결하는 작업은 별도로 설계·검증합니다.

## 이번 작업의 확인 결과 (2026-09-30)

- 원격 main `c6cb7b0b39f80291527b6cea9fc2f625acdc0e19`에서 만든 `codex/google-login` checkout입니다.
  원래 폴더의 미커밋 변경은 보존했습니다. commit·push·PR·배포는 수행하지 않았습니다.
- Node 24.14.1에서 인증 흐름 테스트, 서비스 워커 페이지 캐시 정책 테스트, 변경 파일 lint,
  `tsc --noEmit`, 최종 `npm run build`를 통과했습니다.
  빌드는 가짜 Supabase와 기존 문의 화면의 시험용 공개 Turnstile 설정을 사용했습니다.
- 전체 `npm run lint`는 main에 이미 존재한 `scripts/test_markdown_single_tilde.mjs:21`의
  `react/no-children-prop` 오류 1건으로 실패합니다. 이번 변경에 포함하지 않았습니다.
- 빌드된 실제 Next.js 로컬 경로에서도 PKCE 시작·콜백 쿠키 저장·서버 상태 확인·로그아웃 쿠키 삭제,
  교차 origin POST 거부와 인증/로그인/인증된 공개 페이지의 no-store 헤더를 확인했습니다.
- 브라우저에서 가짜 로그인 → 쿼리·앵커를 포함한 원래 화면 복귀 → 새로고침 → 카테고리 이동 →
  로그인 유지 → 로그아웃 → 익명 열람을 확인했습니다. Google 제공자 오류의 fragment 형식은
  원문을 노출하지 않고 취소 안내로 바꿉니다.
- 한·일 및 라이트·다크 화면, 320px·390px·데스크톱을 확인했습니다.
  독립 검토 1회에서 지적된 로그인 화면 언어 전환 시 복귀 주소 소실을 수정하고 해당 흐름을 재검증했습니다.
  좁은 모바일 헤더의 넘침도 교정했습니다.
- 실제 Google OAuth, 원격 Supabase 연결, 운영 환경의 권한·데이터·배포는 검증하지 않았습니다.

## 공식 참고 문서

- [Supabase Google 로그인](https://supabase.com/docs/guides/auth/social-login/auth-google)
- [Supabase Next.js 서버 인증](https://supabase.com/docs/guides/auth/server-side/creating-a-client?queryGroups=framework&framework=nextjs)
- [Supabase Redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls)

로컬 Next.js 16.2.10 설치본의 Proxy, Route Handler, cookies 가이드를 코드 작성 전에 확인했습니다.
