// Synthetic SQL DTO + fake Auth/RPC. No network, credentials or product writes.
import assert from 'node:assert/strict';
import { readFileSync, existsSync, writeFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

registerHooks({
  resolve(specifier, context, next) {
    if (specifier === 'server-only') return { url: 'data:text/javascript,export{}', shortCircuit: true };
    try { return next(specifier, context); }
    catch (error) {
      if (specifier.startsWith('.')) for (const ext of ['.ts', '.tsx']) {
        const url = new URL(specifier + ext, context.parentURL);
        if (existsSync(url)) return next(url.href, context);
      }
      throw error;
    }
  },
  load(url, context, next) {
    if (url.endsWith('.tsx')) return { format: 'module', shortCircuit: true,
      source: ts.transpileModule(readFileSync(new URL(url), 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext } }).outputText };
    return next(url, context);
  },
});
globalThis.fetch = async () => { throw new Error('Network forbidden'); };
const { databaseItem } = await import('../app/lib/review/database-dto.ts');
const { DatabaseReviewStore } = await import('../app/lib/review/database-store.ts');
const { reviewDetail } = await import('../app/lib/review/handlers.ts');
const { AdminAccessError } = await import('../app/lib/auth/admin-policy.ts');
const { default: Panel } = await import('../app/components/admin/CulturePortalReview.tsx');
const dto = JSON.parse(readFileSync(new URL('./fixtures/culture_portal/admin-synthetic.json', import.meta.url), 'utf8'));
const calls = [];
const store = new DatabaseReviewStore({ rpc: async (name, args) => {
  calls.push({ name, args });
  assert.equal(name, 'admin_review_detail');
  return { data: { ...dto, secret_unallowed: 'DO_NOT_ECHO' }, error: null };
} });
const deps = { authorize: async () => ({ userId: '00000000-0000-4000-8000-000000000001' }), store: () => store };
const request = () => new Request(`http://localhost/api/admin/review/facts/${dto.id}`);
let checks = 0;
function check(value, message) { assert.ok(value, message); checks++; }
const response = await reviewDetail(request(), 'facts', dto.id, deps);
check(response.status === 200, 'Authorized normal admin read');
check(/private.*no-store/.test(response.headers.get('cache-control')), 'Private response');
const body = await response.json();
check(!JSON.stringify(body).includes('DO_NOT_ECHO'), 'Only projected fields');
check(body.item.collectionReview.matches.length > 0, 'Duplicate comparison present');
check(body.item.aiStatus === 'blocked', 'New collector cannot start AI');
const count = calls.length;
for (const [reason, status] of [['signed_out', 401], ['forbidden', 403], ['auth_unavailable', 503]]) {
  const denied = await reviewDetail(request(), 'facts', dto.id, { ...deps, authorize: async () => { throw new AdminAccessError(reason); } });
  check(denied.status === status, 'Auth denial');
}
check(count === calls.length, 'Denied reads never reach RPC');
for (const changed of [{ ...dto.collectionReview, matches: [{ id: 'invalid' }] }, { ...dto.collectionReview, issues: null }]) {
  assert.throws(() => databaseItem({ ...dto, collectionReview: changed }, 'facts', dto.id)); checks++;
}
const review = { ...body.item.collectionReview, outcome: 'change_review', issues: [
  { code: 'portal_information_conflict', field: 'hours', evidence: ['기본 정보 11:00~19:30', '포스터 대체텍스트 11:00~19:00'] },
  { code: 'portal_missing_information', field: 'booking', evidence: [] },
  { code: 'portal_image_evidence', field: 'poster_text', evidence: ['<script>not executable</script>'] },
] };
const markup = renderToStaticMarkup(React.createElement(Panel, { review }));
for (const text of ['중복 비교 대상', '11:00~19:30', '11:00~19:00', '수집된 근거 없음', '기존 저장값·운영자 판단', '&lt;script&gt;']) check(markup.includes(text), `Render: ${text}`);
check(!markup.includes('<script>'), 'Untrusted source text escaped');
check(!markup.includes('<button'), 'Read panel adds no write action');
// A standalone local preview renders the PRODUCT component with SYNTHETIC DTO.
// It is outside app routes, never a fixture fallback for product requests.
if (process.argv.includes('--preview')) {
  const target = process.argv[process.argv.indexOf('--preview') + 1];
  if (!target) throw new Error('Preview path required');
  writeFileSync(target, `<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>서울문화포털 · 합성 검토 자료</title><style>body{font-family:Arial,sans-serif;background:#edf7fb;color:#12325d;line-height:1.7;margin:0}main{max-width:1050px;margin:auto;padding:24px}h3,h4{margin:20px 0 8px}p{margin:8px 0}blockquote{margin:8px 0;border-left:3px solid #b9ccdf;padding:8px 16px;overflow-wrap:anywhere}code{overflow-wrap:anywhere}li{margin:16px 0}section{border-top:1px solid #b9ccdf}small{display:block;background:#fff;padding:12px}</style><main><h1>서울문화포털 수집 검토</h1><small>로컬 합성 자료 · 실제 관리자 컴포넌트 렌더링 · 운영 DB/저장/AI 연결 없음</small>${markup}</main></html>`, 'utf8');
  console.log(`Preview: ${target}`);
}
console.log(JSON.stringify({ checks, fakeAuthRpc: true, productionAccess: false, componentRender: true }));
