// Browser exercises the real PC controls with an isolated browser context and intercepted requests.
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,readFileSync,rmSync,existsSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {createRequire,registerHooks} from 'node:module';
import {IncomingMessage} from 'node:http';
import {Socket} from 'node:net';

import {pathToFileURL} from 'node:url';
import ts from 'typescript';
const require=createRequire(import.meta.url);
const {NodeNextRequest}=require('next/dist/server/base-http/node');
const {NextRequestAdapter}=require('next/dist/server/web/spec-extension/adapters/next-request');
function nextPost(url,headers,payload) {
 const raw=new IncomingMessage(new Socket());
 raw.url=String(url);raw.method='POST';raw.headers=headers;
 if(payload?.length)raw.push(Buffer.from(payload));
 raw.push(null);
 return NextRequestAdapter.fromNodeNextRequest(new NodeNextRequest(raw),new AbortController().signal);
}
const {webpack}=require('next/dist/compiled/webpack/bundle5')();
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
const dir=mkdtempSync(join(resolve('.'),'suitability-ui-test-'));
let browser;
try {
 const loader=join(dir,'loader.cjs'),entry=join(dir,'entry.cjs');
 writeFileSync(loader,'const ts=require('+JSON.stringify(require.resolve('typescript'))+');module.exports=function(src){return ts.transpileModule(src,{fileName:this.resourcePath,compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText}');
 writeFileSync(entry,`const React=require('react');const {createRoot}=require('react-dom/client');const P=require('@/app/components/admin/PcWorkerPanel');createRoot(document.getElementById('root')).render(React.createElement(P.PcWorkerProvider,null,React.createElement(P.default)));`);
 await new Promise((ok,fail)=>webpack({mode:'development',entry,devtool:false,output:{path:dir,filename:'app.js'},
  resolve:{modules:[resolve('node_modules'),'node_modules'],extensions:['.tsx','.ts','.js','.json'],alias:{'@':resolve('.')}},
  module:{rules:[{test:/\.tsx?$/,use:loader},{test:/\.css$/,type:'asset/source'}]}
 },(err,stats)=>err||stats?.hasErrors()?fail(err||Error(stats.toString({all:false,errors:true}))):ok()));
 registerHooks({resolve(name,ctx,next){try{return next(name,ctx);}catch(error){if(name.startsWith('.')&&!/\.[a-z]+$/i.test(name))return next(name+'.ts',ctx);throw error;}},
 load(url,ctx,next){if(url.startsWith('file:')&&url.endsWith('.ts'))return {format:'module',shortCircuit:true,
  source:ts.transpileModule(readFileSync(new URL(url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText};return next(url,ctx);}});
 const {suitabilityRequest}=await import('../app/lib/review/suitability.ts');
 const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
 const origin='http://localhost:31979',instance=crypto.randomUUID(),challenge=crypto.randomUUID(),actor=crypto.randomUUID();
 const catalog=JSON.parse(readFileSync('app/lib/pc-worker/sources.json')).map(s=>[s.id,s.collector,s.ai].join(':')).join('|');
 const rows=['exclude','check','keep','keep'].map((group,i)=>({id:crypto.randomUUID(),source:i%2?'myseoul_program':'seoul_reservation',
  key:'TEST-'+i,queue:i%2?'ai':'facts',title:['합성 장식품 만들기','합성 공원 안내','합성 성곽 해설','합성 생활 수선'][i],
  state:'done',moved:false,reused:false,decision:{group,clause:group==='keep'?'K02':group==='check'?'확인 필요':'E01',
    quote:'합성 원문의 활동 문구',reason:'원문 활동을 기준으로 검토했습니다.',question:group==='check'?'프로그램에 지역 해설이 포함되나요?':'',note:''}}));
 let run=null,report=null,requestId,command,calls=0,moves=[],lose=false;
 let skipItem=rows[1].id, failItem, interruptItem, loseBeforeSave;
 const attempted=[];
 const output=()=>({busy:false,run});
 const deps={authorize:async()=>({userId:actor}),client:()=>({rpc:async(name,args)=>{
   if(name==='suitability_report') return {data:report,error:null};
   assert.equal(name,'suitability_exclude');assert.equal(args.p_actor,actor);assert.equal(args.p_run,report.id);
   moves.push(args.p_item);
   const row=rows.find(item=>item.id===args.p_item);
   if(row.id===skipItem)return {data:'skipped',error:null};
   if(row.id===failItem)return {data:null,error:{code:'PT422'}};
   row.moved=true;return {data:'moved',error:null};
 }})};
 const denied=await suitabilityRequest(new Request(origin+'/api/admin/suitability'),{authorize:async()=>{throw new AdminAccessError('forbidden');},client:()=>assert.fail()});
 assert.equal(denied.status,403);
 const cross=await suitabilityRequest(new Request(origin+'/api/admin/suitability',{method:'POST',headers:{origin:'https://unrelated.invalid'}}),deps);
 assert.equal(cross.status,403);
 const moveUrl=new URL('/api/admin/suitability',origin);
 for(const name of ['run','item','request'])moveUrl.searchParams.set(name,crypto.randomUUID());
 let writes=0;
 const streamDeps={...deps,client:()=>({rpc:async()=>{writes++;return {data:'moved',error:null};}})};
 for(const headers of [{origin},{origin,'content-length':'0'}]){
   const incoming=nextPost(moveUrl,headers);
   assert.ok(incoming.body);
   assert.equal((await suitabilityRequest(incoming,streamDeps)).status,200,'empty Node POST must reach RPC');
 }
 for(const headers of [{origin},{origin,'content-length':'0'},{origin,'content-length':'1'}]){
   assert.equal((await suitabilityRequest(nextPost(moveUrl,headers,' '),streamDeps)).status,422);
 }
 assert.equal(writes,2,'nonempty requests must never reach RPC');
 for(const [code,expected] of [['PT422','failed'],['PT409','skipped'],['08006','unknown']]){
   const url=new URL('/api/admin/suitability',origin);
   for(const name of ['run','item','request'])url.searchParams.set(name,crypto.randomUUID());
   const reply=await suitabilityRequest(new Request(url,{method:'POST',headers:{origin}}),
     {...deps,client:()=>({rpc:async()=>({data:null,error:{code}})})});
   if(expected==='unknown')assert.equal(reply.status,503);else assert.equal((await reply.json()).result,expected);
 }
 browser=await chromium.launch({executablePath:process.env.CHROME_PATH,headless:true});
 const page=await browser.newPage({viewport:{width:1050,height:880},serviceWorkers:'block'});
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url());
  const json=data=>route.fulfill({json:data});
  if(url.origin===origin && url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<meta charset=utf-8><title>로컬 합성 시험</title><div id=root></div><script src=/app.js></script>'});
  if(url.origin===origin && url.pathname==='/app.js')return route.fulfill({path:join(dir,'app.js'),contentType:'text/javascript'});
  if(url.origin===origin && url.pathname==='/api/admin/pc-worker'){
   const grant=req.postDataJSON();command=grant.command;requestId=grant.requestId;return json({ticket:'synthetic-admin-ticket'});}
  if(url.origin==='http://127.0.0.1:14621'){
   if(url.pathname==='/hello')return json({instance,challenge,schema:'machimoa-pc-worker-v3',catalog,project:'a'.repeat(20)});
   if(url.pathname==='/connect')return json({token:'a'.repeat(40),instance});
   if(url.pathname==='/status')return json(output());
   if(url.pathname==='/run'){assert.deepEqual(command,{kind:'suitability',source:'all',limit:'all'});calls++;
    run={requestId,command,state:'completed',code:'completed',counts:{classified:4}};
    report={id:requestId,policy:'1.0',readAt:'2026-11-25T00:00:00Z',items:rows};return json(output());}
  }
  if(url.origin===origin && url.pathname==='/api/admin/suitability'){
   let incoming=new Request(req.url());
   if(req.method()==='POST') {
    const item=url.searchParams.get('item');
    attempted.push(item);
    if(item===loseBeforeSave)return route.abort();
    incoming=nextPost(req.url(),req.headers(),item===interruptItem?'x':req.postDataBuffer());
   }
   const resp=await suitabilityRequest(incoming,deps);
   if(lose && req.method()==='POST'){lose=false;return route.abort();}
   return route.fulfill({status:resp.status,body:await resp.text(),contentType:'application/json'});
  }
  return route.abort();
 });
 await page.goto(origin);
 const screenshot=process.env.SUITABILITY_PREVIEW;
 if(screenshot){
  const css=await require('postcss')([require('@tailwindcss/postcss')({base:resolve('.'),optimize:false})])
    .process(readFileSync('app/globals.css','utf8'),{from:resolve('app/globals.css')});
  await page.addStyleTag({content:css.css+' main,#root{max-width:960px;margin:auto;padding:12px 18px;}'});
 }
 await page.getByRole('button',{name:'PC 연결',exact:true}).click();
 const start=page.getByRole('button',{name:'미판정 콘텐츠 적합성 점검'});
 await start.dblclick();
 await page.getByRole('heading',{name:'제외 권장 1건'}).waitFor();
 if(screenshot)await page.getByRole('region',{name:'콘텐츠 적합성 점검'}).screenshot({path:join(screenshot,'결과.png')});
 assert.equal(calls,1);assert.equal(await page.locator('input:checked').count(),0);
 for(const i of [0,1])await page.getByRole('checkbox',{name:rows[i].title}).check();
 await page.getByRole('button',{name:'선택한 2건 휴지통으로 이동'}).click();
 const confirm=page.getByRole('group',{name:'선택한 콘텐츠 제외 확인'});
 if(screenshot){
   await page.getByRole('region',{name:'콘텐츠 적합성 점검'}).screenshot({path:join(screenshot,'선택확인.png')});
 }
 assert.ok((await confirm.innerText()).includes(rows[0].title));assert.ok(!(await confirm.innerText()).includes(rows[2].title));
 await confirm.getByRole('button',{name:'확인하고 이동'}).click();
 const summary=page.getByRole('status').filter({hasText:'최근 이동 요청'});
 await summary.filter({hasText:'이동 성공 1건 · 실패 0건 · 미처리 0건 · 상태·버전 변경으로 건너뜀 1건'}).waitFor();
 assert.deepEqual(moves,[rows[0].id,rows[1].id]);
 for(const i of [2,3])await page.getByRole('checkbox',{name:rows[i].title}).check();
 await page.getByRole('button',{name:'선택한 2건 휴지통으로 이동'}).click();
 lose=true;await page.getByRole('button',{name:'확인하고 이동'}).click();
 await page.getByRole('heading',{name:'적합 제안 1건'}).waitFor();
 assert.deepEqual(moves,[rows[0].id,rows[1].id,rows[2].id]);assert.equal(rows[3].moved,false);
 await summary.filter({hasText:'이동 성공 1건 · 실패 0건 · 미처리 1건'}).waitFor();
 const box=i=>page.getByRole('checkbox',{name:rows[i].title});
 assert.equal(await box(2).count(),0);
 assert.equal(await box(3).isChecked(),true);
 await page.reload();
 await page.getByRole('heading',{name:'적합 제안 1건'}).waitFor();
 assert.equal(await box(0).count(),0);
 assert.equal(await box(2).count(),0);
 assert.equal(calls,1);assert.equal(await page.locator('input:checked').count(),0);
 async function resetSelection(){
   for(const row of rows)row.moved=false;
   skipItem=failItem=interruptItem=loseBeforeSave=undefined;
   moves=[];attempted.length=0;
   await page.reload();
   for(const i of [0,1,2])await box(i).check();
 }
 async function confirmMove(n){
   await page.getByRole('button',{name:'선택한 '+n+'건 휴지통으로 이동'}).click();
   await confirm.getByRole('button',{name:'확인하고 이동'}).click();
 }
 const ids=rows.map(row=>row.id);
 await resetSelection();
 await confirmMove(3);
 await summary.filter({hasText:'이동 성공 3건 · 실패 0건 · 미처리 0건'}).waitFor();
 assert.deepEqual(moves,ids.slice(0,3));
 assert.deepEqual(attempted,moves);
 assert.equal(await page.locator('input:checked').count(),0);
 assert.equal(rows[3].moved,false);
 assert.equal(await page.getByRole('heading',{name:/제외 권장/}).count(),0);
 assert.equal(await page.getByRole('checkbox').filter({visible:true}).count(),1);
 await box(3).check();
 await confirmMove(1);
 await page.getByText('남은 점검 항목이 없습니다.').waitFor();
 await summary.filter({hasText:'이동 성공 1건 · 실패 0건 · 미처리 0건'}).waitFor();
 assert.deepEqual(moves,ids);

 await resetSelection();interruptItem=ids[1];
 await confirmMove(3);
 await summary.filter({hasText:'이동 성공 1건 · 실패 1건 · 미처리 1건'}).waitFor();
 assert.deepEqual(attempted,ids.slice(0,2));assert.deepEqual(moves,[ids[0]]);
 for(const i of [1,2]){assert.ok(await box(i).isChecked());assert.ok(await box(i).isEnabled());}
 assert.equal(await box(0).count(),0);
 await page.getByRole('button',{name:'점검 결과 다시 확인'}).click();
 interruptItem=undefined;
 await confirmMove(2);
 await summary.filter({hasText:'이동 성공 2건 · 실패 0건 · 미처리 0건'}).waitFor();
 assert.deepEqual(moves,ids.slice(0,3));assert.deepEqual(attempted,[ids[0],ids[1],ids[1],ids[2]]);

 await resetSelection();failItem=ids[1];
 await confirmMove(3);
 await summary.filter({hasText:'이동 성공 2건 · 실패 1건 · 미처리 0건'}).waitFor();
 assert.deepEqual(moves,ids.slice(0,3));assert.ok(await box(1).isChecked());assert.ok(await box(1).isEnabled());
 assert.equal(await page.locator('input:checked').count(),1);

 await resetSelection();loseBeforeSave=ids[1];
 await confirmMove(3);
 await summary.filter({hasText:'이동 성공 1건 · 실패 0건 · 미처리 1건 · 결과 불명 1건'}).waitFor();
 assert.ok(await box(1).isDisabled());assert.ok(await box(2).isChecked());assert.ok(await box(2).isEnabled());
 assert.deepEqual(attempted,ids.slice(0,2));assert.deepEqual(moves,[ids[0]]);
 assert.equal(calls,1);
 console.log('PASS empty and nonempty Node POST, fake auth, multi-select success, 422 stop and explicit retry, item-level failure, version skip, lost responses before/after save, counts and retained selections');
} finally {if(browser)await browser.close();if(existsSync(dir))rmSync(dir,{recursive:true});}
