// Actual color panel -> admin handler -> store -> fake Auth/RPC. No real I/O.
import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';
import {createRequire,syncBuiltinESMExports} from 'node:module';
import net from 'node:net';import https from 'node:https';import http from 'node:http';import dns from 'node:dns/promises';
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react'),root=path.resolve('.');
const deny=()=>{throw Error('real_network_forbidden');};globalThis.fetch=net.Socket.prototype.connect=https.request=https.get=http.request=http.get=dns.lookup=deny;syncBuiltinESMExports();
let states=[],refs=[],cursor=0,refCursor=0,effects=[],dependencies=[];
const fakeReact={...React,useState(initial){const i=cursor++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return [states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef(initial){return refs[refCursor++]??={current:initial};},useEffect(fn,deps){const i=cursor++;if(!dependencies[i]||deps.some((v,j)=>v!==dependencies[i][j])){dependencies[i]=deps;effects.push(fn);}}};
const cache=new Map();function load(name){const file=path.join(root,name);if(cache.has(file))return cache.get(file);const out={};cache.set(file,out);
 if(name==='app/components/admin/ReviewEditors.tsx')return {fieldClass:'',primaryButton:'',secondaryButton:''};
 const code=ts.transpileModule(fs.readFileSync(file,'utf8'),{fileName:file,compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
 new Function('require','exports',code)(s=>{if(s==='react')return fakeReact;if(s.startsWith('@/')||s.startsWith('.')){const target=s.startsWith('@/')?path.join(root,s.slice(2)):path.resolve(path.dirname(file),s);for(const ext of ['', '.ts','.tsx'])if(fs.existsSync(target+ext)&&fs.statSync(target+ext).isFile())return load(path.relative(root,target+ext).replaceAll('\\','/'));}return require(s);},out);return out;}
const Panel=load('app/components/admin/PublishedHomeColor.tsx').default;
const {HomeColorStore,homeColorDetail,homeAnalysisLabel}=load('app/lib/home-colors/admin.ts');
const {homeColorRequest}=load('app/lib/home-colors/admin-handler.ts');
const {AdminAccessError}=load('app/lib/auth/admin-policy.ts');
const id='20000000-0000-4000-8000-000000000001',publishedId='30000000-0000-4000-8000-000000000001',actor='00000000-0000-4000-8000-000000000001';
const base={id,publishedId,revision:'a'.repeat(64),version:'b'.repeat(64),analysisState:'failed',analysisTone:'default',analysisReason:'analysis_failed',analysisActive:false,tone:'default',manual:false,choiceVersion:0,canEdit:true,changedAt:null};
let raw,behavior,posts,rpcs,history,blocked,authorized,disabled,release;
const store=new HomeColorStore({async rpc(name,args){rpcs.push({name,args:structuredClone(args)});
 if(name==='admin_review_home_color')return {data:{...raw,token:'PRIVATE'},error:null};
 assert.equal(name,'admin_review_set_home_color');assert.equal(args.p_actor,actor);
 if(behavior==='delay')await new Promise(r=>release=r);
 if(behavior==='conflict')raw.version='e'.repeat(64);
 if(!raw.canEdit||args.p_revision!==raw.revision||args.p_version!==raw.version)return {data:null,error:{message:'home_color_conflict'}};
 history.push({tone:args.p_tone,actor:args.p_actor,previous:raw.tone});
 raw={...raw,tone:args.p_tone,version:'c'.repeat(64),manual:true,choiceVersion:raw.choiceVersion+1,changedAt:'2026-10-24T00:00:00Z'};
 if(behavior==='unknown')throw Error('PRIVATE_SERVER');
 if(behavior==='malformed')return {data:{...raw,tone:'__proto__'},error:null};
 return {data:raw,error:null};
}});
const authorize=async()=>{if(authorized!==true)throw new AdminAccessError(authorized);return {userId:actor};};
const request=(body,extra={})=>{const headers=new Headers(extra);if(!headers.has('origin'))headers.set('origin','https://synthetic.invalid');if(!headers.has('content-type'))headers.set('content-type','application/json');return new Request('https://synthetic.invalid/api/admin/review-home-color/'+id,{method:body?'POST':'GET',headers,...(body?{body:typeof body==='string'?body:JSON.stringify(body)}:{})});};
const handler=req=>homeColorRequest(req,id,{authorize,store:()=>store});
const nodes=t=>[t,...React.Children.toArray(t?.props?.children).flatMap(c=>typeof c==='object'?nodes(c):[])];
const text=t=>typeof t==='string'||typeof t==='number'?String(t):React.Children.toArray(t?.props?.children).map(text).join('');
const props={id,disabled:false,onBlocked:v=>blocked=v};
function render(){cursor=0;refCursor=0;effects=[];return Panel({...props,disabled});}
const flush=()=>new Promise(r=>setImmediate(r));
async function commit(){render();for(const fn of effects)fn();await flush();return render();}
function button(label){const b=nodes(render()).find(n=>n?.type==='button'&&text(n)===label);assert.ok(b,'missing button '+label);return b;}
function select(value){const node=nodes(render()).find(n=>n?.type==='select');assert.ok(node);node.props.onChange({target:{value}});}
async function seed(overrides={}){
 raw={...base,...overrides};behavior='success';posts=[];rpcs=[];history=[];blocked=false;authorized=true;disabled=false;states=[];refs=[];dependencies=[];
 globalThis.fetch=async(url,options={})=>{assert.equal(url,'/api/admin/review-home-color/'+id);assert.equal(options.cache,'no-store');assert.equal(options.credentials,'same-origin');if(options.method==='POST')posts.push(JSON.parse(options.body));return handler(request(options.body,options.headers));};
 await commit();
}
async function save(){const form=nodes(render()).find(n=>n?.type==='form');assert.ok(form);form.props.onSubmit({preventDefault(){}});await flush();await commit();}
let checks=0;const check=async(name,fn)=>{await fn();checks++;console.log('PASS '+name);};
await check('published panel loads saved result without an image request or write',async()=>{await seed();assert(text(render()).includes('분석 실패'));assert(text(render()).includes('적용 색상: 회청보라'));assert.equal(posts.length,0);assert.deepEqual(rpcs.map(x=>x.name),['admin_review_home_color']);assert(!JSON.stringify(homeColorDetail({...base,token:'PRIVATE'},id)).includes('PRIVATE'));});
for(const [analysisState,analysisReason,label]of [['missing',null,'분석 기록 없음'],['no_image',null,'이미지 없음'],['completed','ambiguous','색상 판단 어려움'],['processing',null,'처리 결과 미확인']])await check('stored '+analysisState+' is distinct from a manual choice',async()=>{
 await seed({analysisState,analysisReason,tone:'red',manual:true,choiceVersion:2});assert(text(render()).includes(label));assert(text(render()).includes('더스티 로즈 · 운영자 지정'));assert.equal(posts.length,0);
});
await check('only approved seven choices; selection is draft until explicit save and can cancel',async()=>{
 await seed();button('색상 변경').props.onClick();await commit();assert.equal(blocked,true);
 const values=nodes(render()).filter(n=>n?.type==='option').map(n=>n.props.value);assert.deepEqual(values,['default','orange','yellow','green','blue','purple','red']);
 assert.equal(button('색상 저장').props.disabled,true);select('orange');assert.equal(posts.length,0);assert.equal(raw.tone,'default');
 button('취소').props.onClick();await commit();assert.equal(blocked,false);assert.equal(history.length,0);assert(text(render()).includes('적용 색상: 회청보라'));
});
await check('explicit save uses latest fence and authenticated actor; analysis is unchanged',async()=>{
 await seed();const original=structuredClone(raw);button('색상 변경').props.onClick();await commit();select('orange');await save();
 assert.equal(posts.length,1);assert.equal(posts[0].revision,original.revision);assert.equal(posts[0].version,original.version);assert.match(posts[0].requestId,/^[a-f0-9-]{36}$/);assert.equal(posts[0].tone,'orange');assert(!('actor'in posts[0]));
 assert.equal(raw.analysisState,original.analysisState);assert.equal(raw.analysisTone,original.analysisTone);assert.equal(raw.analysisReason,original.analysisReason);assert.equal(history.length,1);assert.equal(blocked,false);assert(text(render()).includes('살구 · 운영자 지정'));assert(text(render()).includes('선택한 배경색을 저장했습니다.'));
});
await check('active analysis, other editing and saving keep existing locks',async()=>{
 await seed({analysisState:'processing',analysisActive:true,canEdit:false,analysisReason:null});assert.equal(button('색상 변경').props.disabled,true);
 await seed();disabled=true;assert.equal(button('색상 변경').props.disabled,true);assert.equal(posts.length,0);
 await seed();button('색상 변경').props.onClick();await commit();select('green');behavior='delay';const form=nodes(render()).find(n=>n?.type==='form');form.props.onSubmit({preventDefault(){}});await flush();form.props.onSubmit({preventDefault(){}});await flush();assert.equal(posts.length,1);assert.equal(button('저장 중…').props.disabled,true);release();await flush();await commit();assert.equal(history.length,1);
});
for(const mode of ['conflict','unknown','malformed','signed_out','forbidden'])await check(mode+' preserves selection, stops retries, and requires explicit read',async()=>{
 await seed();button('색상 변경').props.onClick();await commit();select('blue');behavior=mode;if(['signed_out','forbidden'].includes(mode))authorized=mode;
 await save();assert.equal(nodes(render()).find(n=>n?.type==='select').props.value,'blue');assert.equal(button('색상 저장').props.disabled,true);assert(nodes(render()).some(n=>n?.props?.role==='alert'));
 await flush();await commit();assert.equal(posts.length,1);assert(!text(render()).includes('선택한 배경색을 저장했습니다.'));
 authorized=true;behavior='success';await button('변경 취소·최신 결과 확인').props.onClick();await flush();await commit();assert.equal(posts.length,1);assert(text(render()).includes('색상 변경'));
});
await check('server authorizes before reads/writes, retains Origin/no-store, validates payload',async()=>{
 await seed();const body={revision:base.revision,version:base.version,tone:'orange',requestId:crypto.randomUUID()};
 for(const [denial,status]of [['signed_out',401],['forbidden',403],['auth_unavailable',503]]){authorized=denial;const count=rpcs.length;for(const req of [request(),request(body)]){const r=await handler(req);assert.equal(r.status,status);assert.match(r.headers.get('cache-control'),/private.*no-store/);}assert.equal(rpcs.length,count);}
 authorized=true;let r=await handler(request(body,{origin:'https://attacker.invalid'}));assert.equal(r.status,403);
 for(const invalid of [{...body,actor}, {...body,tone:'#ffffff'}, {...body,tone:'__proto__'}, {...body,version:'bad'}, {...body,requestId:'bad'},' '.repeat(4097),'bad-json']){r=await handler(request(invalid));assert.equal(r.status,422);assert(!JSON.stringify(await r.json()).includes('PRIVATE'));}
 assert.equal(history.length,0);assert.equal((await handler(request())).status,200);
});
await check('malformed DTO and unknown analysis states fail closed',()=>{
 for(const change of [{version:'bad'},{tone:'__proto__'},{analysisState:'new'},{canEdit:false},{manual:true},{analysisReason:'PRIVATE'}])assert.throws(()=>homeColorDetail({...base,...change},id));
 assert.equal(homeAnalysisLabel({...base,analysisState:'completed',analysisTone:'blue',analysisReason:'matched'}),'완료 · 페리윙클');
});
console.log(JSON.stringify({passed:checks,real_network:0,operational_db:0,images:0,ai:0,real_publish:0}));
