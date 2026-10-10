// Synthetic selections and the actual panel's handlers. All fetches are denied
// unless explicitly supplied below; no environment file, Auth, DB or AI.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
const require = createRequire(import.meta.url), ts = require('typescript'), React = require('react');
const root = fileURLToPath(new URL('../', import.meta.url));
let states = [], refs = [], cursor = 0, refCursor = 0;
const fakeReact = { ...React, useState(initial) { const i = cursor++; if (!(i in states)) states[i] = typeof initial === 'function' ? initial() : initial; return [states[i], value => { states[i] = typeof value === 'function' ? value(states[i]) : value; }]; }, useEffect() {}, useRef(initial) { return refs[refCursor++] ??= { current: initial }; } };
const cache = new Map();
function load(name) {
  const filename = path.resolve(root, name);
  if (cache.has(filename)) return cache.get(filename);
  const exports = {}; cache.set(filename, exports);
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
  new Function('require', 'exports', code)(s => {
    if (s === 'react') return fakeReact;
    if (s === 'next/link') return { default: () => null };
    if (s.startsWith('@/') || s.startsWith('.')) {
      const target = s.startsWith('@/') ? path.join(root, s.slice(2)) : path.resolve(path.dirname(filename), s);
      for (const suffix of ['.ts', '.tsx', '']) if (fs.existsSync(target + suffix)) return load(path.relative(root, target + suffix));
    }
    return require(s);
  }, exports);
  return exports;
}
let checks = 0;
const eq = (a, b) => { assert.deepEqual(a, b); checks++; };
const ok = a => { assert.ok(a); checks++; };
const fails = fn => { assert.throws(fn); checks++; };
const { factsFromFilterSelection, mergeMySeoulFilters, myseoulFilterFields, assertMySeoulFilterContinuation } = load('app/lib/review/myseoul-filter-ui.ts');
const { parseContentFilters, contentFilterSchema } = load('app/lib/contentFilters.ts');
const { myseoulItem } = load('app/lib/review/myseoul-store.ts');
const { myseoulReasonFields } = load('app/lib/review/myseoul-contract.ts');
const { filterSaveBody, saveFilterRequest, FilterInputs, filterReviewFields, reviewFilterLabel } = load('app/components/admin/FilterReviewPanel.tsx');
const Panel = load('app/components/admin/MySeoulReviewPanel.tsx').default;
const unknown = { status: 'unknown', value: null }, na = { status: 'not_applicable', value: null }, known = value => ({ status: 'known', value });
const data = { schema: contentFilterSchema, category: 'program', topic: unknown, location: unknown, delivery: known('onsite'), audience: unknown, spaceKind: na, application: known({ deadlineKind: 'fixed', start: {value:'2020-01-01T10:00:00+09:00',precision:'minute'}, end: {value:'2099-10-15T18:00:00+09:00',precision:'minute'}, sourceStatus: 'unknown' }), schedule: na };
const selected = structuredClone(data); selected.topic = known('culture_experience'); selected.audience = known('other'); selected.location = known({ scope: 'specific', venues: [{ province: '41', district: '성남시', facility: '합성 교육장', address: '' }] });
eq(parseContentFilters(selected), selected);
const facts = { delivery_mode: 'offline', activity_region: 'unknown', venue: '원문 장소 안내', activity_evidence: ['원문 실제 근거'], residence: '성남시 주민', residence_scope: 'capital', residence_evidence: ['원문 참가 자격'] };
eq(factsFromFilterSelection(facts, data, selected, ['activity_region']).activity_region, 'capital');
eq(factsFromFilterSelection(facts, data, selected, []).activity_region, 'unknown');
eq(factsFromFilterSelection(facts, data, selected, ['activity_region']).venue, facts.venue);
eq(factsFromFilterSelection(facts, data, selected, ['activity_region']).activity_evidence, facts.activity_evidence);
eq(factsFromFilterSelection(facts, data, selected, ['activity_region']).residence, facts.residence);
for (const location of [unknown, known({ scope: 'nationwide', venues: [] }), known({ scope: 'specific', venues: [{ province: '', district: null, facility: '', address: '' }] })]) {
  eq(factsFromFilterSelection(facts, data, { ...selected, location }, ['activity_region']).activity_region, 'unknown');
}
const online = { ...selected, delivery: known('online'), location: na };
const onlineFacts = factsFromFilterSelection(facts, data, online, ['delivery_mode', 'activity_region']);
eq(onlineFacts.delivery_mode, 'online'); eq(onlineFacts.activity_region, 'unknown'); eq(onlineFacts.residence_evidence, facts.residence_evidence);
eq(factsFromFilterSelection(facts, online, { ...selected, delivery: known('mixed') }, ['delivery_mode', 'activity_region']).delivery_mode, 'mixed');
eq(factsFromFilterSelection(facts, online, selected, ['delivery_mode']).delivery_mode, 'offline');
eq(factsFromFilterSelection(facts, data, { ...data, delivery: unknown }, ['delivery_mode']).delivery_mode, 'unknown');
const info = { schema: contentFilterSchema, revision: 'a'.repeat(64), filterVersion: 1, data, missing: ['topic', 'location', 'audience'], origins: {} };
eq(myseoulFilterFields(info, ['activity_region']), ['topic', 'audience', 'location']);
eq(myseoulFilterFields(info, ['delivery_mode']), ['topic', 'delivery', 'audience', 'location']);
const event = { ...data, category: 'event', delivery: na, audience: na, application: na, schedule: unknown };
eq(myseoulFilterFields({ ...info, data: event, missing: ['topic', 'location', 'schedule'] }, []), ['topic', 'location', 'schedule']);
const derived = { ...data, delivery: known('mixed') };
eq(mergeMySeoulFilters(data, selected, derived).delivery, known('mixed'));
eq(mergeMySeoulFilters(data, selected, derived).location, selected.location);
eq(mergeMySeoulFilters(data, selected, event), selected);
assertMySeoulFilterContinuation({ revision: info.revision, category: 'program' }, { revision: info.revision, status: 'open', filterInfo: info }); checks++;
for (const change of [{ revision: 'b'.repeat(64) }, { status: 'resolved' }, { filterInfo: undefined }, { filterInfo: { ...info, data: event } }]) fails(() => assertMySeoulFilterContinuation({ revision: info.revision, category: 'program' }, { revision: info.revision, status: 'open', filterInfo: info, ...change }));
const python = process.env.MACHIMOA_TEST_PYTHON;
if (!python) throw Error('Explicit synthetic fixture Python required');
const samples = JSON.parse(execFileSync(python, ['-X', 'utf8', 'test_myseoul_db.py', '--fixtures'], { cwd: path.join(root, 'scripts'), encoding: 'utf8' }));
const f = structuredClone(samples.fixtures[0].item.myseoul_facts), id = '40000000-0000-4000-8000-000000000901';
f.delivery_mode = 'offline'; f.activity_region = 'unknown';
const reasons = ['activity_region_unknown', 'online_residence_unknown'];
const initial = myseoulItem({ id, revision: f.source_revision, version: 'b'.repeat(64), schema: f.schema_version, profile: 'myseoul-program-v1-local', factsVersion: 1,
  source: { name: 'myseoul_program', title: '합성 사실 검토', url: f.official_url, body: f.description }, facts: f, observedFacts: structuredClone(f), result: { ...samples.fixtures[0].expected, decision: 'review_required', disposition: 'observe_only', reasons }, status: 'open', aiStatus: 'blocked', editableFields: [...new Set(reasons.flatMap(myseoulReasonFields))], history: [], filterInfo: { ...info, revision: f.source_revision } }, id);
const originalFetch = globalThis.fetch;
globalThis.fetch = async () => { throw Error('External network forbidden'); };
const nodes = tree => [tree, ...React.Children.toArray(tree?.props?.children).flatMap(child => typeof child === 'object' ? nodes(child) : [])];
const text = tree => typeof tree === 'string' || typeof tree === 'number' ? String(tree) : React.Children.toArray(tree?.props?.children).map(text).join('');
const render = () => { cursor = 0; refCursor = 0; return Panel({ id, onBlocked() {}, onResult() {} }); };
const button = label => { const node = nodes(render()).find(n => n?.type === 'button' && text(n) === label); assert.ok(node, label); return node; };
const reset = () => { states = [structuredClone(initial), structuredClone(initial.facts), structuredClone(data), false, 0, '', '', false]; refs = []; };
const response = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const settle = () => new Promise(resolve => setImmediate(resolve));
let calls = [], mode = 'ok', server;
function fakeServer() {
  server = structuredClone(initial); calls = [];
  globalThis.fetch = async (url, options = {}) => {
    assert.ok(url === `/api/admin/myseoul-review/${id}` || url === `/api/admin/review-filters/${id}`);
    eq(options.cache, 'no-store'); eq(options.credentials, 'same-origin');
    const body = options.body ? JSON.parse(options.body) : null; calls.push({ url, body });
    if (url.includes('review-filters')) {
      if (mode === 'conflict') return response({ code: 'conflict' }, 409);
      if (mode === 'filter_unknown') throw Error('Synthetic response unknown');
      eq(body.version, server.version); eq(body.filterVersion, server.filterInfo.filterVersion);
      server.version = 'd'.repeat(64); server.filterInfo = { ...server.filterInfo, data: body.data, filterVersion: server.filterInfo.filterVersion + 1, missing: [] };
      return response({ item: { ...server.filterInfo, id, version: server.version, editable: true } });
    }
    if (body) {
      if (mode === 'facts_fail') return response({ code: 'conflict' }, 409);
      if (mode === 'facts_unknown') throw Error('Synthetic response unknown');
      eq(body.action, 'save_facts'); eq(body.version, server.version);
      server.facts = { ...server.facts, ...body.patch }; server.version = 'c'.repeat(64); server.factsVersion++;
      if(body.patch.public_category==='event') server.filterInfo={...server.filterInfo,data:event,missing:['topic','location','schedule']};
      if (mode === 'revision_changed') { server.revision = 'e'.repeat(64); server.facts.source_revision = server.revision; server.observedFacts.source_revision = server.revision; server.filterInfo.revision = server.revision; }
      if (mode === 'category_changed') server.filterInfo.data = event;
      if (mode === 'double_submit') await new Promise(resolve => setImmediate(resolve));
      return response({ mode: 'database', item: server });
    }
    if (mode === 'read_fail') throw Error('Synthetic read failed');
    return response({ mode: 'database', item: server });
  };
}
const choose = value => nodes(render()).find(n => n?.type?.name === 'FilterInputs').props.onChange(value);
try {
  reset(); const siblings=nodes(render()).filter(n=>['FilterInputs','SavedFilterValues'].includes(n.type?.name));eq(new Set(siblings.map(n=>n.key)).size,siblings.length);
  // Actual shared inputs: disabled placeholders, optional address and exact
  // times, opt-in reception state and category-specific labels.
  const inputs = (d, fields, change=()=>{}) => FilterInputs({data:d,fields,onChange:change,disabled:false});
  for (const d of [data,event,{...event,category:'youth_space',topic:na,schedule:na,spaceKind:unknown}]) {
    const tree=inputs(d,filterReviewFields({...info,data:d,missing:Object.keys(d).filter(k=>d[k]?.status==='unknown')}));
    for(const option of nodes(tree).filter(n=>n?.type==='option')) { ok(text(option)!=='미확인');if(option.props.value==='')eq(option.props.disabled,true); }
  }
  eq(reviewFilterLabel(data,'location'),'개최 지역');eq(reviewFilterLabel({...data,category:'youth_space'},'location'),'소재 지역');
  let changed;
  const sparse={...selected,location:known({scope:'specific',venues:[{province:'41',district:null,facility:'',address:''}]})};
  eq(parseContentFilters(sparse),sparse);
  const sparseTree=inputs(sparse,['location'],d=>changed=d);
  const optional=nodes(sparseTree).filter(n=>n?.type==='input');eq(optional.length,0);for(const input of optional)ok(!input.props.required);
  const deliveryTree=inputs(data,['delivery']);ok(text(deliveryTree).includes('오프라인'));ok(!text(deliveryTree).includes('현장'));
  let appTree=inputs(data,['application'],d=>changed=d);
  const statusNode=nodes(appTree).find(n=>n?.type?.name==='ReceptionStatus');
  states=[];cursor=0;let statusTree=statusNode.type(statusNode.props);ok(!nodes(statusTree).some(n=>n?.type==='select'));
  nodes(statusTree).find(n=>n?.type==='input').props.onChange({target:{checked:true}});cursor=0;statusTree=statusNode.type(statusNode.props);
  ok(nodes(statusTree).some(n=>n?.type==='select'));eq(nodes(statusTree).find(n=>n?.type==='select').props.required,true);eq(changed,undefined);
  nodes(statusTree).find(n=>n?.type==='select').props.onChange({target:{value:'closed'}});eq(changed.application.value.sourceStatus,'closed');
  appTree=inputs(changed,['application'],d=>changed=d);const savedStatus=nodes(appTree).find(n=>n?.type?.name==='ReceptionStatus');
  states=[];cursor=0;statusTree=savedStatus.type(savedStatus.props);eq(nodes(statusTree).find(n=>n?.type==='input').props.checked,true);
  nodes(statusTree).find(n=>n?.type==='input').props.onChange({target:{checked:false}});eq(changed.application.value.sourceStatus,'unknown');eq(changed.application.value.deadlineKind,'fixed');
  const dated={...selected,application:known({deadlineKind:'fixed',start:{value:'2026-10-01',precision:'day'},end:{value:'2026-10-10',precision:'day'},sourceStatus:'unknown'})};
  const endNode=nodes(inputs(dated,['application'],d=>changed=d)).find(n=>n?.type?.name==='EndpointInput'&&n.props.label==='신청 마감일 (필수)');
  let endTree=endNode.type(endNode.props);ok(!text(endTree).includes('정밀도'));
  nodes(endTree).find(n=>n?.type==='input'&&n.props.type==='checkbox').props.onChange({target:{checked:true}});
  fails(()=>parseContentFilters(changed)); // no invented midnight/time
  const incomplete=nodes(inputs(changed,['application'],d=>changed=d)).find(n=>n?.type?.name==='EndpointInput'&&n.props.label==='신청 마감일 (필수)');
  endTree=incomplete.type(incomplete.props);nodes(endTree).find(n=>n?.type==='input'&&n.props.type==='time').props.onChange({target:{value:'18:00'}});
  eq(changed.application.value.end,{value:'2026-10-10T18:00:00+09:00',precision:'minute'});eq(parseContentFilters(changed),changed);
  const timed=nodes(inputs(changed,['application'],d=>changed=d)).find(n=>n?.type?.name==='EndpointInput'&&n.props.label==='신청 마감일 (필수)');
  nodes(timed.type(timed.props)).find(n=>n?.type==='input'&&n.props.type==='checkbox').props.onChange({target:{checked:false}});eq(changed.application.value.end,dated.application.value.end);
  const seconds={...dated,application:known({...dated.application.value,end:{value:'2026-10-10T18:00:31+09:00',precision:'second'}})};
  const secondNode=nodes(inputs(seconds,['application'],d=>changed=d)).find(n=>n?.type?.name==='EndpointInput'&&n.props.label==='신청 마감일 (필수)');
  eq(nodes(secondNode.type(secondNode.props)).find(n=>n?.type==='input'&&n.props.type==='time').props.value,'18:00:31');
  reset();mode='ok';fakeServer();states[0].editableFields.push('public_category');states[1].public_category='event';
  button('사실 저장 후 공개 필터 저장').props.onClick();await settle();eq(calls.length,0);ok(states[5].includes('카테고리'));
  nodes(render()).find(n=>n?.type==='form').props.onSubmit({preventDefault(){}});await settle();eq(calls.length,1);eq(states[2].category,'event');eq(states[3],false);
  reset();ok(nodes(render()).some(n=>n?.type?.name==='ClassificationPanel'));ok(!text(render()).includes('확정된 My서울 카테고리의 재분류를 지원하지 않습니다.'));
  reset(); fakeServer(); choose(selected);
  eq(states[1].activity_region, 'capital'); eq(states[1].activity_evidence, initial.facts.activity_evidence);
  button('사실 저장 후 공개 필터 저장').props.onClick(); await settle();
  eq(calls.map(c => c.body?.action ?? (c.body ? 'filters' : 'read')), ['save_facts', 'filters', 'read']);
  ok(states[6].includes('각각 완료')); eq(states[2], server.filterInfo.data);
  // Explicit unchanged venue confirmation must still submit the protected trio.
  reset(); mode='ok'; fakeServer();states[0].facts.activity_region='capital';states[1].activity_region='capital';states[0].filterInfo.data=structuredClone(selected);states[2]=structuredClone(selected);
  button('공개 필터 확인·저장').props.onClick();await settle();eq(calls.map(c=>c.body?.action??(c.body?'filters':'read')),['save_facts','filters','read']);
  eq(Object.keys(calls[0].body.patch).sort(),['activity_region','delivery_mode','venue']);eq(calls[0].body.patch.venue,initial.facts.venue);
  for (mode of ['facts_fail', 'facts_unknown', 'revision_changed', 'category_changed', 'conflict', 'filter_unknown']) {
    reset(); fakeServer(); choose(selected); button('사실 저장 후 공개 필터 저장').props.onClick(); await settle();
    eq(calls.length, ['conflict', 'filter_unknown'].includes(mode) ? 2 : 1);
    ok(states[5].includes('입력')); eq(states[2].location, selected.location);
    eq(states[0].factsVersion, ['facts_fail', 'facts_unknown'].includes(mode) ? 1 : 2);
    const writes = calls.length;
    mode = 'ok'; button('입력을 유지하고 저장 상태 확인').props.onClick(); await settle();
    eq(calls.length, writes + 1); eq(calls.at(-1).body, null); eq(states[2].location, selected.location);
  }
  reset(); mode = 'ok'; fakeServer(); choose({ ...selected, location: known({ scope: 'specific', venues: [{ province: '', district: null, facility: '', address: '' }] }) });
  button('공개 필터 확인·저장').props.onClick(); await settle(); eq(calls.length, 0); ok(states[5].includes('아무 값도 저장하지'));
  reset(); mode = 'double_submit'; fakeServer(); choose(selected); const submit = button('사실 저장 후 공개 필터 저장'); submit.props.onClick(); submit.props.onClick(); await settle(); await settle(); eq(calls.filter(c => c.body?.action === 'save_facts').length, 1);
  reset(); mode = 'read_fail'; fakeServer(); choose(selected); button('사실 저장 후 공개 필터 저장').props.onClick(); await settle();
  ok(states[5].includes('공개 필터 저장은 완료')); eq(states[0].filterInfo.filterVersion, 2); eq(states[2], selected);
  mode = 'ok'; button('입력을 유지하고 저장 상태 확인').props.onClick(); await settle(); eq(calls.filter(c => c.url.includes('review-filters')).length, 1);
  reset(); choose(selected); states[1].residence = '다른 항목의 미저장 조건'; button('공개 필터 입력 취소').props.onClick(); eq(states[1].activity_region, initial.facts.activity_region); eq(states[1].residence, '다른 항목의 미저장 조건'); eq(states[2], data);
  reset(); mode = 'ok'; fakeServer(); choose(online); eq(states[2].location, na); eq(states[1].residence, initial.facts.residence); ok(!JSON.stringify(states[2]).includes('residence'));
  // Scoped fact confirmation preserves independent selections and the repeat editor instance.
  reset(); mode = 'ok'; fakeServer(); choose(selected); states[3] = true;
  const form = nodes(render()).find(n => n?.type === 'form'); form.props.onSubmit({ preventDefault() {} }); await settle();
  eq(states[2].location, selected.location); eq(states[3], true); eq(states[4], 0);
  // Shared filter request rejects an ambiguous returned version or values.
  const body = filterSaveBody(initial.filterInfo, initial.version, selected, ['location']);
  await assert.rejects(saveFilterRequest(id, body, async () => response({ item: { ...initial.filterInfo, id, version: initial.version, editable: true } }))); checks++;
  eq(calls.filter(c => /ai|candidate|claim|publish/.test(c.url)).length, 0);
  // The actual parent supplies one stable source slot before either editor flow.
  reset();const categoryPanel=nodes(render()).find(n=>n?.type?.name==='ClassificationPanel');
  ok(text(categoryPanel.props.reference).includes(initial.source.body));ok(text(categoryPanel.props.overview).includes('이번에 확인할 사항'));
  eq(nodes(render()).filter(n=>n?.type==='details'&&text(n).includes('원문 확인 · 읽기 전용')).length,0);
  // Only the affected reservation UI composition is exercised; its server suite is unchanged.
  const programSamples=JSON.parse(execFileSync(python,['-X','utf8','test_program_db.py','--fixtures'],{cwd:path.join(root,'scripts'),encoding:'utf8'}));
  const programFacts=programSamples.fixtures[0].item.program_facts;
  const {programItem}=load('app/lib/review/program-store.ts');
  const reservation=programItem({id,revision:'a'.repeat(64),version:'b'.repeat(64),schema:'program-scope-v1-local',profile:'program_capital_v1_local',factsVersion:1,source:{name:'seoul_reservation',title:'합성 예약',url:programFacts.official_url,body:'합성 예약 원문'},facts:programFacts,observedFacts:programFacts,result:{decision:'review_required',disposition:'observe_only',reasons:['activity_location_unknown']},status:'open',aiStatus:'blocked',editableFields:['activity_region'],history:[]},id);
  const ReservationPanel=load('app/components/admin/ProgramReviewPanel.tsx').default;
  states=[reservation,structuredClone(reservation.facts)];refs=[];cursor=0;refCursor=0;
  const reservationTree=ReservationPanel({id,onBlocked(){},onResult(){}});
  const reservationCategory=nodes(reservationTree).find(n=>n?.type?.name==='ClassificationPanel');
  ok(text(reservationCategory.props.reference).includes('합성 예약 원문'));ok(text(reservationCategory.props.overview).includes('이번에 확인할 사항'));
  eq(nodes(reservationTree).filter(n=>n?.type==='details'&&text(n).includes('원문 확인 · 읽기 전용')).length,0);
  console.log(JSON.stringify({ syntheticOnly: true, actualPostgreSQL: false, checks, result: 'passed', externalConnections: 0 }));
} finally { globalThis.fetch = originalFetch; }
