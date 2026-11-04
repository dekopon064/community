import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
registerHooks({
  resolve(specifier, context, next) {
    if (specifier.startsWith('@/')) specifier = new URL('../' + specifier.slice(2), import.meta.url).href;
    try { return next(specifier, context); }
    catch (error) {
      if (specifier.startsWith('.') || specifier.startsWith('file:')) {
        for (const extension of ['.ts','.tsx']) {
          try { return next(specifier + extension, context); } catch { /* try next extension */ }
        }
      }
      throw error;
    }
  },
  load(url, context, next) {
    if (!url.endsWith('.tsx')) return next(url, context);
    return { format: 'module', shortCircuit: true,
      source: ts.transpileModule(readFileSync(fileURLToPath(url),'utf8'),
        { compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX } }).outputText };
  },
});
const { seoulCorrectionRequest } = await import('../app/lib/review/seoul-correction-handler.ts');
const { AdminAccessError } = await import('../app/lib/auth/admin-policy.ts');
const id = '00000000-0000-4000-8000-000000000001';
const draftId = '00000000-0000-4000-8000-000000000002';
const base = 'https://example.test/api/admin/seoul-ai-correction/' + id;
const payload = { draftId, before: '3番出口', evidence: '8번 출구', field: 'ja', value: '8' };
const post = (body = payload, origin = 'https://example.test') => new Request(base, {
  method: 'POST', headers: { origin, 'content-type': 'application/json' }, body: JSON.stringify(body),
});
const calls = [];
const deps = {
  authorize: async () => ({ userId: id }),
  invoke: async (name, args) => { calls.push([name, args]); return { id: draftId, requested: true }; },
};
const blocked = { ...deps, authorize: async () => { throw new AdminAccessError('forbidden'); } };
assert.equal((await seoulCorrectionRequest(new Request(base), id, blocked)).status, 403);
assert.equal((await seoulCorrectionRequest(post(), id, blocked)).status, 403);
assert.equal((await seoulCorrectionRequest(post(payload, 'https://other.test'), id, deps)).status, 403);
assert.equal((await seoulCorrectionRequest(post({ ...payload, p_actor: draftId }), id, deps)).status, 422);
assert.equal((await seoulCorrectionRequest(post({ ...payload, before: 'a'.repeat(9000) }), id, deps)).status, 422);
assert.equal(calls.length, 0);
const detail = await seoulCorrectionRequest(new Request(base), id, deps);
assert.match(detail.headers.get('cache-control'), /no-store/);
assert.deepEqual(calls.pop(), ['admin_seoul_ai_draft', { p_job: id }]);
const saved = await seoulCorrectionRequest(post(), id, deps);
assert.equal(saved.status, 200);
assert.deepEqual(calls.pop(), ['admin_request_seoul_ai_correction', {
  p_id: draftId, p_job: id, p_actor: id, p_field: 'ja', p_before: '3番出口', p_evidence: '8번 출구', p_value: '8',
}]);
const proof = await seoulCorrectionRequest(new Request(base + '?view=candidate'), id, deps);
assert.equal(proof.status, 200);
assert.deepEqual(calls.pop(), ['admin_seoul_ai_candidate_review', { p_candidate: id }]);
assert.equal((await seoulCorrectionRequest(post(), id, {
  ...deps, invoke: async () => { throw Object.assign(new Error(), { code: 'PT409' }); },
})).status, 409);
console.log('admin correction API passed: auth, origin, size, no-store, exact RPC arguments and conflict');


const { CorrectionComparison } = await import('../app/components/admin/SeoulAiCorrection.tsx');
const proofHtml = renderToStaticMarkup(createElement(CorrectionComparison, { detail: {
  field: 'ja', before: '<script>3番出口</script>', after: '8番出口',
  evidence: '8번 출구', sourceUrl: 'https://example.test/source',
} }));
for (const text of ['AI 수정', '수정 전', '수정 후', '원문 근거', '8番出口', '8번 출구', '&lt;script&gt;', 'https://example.test/source']) {
  assert.ok(proofHtml.includes(text), text);
}
assert.ok(!proofHtml.includes('<script>'));
console.log('approval evidence renders both excerpts and source link as safe text');

const { SeoulCandidateFindings, applySeoulReviewPatch } = await import('../app/components/admin/SeoulAiCorrection.tsx');
const issue = { stage: 'japanese_validation', rule: 'clock', reason: 'mismatch',
  disposition: 'change', location: { table: 1, row: 2, column: 3 },
  expected: ['time', 10, 0], actual: ['time', 10, 30], field: 'contentJa',
  before: '10:30', after: '10:00', evidence: '원문은 오전 10:00' };
const content = { titleKo: '합성', titleJa: '合成', summaryKo: '안내', summaryJa: '案内',
  contentKo: '오전 10:00', contentJa: '午前10:30' };
const review = { source: '원문은 오전 10:00 <script>', issues: [
  issue, { ...issue, disposition: 'equivalent' }, { ...issue, disposition: 'needs_review' },
] };
const advisory = await seoulCorrectionRequest(new Request(base + '?view=candidate'), id, {
  ...deps, invoke: async () => ({ review, evidence: null }),
});
assert.deepEqual((await advisory.json()).review, review);
assert.equal((await seoulCorrectionRequest(new Request(base + '?view=candidate'), id, blocked)).status, 403);
const html = renderToStaticMarkup(createElement(SeoulCandidateFindings, { review, content, onChange: () => {} }));
for (const text of ['AI 오류·수정 검토', '수집된 원문 근거 보기', '표 1', '2행', '3열',
  '기대값 10:00', '검사값 10:30', 'AI 수정 제안', '수정 전', '수정 후', '수정안 적용', '뜻이 같은 표현', '운영자 확인 필요']) {
  assert.ok(html.includes(text), text);
}
assert.ok(html.includes('&lt;script&gt;'));
assert.ok(!html.includes('재검증'));
const edited = applySeoulReviewPatch(content, issue);
assert.deepEqual(edited, { ...content, contentJa: '午前10:00' });
assert.equal(applySeoulReviewPatch(edited, issue), null);
assert.equal(applySeoulReviewPatch({ ...content, contentJa: '10:30 10:30' }, issue), null);
assert.deepEqual(applySeoulReviewPatch({ ...content, summaryJa: '10:30' }, { ...issue, summaryPatch: true }),
  { ...edited, summaryJa: '10:00' });
console.log('candidate review passed: fake auth/RPC, source, diagnostic, changed and unchanged findings, safe rendering and editor patch');
