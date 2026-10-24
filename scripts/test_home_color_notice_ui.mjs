// Actual workspace event handlers -> real admin handlers -> fake Auth/store.
// No browser cookies, real publication, image download, DB or AI.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire, syncBuiltinESMExports} from 'node:module';
import net from 'node:net';
import http from 'node:http';
import https from 'node:https';
import dns from 'node:dns/promises';
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
const root=path.resolve('.');
const deny=()=>{throw Error('real_network_forbidden');};
globalThis.fetch=deny;net.Socket.prototype.connect=deny;
http.request=http.get=https.request=https.get=dns.lookup=deny;syncBuiltinESMExports();
let states=[],refs=[],cursor=0,refCursor=0,effects=[],dependencies=[];
const fakeReact={...React,
 useState(initial){const i=cursor++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return [states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},
 useRef(initial){return refs[refCursor++]??={current:initial};},useCallback(fn){return fn;},
 useEffect(fn,deps){const i=cursor++;if(!dependencies[i]||deps.some((x,j)=>x!==dependencies[i][j])){dependencies[i]=deps;effects.push(fn);}}
};
const cache=new Map();
function load(relative){
 const filename=path.join(root,relative);if(cache.has(filename))return cache.get(filename);
 if(relative.startsWith('app/components/')&&!relative.endsWith('ReviewWorkspace.tsx')){
  const Stub=()=>null;return {default:Stub,CandidateEditor:Stub,FactsEditor:Stub,CandidateContentNotices:Stub,CandidateFilterComparison:Stub,candidateImageError:()=>'',fieldClass:'',primaryButton:'',secondaryButton:''};
 }
 const exports={};cache.set(filename,exports);
 const code=ts.transpileModule(fs.readFileSync(filename,'utf8'),{fileName:filename,compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
 new Function('require','exports',code)(s=>{
  if(s==='react')return fakeReact;if(s==='next/link')return {default:()=>null};
  if(s.startsWith('@/')||s.startsWith('.')){const file=s.startsWith('@/')?path.join(root,s.slice(2)):path.resolve(path.dirname(filename),s);for(const suffix of ['', '.ts','.tsx'])if(fs.existsSync(file+suffix)&&fs.statSync(file+suffix).isFile())return load(path.relative(root,file+suffix).replaceAll('\\','/'));}
  return require(s);
 },exports);return exports;
}
const Workspace=load('app/components/admin/ReviewWorkspace.tsx').default;
const {homeColorNotice}=load('app/lib/review/presentation.ts');
const {LocalReviewStore}=load('app/lib/review/local-fixture.ts');
const {reviewDetail,listReviews}=load('app/lib/review/handlers.ts');
const {AdminAccessError}=load('app/lib/auth/admin-policy.ts');
const actor='00000000-0000-4000-8000-000000000001',id='20000000-0000-4000-8000-000000000001';
const nodes=t=>[t,...React.Children.toArray(t?.props?.children).flatMap(c=>typeof c==='object'?nodes(c):[])];
const text=t=>typeof t==='string'||typeof t==='number'?String(t):React.Children.toArray(t?.props?.children).map(text).join('');
const flush=()=>new Promise(r=>setImmediate(r));
let store,posts=[],colorCalls=0,behavior,outcome,mode,release;
function render(){cursor=0;refCursor=0;effects=[];return Workspace();}
async function commit(){render();const todo=effects;effects=[];for(const effect of todo)effect();await flush();return render();}
function button(label){const b=nodes(render()).find(n=>n?.type==='button'&&text(n)===label);assert.ok(b,'missing button '+label);return b;}
function notice(){return nodes(render()).filter(n=>n?.type==='p'&&n.props.role==='status').map(text).join('\n');}
async function seed(nextOutcome,{responseMode='database',failure=''}={}){
 states=[];refs=[];dependencies=[];outcome=nextOutcome;behavior=failure;mode=responseMode;posts=[];colorCalls=0;store=new LocalReviewStore();
 globalThis.fetch=async(url,options={})=>{
  assert.match(url,/^\/api\/admin\/review(?:\?|\/)/);assert.equal(options.cache,'no-store');assert.equal(options.credentials,'same-origin');
  const parsed=new URL(url,'https://synthetic.invalid'),body=options.body?JSON.parse(options.body):null;
  if(body)posts.push(structuredClone(body));
  const request=new Request(parsed,{method:body?'POST':'GET',headers:{origin:parsed.origin,...options.headers},...(body?{body:options.body}:{})});
  const deps={authorize:async()=>{if(body&&behavior==='signed_out')throw new AdminAccessError('signed_out');return {userId:actor};},
   store:()=>({mode,list:(...a)=>store.list(...a),get:(...a)=>store.get(...a),execute:async(...a)=>{if(behavior==='delay')await new Promise(r=>release=r);return store.execute(...a);}}),
   onPublished:async()=>{colorCalls++;return outcome;}};
  if(body&&behavior==='unknown')throw Error('PRIVATE_RESPONSE');
  if(body&&behavior==='conflict')store.advanceRevision(id);
  const response=parsed.pathname==='/api/admin/review'?await listReviews(request,deps):await reviewDetail(request,'candidates',id,deps);
  if(body&&behavior==='missing'&&response.ok){const data=await response.json();delete data.homeColor;return Response.json(data);}
  return response;
 };
 await commit();button('AI 결과 후보 검토').props.onClick();await commit();
 const row=nodes(render()).find(n=>n?.type==='button'&&text(n).includes('후보 검토 대기'));
 assert.ok(row);await row.props.onClick();await flush();render();
}
let checks=0;const check=async(name,fn)=>{await fn();checks++;console.log('PASS '+name);};
async function publish(){button('승인하고 게시').props.onClick();render();const b=button('확인하고 게시');b.props.onClick();await flush();return render();}
for(const [value,phrase]of [['completed','배경색 분석을 완료했습니다.'],['completed_default','기본색(회청보라)을 적용했습니다.'],['failed','분석에 실패해'],['no_image','이미지가 없어'],['unchanged','기존 배경색 기록'],['unavailable','결과를 확인하지 못했습니다.']])await check('workspace publishes once and reports '+value,async()=>{
 await seed(value);const before=await store.get('candidates',id);await publish();
 assert.match(notice(),/승인·게시와 이력을 기록/);assert.ok(notice().includes(phrase));assert.equal(posts.length,1);assert.equal(colorCalls,1);
 assert.deepEqual(posts[0],{action:'publish',revision:before.revision,version:before.version});
 const after=await store.get('candidates',id);assert.equal(after.status,'published');assert.equal(after.history.length,1);assert.equal(after.history[0].actor,actor);
 assert.deepEqual(after.content,before.content);assert.deepEqual(after.source,before.source);assert.equal(after.revision,before.revision);
 assert.equal(nodes(render()).some(n=>n?.type==='button'&&text(n)==='승인하고 게시'),false);
 await commit();assert.equal(posts.length,1);assert.equal(colorCalls,1);
});
await check('missing/unknown/malformed result never claims successful analysis or echoes data',async()=>{
 for(const value of [undefined,null,'NEW_STATUS',{token:'PRIVATE'},'https://private.invalid/secret']){
  assert.match(homeColorNotice(value),/결과를 확인하지 못했습니다/);assert(!homeColorNotice(value).includes('PRIVATE'));assert(!homeColorNotice(value).includes('private.invalid'));
 }
 await seed('completed',{failure:'missing'});await publish();assert.match(notice(),/게시 요청을 다시 보내지 마세요/);assert.equal(posts.length,1);
});
await check('local fixture does not pretend to run real image analysis',async()=>{
 await seed('completed',{responseMode:'local-fixture'});await publish();
 assert.match(notice(),/실제 이미지 분석을 실행하지 않았습니다/);assert.match(notice(),/실제 DB 저장·게시는 아닌 로컬 시험/);assert.equal(colorCalls,0);
});
await check('second click while publishing cannot duplicate publish or color analysis',async()=>{
 await seed('completed',{failure:'delay'});button('승인하고 게시').props.onClick();render();const b=button('확인하고 게시');b.props.onClick();await flush();
 assert.equal(posts.length,1);assert.equal(button('처리 중…').props.disabled,true);b.props.onClick();await flush();assert.equal(posts.length,1);release();await flush();
 assert.equal(colorCalls,1);assert.equal((await store.get('candidates',id)).history.length,1);
});
for(const failure of ['conflict','signed_out','unknown'])await check(failure+' preserves candidate and makes no retry or success notice',async()=>{
 await seed('completed',{failure});const before=await store.get('candidates',id);await publish();await commit();
 const after=await store.get('candidates',id);assert.equal(after.status,'pending');assert.deepEqual(after.content,before.content);assert.equal(after.history.length,0);
 assert.equal(notice(),'');assert.equal(posts.length,1);assert.equal(colorCalls,0);assert(nodes(render()).some(n=>n?.props?.role==='alert'));
});
await check('non-publication save never invokes or displays color analysis',async()=>{
 await seed('completed');const editor=nodes(render()).find(n=>n?.props?.formattedBody);
 assert.ok(editor);editor.props.onChange({...editor.props.value,summaryKo:'합성 수정 요약'});render();
 const form=nodes(render()).find(n=>n?.type==='form');form.props.onSubmit({preventDefault(){}});await flush();
 assert.equal(posts.length,1);assert.equal(posts[0].action,'save_candidate');assert.equal(colorCalls,0);assert.match(notice(),/비공개로 저장/);assert(!notice().includes('배경색'));
});
console.log(JSON.stringify({passed:checks,real_images:0,db:0,ai:0,real_publications:0,external_network:0}));
