// Actual featured panel -> authenticated handler -> store -> fake RPC. No real I/O.
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
const Panel=load('app/components/admin/PublishedHomeFeatured.tsx').default;
const {FeaturedStore,featuredDetail}=load('app/lib/home-featured/admin.ts');
const {featuredRequest}=load('app/lib/home-featured/admin-handler.ts');
const {AdminAccessError}=load('app/lib/auth/admin-policy.ts');
const id='20000000-0000-4000-8000-000000000001',pid='30000000-0000-4000-8000-000000000001',other='30000000-0000-4000-8000-000000000002',actor='00000000-0000-4000-8000-000000000001';
const base={id,publishedId:pid,revision:'a'.repeat(64),version:'b'.repeat(64),stateVersion:0,position:null,eligible:true,pins:[]};
let raw,behavior,posts,rpcs,history,blocked,authorized,disabled,release;
const store=new FeaturedStore({async rpc(name,args){rpcs.push({name,args:structuredClone(args)});
 if(name==='admin_review_home_featured')return {data:{...raw,token:'PRIVATE'},error:null};
 assert.equal(name,'admin_review_set_home_featured');assert.equal(args.p_actor,actor);
 if(behavior==='delay')await new Promise(r=>release=r);
 if(behavior==='conflict')raw.version='e'.repeat(64);
 if(args.p_revision!==raw.revision||args.p_version!==raw.version)return {data:null,error:{message:'home_featured_conflict'}};
 let pins=raw.pins.filter(p=>p.id!==args.p_target);if(args.p_position!==null)pins.splice(args.p_position-1,0,{id:args.p_target,title:'합성 글',eligible:true});
 pins=pins.map((p,i)=>({...p,position:i+1}));assert(pins.length<=2);
 history.push({actor:args.p_actor,request:args.p_request,before:raw.pins,after:pins});
 raw={...raw,pins,position:pins.find(p=>p.id===pid)?.position??null,stateVersion:raw.stateVersion+1,version:'c'.repeat(64)};
 if(behavior==='unknown')throw Error('PRIVATE_SERVER');
 return {data:behavior==='malformed'?{...raw,stateVersion:-1}:raw,error:null};
}});
const authorize=async()=>{if(authorized!==true)throw new AdminAccessError(authorized);return {userId:actor};};
const request=(body,extra={})=>{const headers=new Headers(extra);if(!headers.has('origin'))headers.set('origin','https://synthetic.invalid');if(!headers.has('content-type'))headers.set('content-type','application/json');return new Request('https://synthetic.invalid/api/admin/review-home-featured/'+id,{method:body?'POST':'GET',headers,...(body?{body:typeof body==='string'?body:JSON.stringify(body)}:{})});};
const handler=req=>featuredRequest(req,id,{authorize,store:()=>store});
const nodes=t=>[t,...React.Children.toArray(t?.props?.children).flatMap(c=>typeof c==='object'?nodes(c):[])];
const text=t=>typeof t==='string'||typeof t==='number'?String(t):React.Children.toArray(t?.props?.children).map(text).join('');
const props={id,onBlocked:v=>blocked=v};
function render(){cursor=0;refCursor=0;effects=[];return Panel({...props,disabled});}
const flush=()=>new Promise(r=>setImmediate(r));
async function commit(){render();for(const fn of effects)fn();await flush();return render();}
function button(label){const b=nodes(render()).find(n=>n?.type==='button'&&text(n)===label);assert.ok(b,'missing '+label);return b;}
function select(value){nodes(render()).find(n=>n?.type==='select').props.onChange({target:{value:String(value)}});}
async function seed(overrides={}){
 raw={...base,...overrides};behavior='success';posts=[];rpcs=[];history=[];blocked=false;authorized=true;disabled=false;states=[];refs=[];dependencies=[];
 globalThis.fetch=async(url,options={})=>{assert.equal(url,'/api/admin/review-home-featured/'+id);assert.equal(options.cache,'no-store');assert.equal(options.credentials,'same-origin');if(options.method==='POST')posts.push(JSON.parse(options.body));return handler(request(options.body,options.headers));};
 await commit();
}
async function save(){nodes(render()).find(n=>n?.type==='form').props.onSubmit({preventDefault(){}});await flush();await commit();}
let passed=0;const check=async(name,fn)=>{await fn();passed++;console.log('PASS '+name);};
await check('real panel reads metadata only; no write or private DTO fields',async()=>{await seed();assert(text(render()).includes('자동 선정 대상'));assert.equal(posts.length,0);assert.deepEqual(rpcs.map(x=>x.name),['admin_review_home_featured']);assert(!JSON.stringify(featuredDetail({...base,token:'PRIVATE'},id)).includes('PRIVATE'));});
await check('explicit pin uses server actor and latest fence; draft and cancel are write-free',async()=>{
 await seed();button('대표로 고정').props.onClick();await commit();assert.equal(blocked,true);assert.equal(posts.length,0);button('취소').props.onClick();await commit();assert.equal(blocked,false);
 button('대표로 고정').props.onClick();await commit();await save();assert.equal(posts.length,1);assert.deepEqual(Object.keys(posts[0]).sort(),['position','requestId','revision','targetId','version']);assert.equal(posts[0].version,base.version);assert.equal(posts[0].targetId,pid);assert.equal(history[0].actor,actor);assert.equal(raw.position,1);assert.equal(blocked,false);
});
await check('second position, explicit reorder, full list and ineligible content',async()=>{
 const pin={id:other,position:1,title:'기존 글',eligible:true};await seed({pins:[pin]});button('대표로 고정').props.onClick();await commit();assert.equal(nodes(render()).find(n=>n?.type==='select').props.value,2);select(1);await save();assert.deepEqual(raw.pins.map(p=>p.id),[pid,other]);
 await seed({pins:[{id:pid,position:1,title:'현재 글',eligible:true},{...pin,position:2}],position:1});button('고정 순서 변경').props.onClick();await commit();assert.equal(button('고정 저장').props.disabled,true);select(2);await save();assert.deepEqual(raw.pins.map(p=>p.id),[other,pid]);
 await seed({pins:[pin,{id:'30000000-0000-4000-8000-000000000003',position:2,title:'다른 글',eligible:true}]});assert.equal(button('대표로 고정').props.disabled,true);assert(text(render()).includes('먼저 한 항목을 해제'));assert.equal(posts.length,0);
 await seed({eligible:false});assert.equal(button('대표로 고정').props.disabled,true);
});
await check('expired or hidden pin can be explicitly removed without altering content',async()=>{
 await seed({pins:[{id:other,position:1,title:'종료 글',eligible:false}]});assert(text(render()).includes('현재 노출 제외'));button('해제').props.onClick();await flush();await commit();assert.equal(posts.length,1);assert.equal(posts[0].targetId,other);assert.equal(posts[0].position,null);assert.deepEqual(raw.pins,[]);assert(text(render()).includes('남은 자리는 자동으로 채웁니다.'));
});
await check('other editing locks controls; duplicate submit sends only once',async()=>{
 await seed();disabled=true;assert.equal(button('대표로 고정').props.disabled,true);assert.equal(posts.length,0);
 await seed();button('대표로 고정').props.onClick();await commit();behavior='delay';const form=nodes(render()).find(n=>n?.type==='form');form.props.onSubmit({preventDefault(){}});await flush();form.props.onSubmit({preventDefault(){}});await flush();assert.equal(posts.length,1);assert.equal(button('저장 중…').props.disabled,true);release();await flush();await commit();assert.equal(history.length,1);
});
for(const mode of ['conflict','unknown','malformed','signed_out','forbidden'])await check(mode+' keeps draft and stops automatic write/read retries',async()=>{
 await seed();button('대표로 고정').props.onClick();await commit();behavior=mode;if(['signed_out','forbidden'].includes(mode))authorized=mode;
 await save();assert.equal(nodes(render()).find(n=>n?.type==='select').props.value,1);assert.equal(button('고정 저장').props.disabled,true);assert(nodes(render()).some(n=>n?.props?.role==='alert'));const count=rpcs.length;await commit();assert.equal(rpcs.length,count);assert.equal(posts.length,1);
 authorized=true;behavior='success';button('선택 취소·최신 고정 정보 확인').props.onClick();await flush();await commit();assert.equal(posts.length,1);assert.equal(blocked,false);
});
await check('authenticated Origin-checked exact payload, bounded body, private no-store',async()=>{
 await seed();const body={revision:base.revision,version:base.version,targetId:pid,position:1,requestId:crypto.randomUUID()};
 for(const [denial,status]of [['signed_out',401],['forbidden',403],['auth_unavailable',503]]){authorized=denial;const count=rpcs.length;for(const req of [request(),request(body)]){const r=await handler(req);assert.equal(r.status,status);assert.match(r.headers.get('cache-control'),/private.*no-store/);}assert.equal(rpcs.length,count);}
 authorized=true;assert.equal((await handler(request(body,{origin:'https://attacker.invalid'}))).status,403);
 for(const invalid of [{...body,actor},{...body,position:3},{...body,targetId:'bad'},{...body,version:'bad'},{...body,requestId:'bad'},' '.repeat(4097),'bad-json']){const r=await handler(request(invalid));assert.equal(r.status,422);assert(!JSON.stringify(await r.json()).includes('PRIVATE'));}assert.equal(history.length,0);
});
await check('malformed details fail closed; parent shares navigation and edit locks',()=>{
 for(const patch of [{version:'bad'},{stateVersion:-1},{position:1},{pins:[{id:pid,position:2,title:'bad',eligible:true}]}])assert.throws(()=>featuredDetail({...base,...patch},id));
 const parent=fs.readFileSync('app/components/admin/ReviewWorkspace.tsx','utf8');assert(parent.includes('<PublishedHomeFeatured'));assert(parent.includes('onBlocked={setFeaturedBlocked}'));assert.match(parent,/const busy = .*featuredBlocked/);assert.match(parent,/PublishedHomeColor[^\n]*featuredBlocked/);
});
console.log(JSON.stringify({passed,real_network:0,operational_db:0,ai:0,content_writes:0}));
