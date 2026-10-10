// Actual classification modules + panel handlers with fake Auth/RPC only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
const root=fileURLToPath(new URL('../',import.meta.url));
let states=[],refs=[],cursor=0,rc=0,effects=[];
const fakeReact={...React,useState(initial){const i=cursor++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return[states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef(v){return refs[rc++]??={current:v};},useEffect(fn){effects.push(fn);}};
const cache=new Map();
function load(name){const file=path.resolve(root,name);if(cache.has(file))return cache.get(file);const out={};cache.set(file,out);new Function('require','exports',ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText)(s=>{if(s==='react')return fakeReact;if(s==='next/link')return{default:()=>null};if(s.startsWith('@/')||s.startsWith('.')){const t=s.startsWith('@/')?path.join(root,s.slice(2)):path.resolve(path.dirname(file),s);for(const x of ['.ts','.tsx',''])if(fs.existsSync(t+x))return load(path.relative(root,t+x));}return require(s);},out);return out;}
let checks=0;const ok=v=>{assert.ok(v);checks++;},eq=(a,b)=>{assert.deepEqual(a,b);checks++;},fails=fn=>{assert.throws(fn);checks++;};
const {classificationCommand,classificationDraft,classificationDetail,classificationMissing,classificationFilters,classificationFilterFacts,classificationMatches,classificationApplyCommand}=load('app/lib/review/classification.ts');
const {classificationRequest}=load('app/lib/review/classification-handler.ts');
const {ClassificationStore}=load('app/lib/review/classification-store.ts');
const {ReviewFailure}=load('app/lib/review/contracts.ts');
const {AdminAccessError}=load('app/lib/auth/admin-policy.ts');
const Panel=load('app/components/admin/ClassificationPanel.tsx').default;
const id='40000000-0000-4000-8000-000000000901',revision='a'.repeat(64),version='b'.repeat(64);
const facts={productType:'living_guide',category:'living',scope:'unknown',regions:[],evidence:'',foreignEligibility:'unknown',delivery:'online',deadlineKind:'',deadlineOn:'',eventStart:'',eventEnd:''};
const base={id,revision,version,classificationVersion:0,active:false,category:'living',facts,filters:null,note:'',editable:true,ready:false,reasons:[],sourceReasons:[]};
const command={revision,version,classificationVersion:0,facts,filters:null,note:'합성 원문을 확인하여 생활 안내로 재분류합니다.'};
eq(classificationCommand(command),command);eq(classificationDetail(base,id),base);
for(const category of ['policy','program','event','youth_space','living']){eq(classificationDraft(facts,category).category,category);const f=classificationFilters(category,null);eq(f?.category??null,['policy','living'].includes(category)?null:category);}
for(const bad of [{...command,actor:id},{...command,source:'myseoul_program'},{...command,classificationVersion:-1},{...command,facts:{...facts,category:'invalid'}},{...command,filters:{}},{...command,note:'短'},{...command,facts:{...facts,productType:''}},{...command,facts:{...facts,delivery:'unknown'}}])fails(()=>classificationCommand(bad));
eq(classificationMissing({...facts,category:'event',productType:'event_program'},null),['scope','evidence','eventStart','eventEnd','filters']);
const pf=classificationFilters('program',null);pf.delivery={status:'known',value:'onsite'};pf.application={status:'known',value:{deadlineKind:'fixed',start:null,end:{value:'2099-10-15T18:00:00+09:00',precision:'minute'},sourceStatus:'closed'}};
const linked=classificationFilterFacts({...facts,category:'program'},pf);eq(linked.delivery,'offline');eq(linked.deadlineKind,'fixed');eq(linked.deadlineOn,'2099-10-15');eq(linked.scope,'unknown');
const ef=classificationFilters('event',null);ef.schedule={status:'known',value:{kind:'occurrences',recurrence:null,occurrences:[{start:{value:'2099-10-11',precision:'day'},end:{value:'2099-10-12',precision:'day'}},{start:{value:'2099-10-15',precision:'day'},end:{value:'2099-10-16',precision:'day'}}]}};
const dates=classificationFilterFacts({...facts,category:'event'},ef);eq(dates.eventStart,'2099-10-11');eq(dates.eventEnd,'2099-10-16');
ok(classificationMatches({...base,classificationVersion:1,note:command.note,facts:Object.fromEntries(Object.entries(facts).reverse())},command));ok(!classificationMatches({...base,classificationVersion:2,note:command.note},command));
const from={...facts,category:'program',deadlineKind:'fixed',deadlineOn:'2099-01-31'};eq(classificationDraft(from,'event').deadlineOn,'');eq(classificationDraft(from,'policy').deadlineOn,'2099-01-31');
let calls=[];const store=new ClassificationStore({rpc:async(name,args)=>{calls.push({name,args});return{data:base,error:null};}});
await store.get(id);eq(calls[0].name,'admin_review_classification_detail');await store.save(id,command,id);eq(calls[1].args.p_actor,id);eq(calls[1].args.p_facts,facts);ok(!calls.some(c=>/claim|enqueue|publish|provider/.test(c.name)));
for(const [dbCode,code] of [['PT409','conflict'],['PT422','invalid_input'],['PT404','not_found'],['other','unavailable']]){await assert.rejects(new ClassificationStore({rpc:async()=>({error:{code:dbCode},data:null})}).get(id),e=>e.code===code);checks++;}
let authorized=0,gets=0,saves=0;const deps={authorize:async()=>{authorized++;return{userId:id};},store:()=>({get:async()=>{gets++;return base;},save:async(_,c,actor)=>{saves++;eq(actor,id);eq(c,command);return base;}})};
const url='http://localhost:3227/api/admin/review-classification/'+id;
const req=(body=command,headers={Origin:'http://localhost:3227','Content-Type':'application/json'})=>new Request(url,{method:'POST',headers,body:JSON.stringify(body)});
let res=await classificationRequest(new Request(url),id,deps);eq(res.status,200);eq(gets,1);eq(saves,0);ok(res.headers.get('cache-control').includes('no-store'));
res=await classificationRequest(req(),id,deps);eq(res.status,200);eq(saves,1);
for(const request of [req(command,{Origin:'http://evil.invalid','Content-Type':'application/json'}),req(command,{'Content-Type':'application/json'}),req({...command,actor:id}),new Request(url,{method:'PUT',headers:{Origin:'http://localhost:3227'}}),new Request(url,{method:'POST',headers:{Origin:'http://localhost:3227','Content-Type':'application/json'},body:'"'+ 'a'.repeat(160001)+'"'})]){res=await classificationRequest(request,id,deps);ok(res.status>=400);ok(res.headers.get('cache-control').includes('no-store'));}eq(saves,1);
for(const status of ['signed_out','forbidden']){res=await classificationRequest(req(),id,{...deps,authorize:async()=>{throw new AdminAccessError(status);}});ok(res.status===401||res.status===403);}eq(saves,1);ok(authorized>0);
const nodes=t=>[t,...React.Children.toArray(t?.props?.children).flatMap(c=>typeof c==='object'?nodes(c):[])];
const text=t=>typeof t==='string'?t:React.Children.toArray(t?.props?.children).map(text).join('');
const props={id,disabled:false,onBlocked(){},onActive(){},onSaved:async()=>{}};
const render=()=>{cursor=0;rc=0;effects=[];return Panel(props);};
const button=label=>{const n=nodes(render()).find(n=>n?.type==='button'&&text(n)===label);assert.ok(n,label);return n;};
const response=(item,status=200)=>new Response(JSON.stringify(status===200?{item}:{code:item}),{status});
const originalFetch=globalThis.fetch;let fetches=[],mode='success',stored=null;
globalThis.fetch=async(u,o={})=>{assert.equal(u,'/api/admin/review-classification/'+id);fetches.push(o.body?JSON.parse(o.body):null);eq(o.cache,'no-store');eq(o.credentials,'same-origin');if(o.body&&mode==='unknown')throw Error('synthetic timeout');if(o.body&&mode==='unknown_completed'){stored={...base,classificationVersion:1,version:'c'.repeat(64),active:true,ready:true,note:command.note};return response('unavailable',503);}if(!o.body&&mode==='unknown_completed'&&stored)return response(stored);if(o.body&&mode==='conflict')return response('conflict',409);return response(o.body?{...base,classificationVersion:1,version:'c'.repeat(64),active:true,ready:true,note:command.note}:base);};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
async function prepare(){states=[];refs=[];render();effects[0]();await settle();button('분류 변경').props.onClick();const t=render();nodes(t).find(n=>n?.type==='textarea').props.onChange({target:{value:command.note}});nodes(render()).find(n=>n?.type==='input'&&n.props.type==='checkbox').props.onChange({target:{checked:true}});}
try{
 await prepare();ok(text(render()).includes('미저장 변경'));eq(button('분류 변경 닫기').props.disabled,true);
 const form=nodes(render()).find(n=>n?.type==='form');form.props.onSubmit({preventDefault(){}});form.props.onSubmit({preventDefault(){}});await settle();eq(fetches.filter(Boolean).length,1);eq(states[0].active,true);eq(states[3],false);
 for(mode of ['conflict','unknown']){fetches=[];await prepare();await nodes(render()).find(n=>n?.type==='form').props.onSubmit({preventDefault(){}});eq(states[7],command.note);eq(states[3],true);eq(fetches.filter(Boolean).length,1);if(mode==='unknown'){eq(button('분류·필수값 저장·재판정').props.disabled,true);button('입력을 유지하고 저장 상태 확인').props.onClick();await settle();eq(fetches.filter(Boolean).length,1);eq(states[7],command.note);eq(button('분류·필수값 저장·재판정').props.disabled,true);}}
 fetches=[];stored=null;mode='unknown_completed';await prepare();await nodes(render()).find(n=>n?.type==='form').props.onSubmit({preventDefault(){}});eq(states[3],true);eq(states[7],command.note);button('입력을 유지하고 저장 상태 확인').props.onClick();await settle();eq(states[3],false);eq(fetches.filter(Boolean).length,1);eq(states[0].classificationVersion,1);
 // Unresolved native reasons are read-back state, not client-confirmed completion.
 fails(()=>classificationDetail({...base,id:'another'},id));fails(()=>classificationDetail({...base,active:true},id));
 const sourceFilters=classificationFilters('program',null);sourceFilters.delivery={status:'known',value:'onsite'};sourceFilters.location={status:'known',value:{scope:'specific',venues:[{province:'11',district:null,facility:'',address:''}]}};sourceFilters.application={status:'known',value:{deadlineKind:'none',start:null,end:null,sourceStatus:'unknown'}};
 eq(classificationFilters('event',sourceFilters).location,sourceFilters.location);eq(classificationFilters('event',sourceFilters).schedule.status,'unknown');eq(classificationFilters('event',sourceFilters).topic.status,'unknown');
 const programItem={...base,category:'program',facts:{...facts,productType:'event_program',category:'program',delivery:'offline',deadlineKind:'none'},filters:sourceFilters};
 globalThis.fetch=async()=>response(programItem);states=[];refs=[];render();effects[0]();await settle();button('분류 변경').props.onClick();
 let select=nodes(render()).find(n=>n?.type==='select');select.props.onChange({target:{value:'event'}});eq(states[2].location,sourceFilters.location);eq(states[1].deadlineKind,'');
 nodes(render()).find(n=>n?.type==='select').props.onChange({target:{value:'program'}});eq(states[2],sourceFilters);eq(states[1],programItem.facts);
 const filterNode=nodes(render()).find(n=>n?.props?.prefix==='classification');filterNode.props.onChange({...states[2],topic:{status:'known',value:'language_learning'}});
 nodes(render()).find(n=>n?.type==='select').props.onChange({target:{value:'event'}});nodes(render()).find(n=>n?.type==='select').props.onChange({target:{value:'program'}});eq(states[2].topic.value,'language_learning');eq(states[2].application,sourceFilters.application);
 const body={titleKo:'합성 제목',titleJa:'合成題名',summaryKo:'합성 요약',summaryJa:'合成概要',contentKo:'합성 본문',contentJa:'合成本文'};
 const pub={...base,active:true,ready:true,classificationVersion:1,version:'c'.repeat(64),publication:{version:'d'.repeat(64),category:'program',content:body,applied:false}};
 eq(classificationDetail(pub,id).publication.content,body);eq(classificationDetail({...pub,publication:{...pub.publication,content:{...body,titleJa:null,summaryJa:null,contentJa:null}}},id).publication.content.contentJa,'');
 const apply={action:'apply_public',bodyReviewed:true,revision,version:pub.version,classificationVersion:1,publicationVersion:pub.publication.version,content:body,note:command.note};eq(classificationApplyCommand(apply),apply);
 for(const bad of [{...apply,actor:id},{...apply,bodyReviewed:false},{...apply,publicationVersion:'wrong'},{...apply,content:{...body,contentJa:''}}])fails(()=>classificationApplyCommand(bad));
 let applies=0;res=await classificationRequest(req(apply),id,{...deps,store:()=>({apply:async(_,c,actor)=>{applies++;eq(c,apply);eq(actor,id);return pub;}})});eq(res.status,200);eq(applies,1);ok(res.headers.get('cache-control').includes('no-store'));
 let current=pub,transport='success',writes=0;const completed={...pub,publication:{...pub.publication,category:'living',applied:true}};
 globalThis.fetch=async(u,o={})=>{if(o.body){writes++;if(transport==='unknown'){current=completed;return response('unavailable',503);}if(transport==='conflict')return response('conflict',409);return response(completed);}return response(current);};
 async function publicPrepare(){states=[];refs=[];current=pub;render();effects[0]();await settle();button('공개 본문 확인·재분류 적용').props.onClick();let t=render();nodes(t).find(n=>n?.type==='textarea').props.onChange({target:{value:command.note}});nodes(render()).find(n=>n?.type==='input'&&n.props.type==='checkbox').props.onChange({target:{checked:true}});}
 await publicPrepare();props.onSaved=async()=>{throw Error('synthetic refresh failed');};await nodes(render()).find(n=>n?.type==='form').props.onSubmit({preventDefault(){}});eq(states[13],false);eq(states[10],false);ok(text(render()).includes('적용은 완료했지만'));props.onSaved=async()=>{};
 transport='unknown';writes=0;await publicPrepare();await nodes(render()).find(n=>n?.type==='form').props.onSubmit({preventDefault(){}});eq(states[10],true);eq(states[13],true);button('입력을 유지하고 저장 상태 확인').props.onClick();await settle();eq(states[10],false);eq(states[13],false);eq(writes,1);
 transport='conflict';writes=0;await publicPrepare();await nodes(render()).find(n=>n?.type==='form').props.onSubmit({preventDefault(){}});current={...pub,version:'e'.repeat(64),publication:{...pub.publication,version:'f'.repeat(64),content:{...body,contentKo:'다른 검토자가 수정한 합성 본문'}}};button('입력을 유지하고 저장 상태 확인').props.onClick();await settle();eq(states[15],false);eq(states[14].contentKo,body.contentKo);eq(states[0].publication.content.contentKo,current.publication.content.contentKo);eq(button('재분류 적용').props.disabled,true);eq(writes,1);
 console.log(JSON.stringify({checks,syntheticOnly:true,externalConnections:0,result:'passed'}));
}finally{globalThis.fetch=originalFetch;}
