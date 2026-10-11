// Actual worker output -> real DTO/save handler -> candidate editor/public body.
// Synthetic data, injected RPC, no external fetch/auth/database/provider.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {registerHooks} from 'node:module';
import {readFileSync} from 'node:fs';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';

const root=fileURLToPath(new URL('../',import.meta.url));
const uiRoot=process.env.MACHIMOA_APPROVED_UI_ROOT || root;
registerHooks({
  resolve(specifier,context,next) {
    if(specifier.startsWith('@/')) {
      const base=context.parentURL?.startsWith(pathToFileURL(uiRoot).href)?uiRoot:root;
      specifier=pathToFileURL(path.join(base,specifier.slice(2))).href;
    }
    try{return next(specifier,context);}catch(error){
      if(specifier.startsWith('.')||specifier.startsWith('file:'))
        for(const ext of ['.ts','.tsx'])try{return next(specifier+ext,context);}catch{}
      throw error;
    }
  },
  load(url,context,next) {
    if(url.endsWith('.tsx'))return {format:'module',shortCircuit:true,
      source:ts.transpileModule(readFileSync(fileURLToPath(url),'utf8'),
        {compilerOptions:{module:ts.ModuleKind.ESNext,jsx:ts.JsxEmit.ReactJSX}}).outputText};
    return next(url,context);
  }
});
globalThis.fetch=()=>{throw Error('network forbidden');};
const python=process.env.MACHIMOA_TEST_PYTHON;
assert.ok(python,'Explicit test Python required');
const fixture=process.argv.includes('--actual-summary')
  ? 'test_myseoul_schedule_table_continuity.py' : 'test_body_markdown_pipeline.py';
const packet=JSON.parse(execFileSync(python,['-X','utf8',fixture,'--fixture'],
  {cwd:path.join(root,'scripts'),encoding:'utf8'}));
assert.equal(packet.syntheticOnly,true);
const content=Object.fromEntries(Object.entries(packet.output).filter(([key])=>key!=='aiModel').map(([key,value])=>[key,value.trim()]));
const {databaseItem}=await import('../app/lib/review/database-dto.ts');
const {LocalReviewStore}=await import('../app/lib/review/local-fixture.ts');
const {DatabaseReviewStore}=await import('../app/lib/review/database-store.ts');
const {reviewDetail}=await import('../app/lib/review/handlers.ts');
const {CandidateEditor}=await import('../app/components/admin/ReviewEditors.tsx');
const {default:CurationBody}=await import(pathToFileURL(path.join(uiRoot,'app/components/CurationBody.tsx')).href);
const id='20000000-0000-4000-8000-000000000001',actor='00000000-0000-4000-8000-000000000001';
const base=await new LocalReviewStore().get('candidates',id);
const candidate={...base,source:{...base.source,name:'myseoul_program',body:packet.source},content,
  version:'c'.repeat(64),programInfo:{inputFactsVersion:2,currentFactsVersion:2,inputChanged:false,
    canPublish:false,applicationPeriod:'2026-10-01 ~ 2026-10-02',operatingPeriod:'2026-10-03 ~ 2026-10-10'}};
const projected=databaseItem(candidate,'candidates',id);
assert.deepEqual(projected.content,content);
const calls=[];
const store=new DatabaseReviewStore({rpc:async(name,args)=>{
  calls.push({name,args});
  if(name==='admin_myseoul_candidate_notice_input')return {data:null,error:null};
  assert.equal(name,'admin_review_save_candidate');
  assert.equal(args.p_actor,actor);
  assert.equal(args.p_version,candidate.version);
  assert.equal(args.p_revision,candidate.revision);
  assert.deepEqual(args.p_content,content);
  return {data:candidate,error:null};
}});
const response=await reviewDetail(new Request(`http://localhost/api/admin/review/candidates/${id}`,{
  method:'POST',headers:{origin:'http://localhost','content-type':'application/json'},
  body:JSON.stringify({action:'save_candidate',revision:candidate.revision,version:candidate.version,content})
}),'candidates',id,{authorize:async()=>({userId:actor}),store:()=>store});
assert.equal(response.status,200);
assert.ok(response.headers.get('cache-control').includes('no-store'));
assert.deepEqual((await response.json()).item.content,content);
assert.equal(calls.filter(c=>c.name==='admin_review_save_candidate').length,1);
const editor=renderToStaticMarkup(createElement(CandidateEditor,{value:content,onChange:()=>{},errors:{},disabled:false}));
assert.ok(editor.includes(content.contentKo));
assert.ok(editor.includes(content.contentJa));
assert.ok(editor.includes('한국어 상세')&&editor.includes('일본어 상세'));
for(const [locale,body] of [['ko',content.contentKo],['ja',content.contentJa]]){
  const html=renderToStaticMarkup(createElement(CurationBody,{content:body,locale}));
  assert.equal((html.match(/<section/g)||[]).length,5);
  assert.equal((html.match(/<table/g)||[]).length,1);
  assert.equal((html.match(/<tbody>/g)||[]).length,1);
  assert.ok(html.includes('<ol')&&html.includes('<ul')&&html.includes('<strong'));
  assert.ok(html.includes('href="https://synthetic.invalid/apply?id=1"'));
  assert.ok(html.includes('10,000')&&html.includes('2,000'));
  assert.ok(!html.includes('[일정 안내]')&&!html.includes('[日程案内]'));
  if(process.argv.includes('--actual-summary')){
    // The former losing section, not just a table already in major content.
    const cells=html.indexOf('<table');
    assert.ok(cells>0&&cells<html.indexOf(locale==='ko'?'주요 내용':'主な内容'));
    assert.ok(html.includes(locale==='ko'?'문서 작성':'文書の作成'));
    assert.ok(html.includes(locale==='ko'?'문서 제출':'文書の提出'));
    assert.equal((html.match(new RegExp(locale==='ko'?'서울 합성 교육실':'ソウル合成教育室','g'))||[]).length,1);
  }
}
for(const body of ['일반 본문입니다.','[한 줄 요약]\n기존 요약\n[기간·상태]\n기존 일정\n[주요 내용]\n기존 설명']){
  const html=renderToStaticMarkup(createElement(CurationBody,{content:body,locale:'ko'}));
  assert.ok(html.includes('본문')||html.includes('기존 설명'));
}
console.log(JSON.stringify({mode:'synthetic',provider:'fake Pro stream',providerCalls:0,dbCalls:0,
  fakeGenerationStages:packet.calls,candidate:'real DTO/editor/save handler with fake RPC',
  publicUI:uiRoot,fixture,locales:['ko','ja'],tables:1,gitWrites:0}));
