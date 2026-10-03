// New UI mapping checks and an explicit loopback synthetic RPC server.
// No environment files, real Auth, DB, site, SQL evaluator, or AI are used.
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:http';
registerHooks({ resolve(s, c, next) { try { return next(s, c); } catch (e) { if (s.startsWith('.') && !/\.[a-z]+$/i.test(s)) return next(`${s}.ts`, c); throw e; } } });
const { buildMySeoulSave, myseoulPatch, displayMySeoulValue } = await import('../app/lib/review/myseoul-ui.ts');
const { myseoulReasonFields } = await import('../app/lib/review/myseoul-contract.ts');
const { myseoulItem } = await import('../app/lib/review/myseoul-store.ts');
const { reviewDetailPath } = await import('../app/lib/review/program-ui.ts');
const { LocalReviewStore } = await import('../app/lib/review/local-fixture.ts');
const scripts = fileURLToPath(new URL('./', import.meta.url));
const samples = JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON, ['-X', 'utf8', 'test_myseoul_db.py', '--fixtures'], { cwd: scripts, encoding: 'utf8' }));
const actor = '00000000-0000-4000-8000-000000000001';
const makeItem = (n, sample, reasons) => {
  const facts = structuredClone(sample.item.myseoul_facts);
  const id = `40000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
  return myseoulItem({ id, revision: facts.source_revision, version: 'b'.repeat(64), schema: facts.schema_version, profile: 'myseoul-program-v1-local', factsVersion: 1,
    source: { name: 'myseoul_program', title: n === 1 ? '신청 방법·비용 확인 (합성 시험 자료)' : '일정·분류 확인 (합성 시험 자료)', url: facts.official_url, body: facts.description },
    facts, observedFacts: structuredClone(facts), result: { ...sample.expected, decision: 'review_required', disposition: 'observe_only', reasons }, status: 'open', aiStatus: 'blocked',
    editableFields: [...new Set(reasons.flatMap(myseoulReasonFields))], history: [] }, id);
};
const first = makeItem(1, samples.fixtures.find(f => f.name === 'two_conflicts'), ['source_fact_conflict:application_method', 'source_fact_conflict:tuition']);
const second = makeItem(2, samples.fixtures[0], ['operation_period_unknown', 'category_unresolved', 'unsupported_test_reason']);
const items = new Map([first, second].map(i => [i.id, i]));
if (!process.argv.includes('--serve')) {
  let checks = 0;
  const eq = (a, b) => { assert.deepEqual(a, b); checks++; };
  eq(reviewDetailPath('facts', first.id, 'myseoul_program'), `/api/admin/myseoul-review/${first.id}`);
  eq(reviewDetailPath('facts', first.id, 'seoul_reservation'), `/api/admin/program-review/${first.id}`);
  for (const [kind, source] of [['facts', 'youthcenter_policy'], ['facts', 'youthcenter_content'], ['candidates', 'myseoul_program']]) eq(reviewDetailPath(kind, first.id, source), `/api/admin/review/${kind}/${first.id}`);
  const draft = structuredClone(first.facts); draft.application_methods = ['인터넷·방문 병행']; draft.missing = []; draft.target = 'FORGED READONLY';
  const command = buildMySeoulSave(first, draft, '확인한 근거', ['source_fact_conflict:application_method']);
  eq(command.patch, { application_methods: ['인터넷·방문 병행'] });
  eq([command.revision, command.version, command.resolve], [first.revision, first.version, ['source_fact_conflict:application_method']]);
  eq(myseoulPatch(first.facts, draft, []), {});
  for (const resolve of [['source_fact_conflict:tuition'], ['unsupported_test_reason']]) { assert.throws(() => buildMySeoulSave(first, draft, '근거', resolve), e => e.code === 'invalid_input'); checks++; }
  eq(displayMySeoulValue('fees', [{ component: 'tuition', evidence: ['무료'] }, { component: 'admission', evidence: ['3,000원'] }]), '수강료: 무료\n입장료: 3,000원');
  const periods = structuredClone(second.facts.periods); const changed = structuredClone(second.facts); changed.periods.operation[0].endpoints[1].value = '2099-11-04';
  eq(buildMySeoulSave(second, changed, '운영 일정 근거', []).patch.periods.application, periods.application);
  const pasted = structuredClone(first.facts); pasted.application_links = [' https://example.test/apply ', '']; pasted.fees = [{ component: 'tuition', evidence: [' 무료 확인 ', ''] }];
  eq(buildMySeoulSave(first, pasted, '원문 근거', []).patch.application_links, ['https://example.test/apply']);
  eq(buildMySeoulSave(first, pasted, '원문 근거', []).patch.fees, [{ component: 'tuition', evidence: ['무료 확인'] }]);
  eq(myseoulPatch(first.facts, { ...first.facts, application_methods: [...first.facts.application_methods, ''] }, first.editableFields), {});
  console.log(`PASS: ${checks} new My Seoul+ UI routing/patch/resolve/period/fee checks.`);
} else {
  const legacy = new LocalReviewStore();
  const seoulSamples = JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON, ['-X', 'utf8', 'test_program_db.py', '--fixtures'], { cwd: scripts, encoding: 'utf8' }));
  const seoulFacts = seoulSamples.fixtures[0].item.program_facts;
  const seoul = { id: '30000000-0000-4000-8000-000000000001', revision: 'a'.repeat(64), version: 'b'.repeat(64), schema: 'program-scope-v1-local', profile: 'program_capital_v1_local', factsVersion: 1,
    source: { name: 'seoul_reservation', title: '서울 기존 계약 확인 (합성 시험 자료)', url: seoulFacts.official_url, body: '기존 서울 입력 경로를 확인하는 합성 원문' },
    facts: seoulFacts, observedFacts: seoulFacts, result: { decision: 'review_required', disposition: 'observe_only', reasons: ['activity_location_unknown'] }, status: 'open', aiStatus: 'blocked', editableFields: ['activity_region', 'activity_evidence'], history: [] };
  let mutations = 0;
  const server = createServer(async (req, res) => {
    try {
      const chunks = []; for await (const c of req) chunks.push(c); const body = Buffer.concat(chunks);
      if (!req.url.startsWith('/rest/v1/rpc/admin_')) {
        const upstream = await fetch(`http://127.0.0.1:54329${req.url}`, { redirect: 'manual', method: req.method, headers: { 'content-type': req.headers['content-type'] ?? 'application/json', authorization: req.headers.authorization ?? '' }, ...(req.method === 'GET' ? {} : { body }) });
        res.writeHead(upstream.status, Object.fromEntries(upstream.headers)); res.end(Buffer.from(await upstream.arrayBuffer())); return;
      }
      const args = JSON.parse(body.toString()), name = req.url.split('/').at(-1); let data;
      if (name === 'admin_review_list') {
        data = await legacy.list(args.p_kind, args.p_offset);
        if (args.p_kind === 'facts' && args.p_offset === 0) data = [...items.values()].filter(i => i.status === 'open').map(i => ({ id: i.id, title: i.source.title, sourceName: i.source.name, status: i.status, reasons: i.result.reasons })).concat([{ id: seoul.id, title: seoul.source.title, sourceName: 'seoul_reservation', status: 'open', reasons: seoul.result.reasons }], data);
      } else if (name === 'admin_review_detail') {
        data = await legacy.get(args.p_kind, args.p_id); data.version = 'c'.repeat(64);
        if (data.kind === 'facts') { data.editableFields = ['scope', 'regions', 'evidence']; data.excludeAllowed = false; }
      }
      else if (name === 'admin_program_detail') data = seoul;
      else if (name.startsWith('admin_myseoul_program_')) {
        const item = items.get(args.p_id);
        if (!item) data = { code: 'PT404' };
        else if (name === 'admin_myseoul_program_detail') data = item;
        else if (args.p_note === '충돌 시험' || args.p_version !== item.version) data = { code: 'PT409' };
        else if (args.p_note === '실패 시험') data = { code: 'XX000' };
        else if (args.p_actor !== actor) data = { code: 'PT422' };
        else {
          data = structuredClone(item); mutations++;
          if (name === 'admin_myseoul_program_exclude') { data.status = 'excluded'; data.result = { ...data.result, decision: 'out_of_scope', disposition: 'non_target', reasons: ['manual_service_scope_excluded'] }; }
          else { Object.assign(data.facts, args.p_patch); data.result.reasons = data.result.reasons.filter(code => !args.p_resolve.includes(code)); if (!data.result.reasons.length) { data.status = 'resolved'; data.result.decision = 'in_scope'; data.result.disposition = 'target'; } }
          data.editableFields = data.status === 'open' ? [...new Set(data.result.reasons.flatMap(myseoulReasonFields))] : [];
          data.version = String(mutations).padStart(64, '0'); data.factsVersion++;
          data.history.unshift({ action: name.endsWith('exclude') ? 'exclude' : 'save_facts', actor, at: new Date().toISOString(), note: args.p_note, fields: Object.keys(args.p_patch ?? {}) });
          items.set(item.id, data);
        }
      } else data = { code: 'PT422' };
      res.setHeader('content-type', 'application/json'); res.setHeader('cache-control', 'no-store'); if (data.code) res.statusCode = data.code === 'PT409' ? 409 : data.code === 'PT404' ? 404 : 503; res.end(JSON.stringify(data));
    } catch { res.writeHead(500, { 'content-type': 'application/json' }); res.end('{"code":"XX000"}'); }
  });
  await new Promise(r => server.listen(54331, '127.0.0.1', r));
  console.log('Synthetic My Seoul+ RPC UI server on 127.0.0.1:54331. Not SQL/DB/AI.');
}
