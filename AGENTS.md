<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## 수집·AI 관련 배포

수집·AI 관련 배포에서는 [.cursor/rules/ingest-pc-worker-release.mdc](.cursor/rules/ingest-pc-worker-release.mdc)를 따른다. 웹 배포와 함께 기존 PC 시작 파일의 worker 최신화·연결 확인까지 완료하고, 실제 수집·AI 호출은 별도 실행 요청이 있을 때만 진행한다. 이 저장소 아래의 worktree에도 적용한다.
