// Synthetic components and real display functions only. No Auth, DB or AI connection.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {readFileSync} from 'node:fs';
import {fileURLToPath,pathToFileURL} from 'node:url';
import path from 'node:path';
import ts from 'typescript';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const root=fileURLToPath(new URL('../',import.meta.url));
registerHooks({resolve(s,c,next){
  if(s.startsWith('@/'))s=pathToFileURL(path.join(root,s.slice(2))).href;
  try{return next(s,c);}catch(e){if(s.startsWith('.')||s.startsWith('file:'))for(const ext of ['.ts','.tsx'])try{return next(s+ext,c);}catch{}throw e;}
},load(url,c,next){
  if(url.endsWith('.json'))return {format:'module',shortCircuit:true,source:`export default ${readFileSync(fileURLToPath(url),'utf8')};`};
  if(url.endsWith('.css'))return {format:'module',shortCircuit:true,source:'export default {};'};
  if(url.endsWith('.tsx'))return {format:'module',shortCircuit:true,source:ts.transpileModule(readFileSync(fileURLToPath(url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,jsx:ts.JsxEmit.ReactJSX}}).outputText};
  return next(url,c);
}});
globalThis.fetch=()=>{throw Error('network forbidden');};
const {candidatePeriodText:date,candidateSourceName:source}=await import('../app/lib/review/candidate-display.ts');
const {CandidateSource,CandidateRegistration,CandidateFilterAlert}=await import('../app/components/admin/CandidateReviewContext.tsx');
const {SeoulCandidateFindings}=await import('../app/components/admin/SeoulCandidateFindings.tsx');
const {focusCandidates,syntheticReview}=await import('./fixtures/candidate-review-focus.ts');
const items=focusCandidates();
let checks=0;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;},ok=value=>{assert.ok(value);checks++;};
const render=(C,props)=>renderToStaticMarkup(createElement(C,props));
eq(date('2026-11-28 ~ 2026-11-30'),'2026.11.28 ~ 2026.11.30');
eq(date('2026-11-18T01:30:00Z'),'2026.11.18 10:30:00 (한국 시간)');
eq(date('2026-11-18T10:30+09:00'),'2026.11.18 10:30 (한국 시간)');
eq(date('2026-11-18T10:30:12.123+09:00'),'2026.11.18 10:30:12.123 (한국 시간)');
eq(date('공식 안내 확인'),'공식 안내 확인');
eq(source('seoul_reservation'),'서울 공공서비스예약');eq(source('myseoul_program'),'My서울+');
eq(source('new_collector'),'수집원 이름 확인 필요');eq(source('공식 문화 안내'),'공식 문화 안내');
for(const item of items){
  const before=JSON.stringify(item),html=render(CandidateSource,{source:item.source});
  if(item.source.url){ok(html.indexOf('<a ')<html.indexOf('<details'));ok(html.includes('target="_blank"'));ok(html.includes('noopener noreferrer'));}
  else {ok(!html.includes('<a '));ok(!html.includes('border-'));}
  ok(!html.includes('<details open'));ok(html.includes(item.source.body.split('\n')[0]));
  const meta=render(CandidateRegistration,{item,local:true});
  eq((meta.match(/<details/g)??[]).length,1);ok(!meta.includes('open=""'));ok(meta.includes('등록 정보·변경 이력'));
  for(const text of ['신청 기간','운영 기간','현재 사실 버전','생성 당시 입력','후보 반영값','현재 확정값','가짜 RPC 저장 기록'])ok(meta.includes(text));
  eq(JSON.stringify(item),before);
}
eq(render(CandidateFilterAlert,{item:items[0]}),'');
const warning=render(CandidateFilterAlert,{item:items[2]});ok(warning.includes('진행 방식'));ok(warning.includes('게시할 수 없습니다'));ok(warning.includes('등록 정보·변경 이력에서 확인'));
const unknown=structuredClone(items[2]);unknown.filterInfo.current=structuredClone(unknown.filterInfo.approved);
ok(render(CandidateFilterAlert,{item:unknown}).includes('특정할 수 없습니다'));
const reference=render(SeoulCandidateFindings,{review:{source:'합성 원문',issues:syntheticReview.issues.filter(i=>i.disposition==='equivalent')},content:items[0].content});
ok(!reference.includes('수정 제안 0개'));ok(reference.includes('수정 불필요 · 참고 이력'));ok(!reference.includes('open=""'));
const active=render(SeoulCandidateFindings,{review:syntheticReview,content:items[0].content});ok(active.includes('AI 수정 제안'));ok(active.includes('근거 확인 필요'));
const workspace=readFileSync(new URL('../app/components/admin/ReviewWorkspace.tsx',import.meta.url),'utf8');
ok(workspace.indexOf('<CandidateRegistration')>workspace.indexOf('</form>'));
ok(workspace.indexOf('<CandidateFilterAlert')<workspace.indexOf('<CandidateEditor'));
ok(workspace.includes('!item.programInfo.canPublish'));ok(workspace.includes('!item.filterInfo.canPublish'));
ok(workspace.includes('fieldsDirty'));ok(workspace.includes('preconditions()'));
console.log(`Candidate review focus: ${checks} assertions passed (source access, precision, collapsed history, warnings, immutable data, save/publish wiring).`);
