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
    if (url.endsWith('.css')) return { format: 'module', shortCircuit: true, source: 'export default {}' };
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
for (const text of ['AI 결과 검토', '수집된 원문 전체 보기', '표 1', '2행', '3열',
  '기준 10:00', '결과 10:30', 'AI 수정 제안', '수정 전', '수정안 적용', '같은 의미', '근거 확인 필요', '현재 후보 문구', '미적용']) {
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

const { groupReviewIssues, issueExcerpt, reviewSaveState } = await import('../app/components/admin/SeoulCandidateFindings.tsx');
const equivalent = {stage:'japanese_validation',rule:'per_session',reason:'added',disposition:'equivalent',
  location:{item:1,field:'body'},expected:[],actual:[[1,1]],evidence:'한 ID당 각 회차 1회 예약'};
const listContent = {...content,contentJa:'[申込条件]\n- 各回1回のみ予約できます。\n- 各回1回のみ予約できます。'};
const repeated = {...equivalent,location:{item:2,field:'body'}};
assert.equal(groupReviewIssues([equivalent,repeated],listContent).length,2);
assert.equal(groupReviewIssues([equivalent,{...repeated,evidence:'다른 근거'}],listContent).length,2);
assert.equal(groupReviewIssues([issue,issue],content).length,2,'do not merge independently applied changes');
assert.equal(issueExcerpt(listContent,equivalent),null);
assert.equal(issueExcerpt(listContent,{...equivalent,location:{item:9,field:'body'}}),null);
const tableContent = {...content,contentJa:'| 曜日 | 時間 |\n| --- | --- |\n| 土曜日 | 10:30 |'};
assert.equal(issueExcerpt(tableContent,{...equivalent,location:{table:1,row:1,column:2,field:'body'}}),null);
assert.equal(issueExcerpt(tableContent,{...equivalent,location:{table:2,row:1,column:2,field:'body'}}),null);
assert.equal(reviewSaveState(issue,content,content),'AI 수정 제안 · 미적용');
assert.equal(reviewSaveState(issue,edited,content,edited),'편집기에 반영됨 · 저장 전');
assert.equal(reviewSaveState(issue,edited,edited),'후보에 저장됨 · 제안 문구와 일치');
assert.equal(reviewSaveState(issue,{...content,contentJa:'別の文'},content,edited),'직접 편집 또는 다른 변경 · 저장 전');
assert.equal(reviewSaveState(issue,content,content,edited),'AI 수정 제안 · 미적용','cancel resets by saved comparison');
assert.equal(applySeoulReviewPatch(content,{...issue,after:issue.before}),null);
const summaryIssue = {...issue,summaryPatch:true};
assert.equal(reviewSaveState(summaryIssue,{...edited,summaryJa:'10:30'},{...edited,summaryJa:'10:30'}),'저장본 · 제안 위치 확인 필요','body alone must not imply summary saved');
const groupedHtml=renderToStaticMarkup(createElement(SeoulCandidateFindings,{review:{source:'원문',issues:[equivalent,repeated]},content:listContent}));
assert.equal((groupedHtml.match(/<li /g)||[]).length,2);
assert.ok(groupedHtml.includes('수정 불필요 · 참고 이력 2개'));
assert.ok(groupedHtml.includes('추가로 수정할 사항은 없습니다'));
assert.ok(!groupedHtml.includes('현재 후보 문구'));
assert.ok(!groupedHtml.includes('본문에서 직접 편집'));
assert.ok(!groupedHtml.includes('<details open'));
assert.ok(groupedHtml.includes('AI가 수정한 부분은 없습니다.'));
assert.ok(!groupedHtml.includes('수정안 적용'));
const historical=renderToStaticMarkup(createElement(SeoulCandidateFindings,{review:{source:'원문',issues:[{...equivalent,location:{field:'body'}}]},content}));
assert.ok(historical.includes('별도 수정·저장'));
assert.ok(historical.includes('당시 검사 기록'));
assert.ok(!historical.includes('현재 필드 전체 보기'));
assert.ok(!historical.includes('원문에 없는 조건입니다'));
console.log('review presentation passed: grouping, missing historical excerpts, list/table locations, apply/save/manual/cancel and summary states');

assert.equal(applySeoulReviewPatch({...content,contentJa:'100명'}, {...issue,before:'10',after:'100'}),null,'do not apply a substring patch twice');

// Stale locations must never point at unrelated current text, including title/line/table.
const displaced = {...content, contentJa:'- **実施方式:** 対面\n- 別の案内'};
for (const location of [{item:1,field:'body'},{line:1,field:'body'},{table:1,row:1,column:2,field:'body'},{field:'title'}]) {
  assert.equal(issueExcerpt(displaced,{...equivalent,location}),null);
}
assert.equal(issueExcerpt(displaced,{...issue,before:'gone',after:'missing',location:{line:1,field:'body'}}),null);
assert.equal(issueExcerpt(content,issue),'午前10:30');
assert.equal(issueExcerpt(edited,issue),'午前10:00');
assert.equal(issueExcerpt({...content,contentJa:'10:30\n10:30'},issue),null);
const unresolved=renderToStaticMarkup(createElement(SeoulCandidateFindings,{review:{source:'원문',issues:[{...equivalent,disposition:'needs_review'}]},content:displaced,onChange:()=>{}}));
assert.ok(!unresolved.includes('**実施方式:** 対面</p>'));
assert.ok(unresolved.includes('과거 위치로 다른 문장을 표시하지 않습니다'));
assert.ok(unresolved.includes('전체에서 확인·편집'));
assert.ok(html.indexOf('AI 수정 제안')<html.indexOf('수정 불필요 · 참고 이력'));
assert.ok(html.indexOf('당시 AI 검토의 세부 결과가 기록되지 않았습니다')<html.indexOf('수정 불필요 · 참고 이력'));
assert.ok(!renderToStaticMarkup(createElement(SeoulCandidateFindings,{review:{source:'',issues:[issue]},content})).includes('참고 이력'));
console.log('history and stale-location checks passed: collapsed non-actionable history, action priority, unique text matching, no coordinate fallback');

const { currentYenLines, reviewOutcomeText } = await import('../app/lib/review/seoul-review-status.ts');
const seongbuk = JSON.parse(readFileSync(new URL('./testdata/seongbuk_review_context.json', import.meta.url), 'utf8'));
const unchanged = JSON.stringify(seongbuk);
const pastHtml = renderToStaticMarkup(createElement(SeoulCandidateFindings, {
  review: seongbuk.review, content: seongbuk.current, onChange: () => { throw Error('unexpected edit'); },
}));
for (const text of ['과거 진단 9개', '현재 감지 없음 1개', '문구 연결 확인 필요 8개',
  '근거 확인 필요 0개', '현재 한·일 본문과 저장 원문 대조', '현재 엔화 표기 없음',
  '당시 AI 검토의 세부 결과가 기록되지 않았습니다', '현재 한국어 본문', '현재 일본어 본문']) assert.ok(pastHtml.includes(text), text);
assert.ok(!pastHtml.includes('근거가 부족하거나 안전한 수정안을'));
assert.equal(JSON.stringify(seongbuk), unchanged);
for (const text of ['円滑な運営','円満','円形','100ウォン']) assert.equal(currentYenLines({...content,contentJa:text}).length,0);
for (const text of ['100円','１００円','千円','¥100','￥100','日本円','費用：円']) assert.equal(currentYenLines({...content,contentJa:text}).length,1,text);
const currency={stage:'japanese_validation',rule:'translation_currency',reason:'unexpected_yen',disposition:'needs_review'};
const moneyHtml=renderToStaticMarkup(createElement(SeoulCandidateFindings,{review:{source:'요금 100원',issues:[currency]},content:{...content,contentJa:'料金100円'}}));
assert.ok(moneyHtml.includes('근거 확인 필요 1개'));
assert.ok(moneyHtml.includes('料金100円'));
assert.ok(!moneyHtml.includes('현재 엔화 표기 없음'));
const captured={...issue,disposition:'needs_review',field:undefined,before:undefined,after:undefined,
  location:{field:'body',table:1,row:1,column:2},context:{field:'contentJa',candidate:'10:30',reference:'오전 10:00'},reviewOutcome:'evidence_not_matched'};
assert.equal(issueExcerpt(content,captured),'午前10:30');
assert.equal(issueExcerpt({...content,contentJa:'10:30\n10:30'},captured),null);
assert.equal(issueExcerpt({...content,contentJa:'無関係な文'},captured),null);
const capturedHtml=renderToStaticMarkup(createElement(SeoulCandidateFindings,{review:{source:'오전 10:00',issues:[captured]},content}));
for(const text of ['검사 당시 대조한 한국어','오전 10:00','현재 후보 문구','午前10:30','원문과 정확히 일치하지 않아']) assert.ok(capturedHtml.includes(text),text);
assert.match(reviewOutcomeText({...captured,reviewOutcome:'ai_needs_review'}),/AI가 확인 보류로 응답/);
assert.match(reviewOutcomeText({...captured,reviewOutcome:'unsafe_patch'}),/위치·범위/);
assert.match(reviewOutcomeText({...captured,reviewOutcome:'no_finding'}),/응답에 없었습니다/);
console.log('Seongbuk + counterexamples passed: immutable 9 historical findings, current money detection, bounded matching context, truthful AI outcomes, no false resolution of unlinked records');
