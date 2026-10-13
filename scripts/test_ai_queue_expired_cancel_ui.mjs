// Real component -> official handler -> fake Auth/RPC. No network/DB/AI.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
const root=fileURLToPath(new URL('../',import.meta.url));
const oldConnect=net.Socket.prototype.connect,oldFetch=globalThis.fetch;
net.Socket.prototype.connect=function(){throw Error('real network forbidden');};
globalThis.fetch=async()=>{throw Error('real fetch forbidden');};
let states=[],refs=[],cursor=0,refCursor=0,effects=[];
const fakeReact={...React,useState(initial){const i=cursor++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return [states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef(initial){return refs[refCursor++]??={current:initial};},useEffect(fn){effects.push(fn);},useCallback(fn){return fn;}};
const cache=new Map();
function load(name){const filename=path.join(root,name);if(cache.has(filename))return cache.get(filename);if(filename.endsWith('.css'))return {};const exports={};cache.set(filename,exports);
 const code=ts.transpileModule(fs.readFileSync(filename,'utf8'),{fileName:filename,compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
 new Function('require','exports',code)(s=>{if(s==='react')return fakeReact;if(s==='next/link')return {default:()=>null};if(s.startsWith('@/')||s.startsWith('.')){const file=s.startsWith('@/')?path.join(root,s.slice(2)):path.resolve(path.dirname(filename),s);for(const suffix of ['.ts','.tsx',''])if(fs.existsSync(file+suffix))return load(path.relative(root,file+suffix));}return require(s);},exports);return exports;}
const Panel=load('app/components/admin/AiQueueReview.tsx').default;
const {aiReview,DatabaseAiReviewStore}=load('app/lib/review/ai-review.ts');
const {aiReviewRequest}=load('app/lib/review/ai-review-handlers.ts');
const {AdminAccessError}=load('app/lib/auth/admin-policy.ts');
const data=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','test_program_db.py','--fixtures'],{cwd:path.join(root,'scripts'),encoding:'utf8'}));
const job='10000000-0000-4000-8000-000000000001',sid='20000000-0000-4000-8000-000000000001',actor='30000000-0000-4000-8000-000000000001';
const facts=data.fixtures[0].item.program_facts;
const initialRaw={jobId:job,sourceItemId:sid,sourceName:'seoul_reservation',revision:'a'.repeat(64),version:'b'.repeat(64),status:'claimed',canRecheck:false,canExclude:false,recheckPending:false,note:'',expiredCancellation:{attempt:'c'.repeat(64)},
 review:{id:sid,revision:'a'.repeat(64),version:'b'.repeat(64),schema:'program-scope-v1-local',profile:'program_capital_v1_local',factsVersion:1,source:{name:'seoul_reservation',title:'합성 만료 작업',url:facts.official_url,body:'합성 원문과 관측값을 보존합니다.'},facts,observedFacts:facts,result:{decision:'in_scope',disposition:'target',reasons:[]},status:'resolved',aiStatus:'claimed',editableFields:[],history:[]},
 workerId:'PRIVATE_WORKER',secret:'PRIVATE_KEY'};
const heldRaw={...structuredClone(initialRaw),status:'cancelled',version:'d'.repeat(64),expiredCancellation:null,recheckPending:true,
 review:{...structuredClone(initialRaw.review),version:'d'.repeat(64),status:'open',aiStatus:'cancelled',editableFields:['description'],result:{...initialRaw.review.result,reasons:['ai_recheck_requested']}}};
let raw,rpcCalls=[],posts=[],reads=0,mode='success',authorized=true,changed=0,reviewed=0,busySignals=[],release;
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};const ok=v=>{assert.ok(v);checks++;};
const nodes=t=>[t,...React.Children.toArray(t?.props?.children).flatMap(c=>typeof c==='object'?nodes(c):[])];
const text=t=>typeof t==='string'||typeof t==='number'?String(t):React.Children.toArray(t?.props?.children).map(text).join('');
const props={jobId:job,onClose(){},onBusy(v){busySignals.push(v);},onChanged(){changed++;},onReview(v){eq(v.recheckPending,true);reviewed++;}};
function render(){cursor=0;refCursor=0;effects=[];return Panel(props);}
function button(label){const b=nodes(render()).find(n=>n?.type==='button'&&text(n)===label);ok(b);return b;}
const flush=()=>new Promise(r=>setImmediate(r));
function seed(view=aiReview(initialRaw,job)){states=[structuredClone(view),false,false,'','',false,null,''];refs=[];raw=structuredClone(initialRaw);rpcCalls=[];posts=[];reads=0;mode='success';authorized=true;changed=0;reviewed=0;busySignals=[];}
const store=new DatabaseAiReviewStore({async rpc(name,args){rpcCalls.push({name,args:structuredClone(args)});
 if(name==='admin_ai_queue_review_detail')return {data:raw,error:null};
 assert.equal(name,'admin_seoul_ai_cancel_expired');assert.equal(args.p_actor,actor);
 if(mode==='delay')await new Promise(r=>release=r);
 if(mode==='conflict')return {data:null,error:{code:'PT409',message:'PRIVATE_KEY'}};
 if(mode==='unknown')throw Error('PRIVATE_KEY');
 if(mode==='malformed')return {data:initialRaw,error:null};
 raw=structuredClone(heldRaw);raw.note=args.p_note;return {data:raw,error:null};
}});
globalThis.fetch=async(url,options)=>{
 assert.equal(url,`/api/admin/ai-queue/${job}`);assert.equal(options.credentials,'same-origin');assert.equal(options.cache,'no-store');
 if(options.method==='POST')posts.push(JSON.parse(options.body));else reads++;
 const request=new Request('https://example.test'+url,{method:options.method??'GET',headers:{origin:'https://example.test',...(options.headers??{})},...(options.body?{body:options.body}:{})});
 const result=await aiReviewRequest(request,job,{authorize:async()=>{if(!authorized)throw new AdminAccessError('signed_out');return {userId:actor};},store:()=>store});
 assert.ok(result.headers.get('cache-control').includes('no-store'));
 return result;
};
const trigger={focus(){}};
function begin(){button('만료 작업 취소·재검토').props.onClick({currentTarget:trigger});}
async function cancel(){begin();button('만료 작업 취소').props.onClick();await flush();await flush();}
async function refresh(){button('입력을 유지하고 최신 상태 확인').props.onClick();await flush();await flush();}
function writeNote(value){nodes(render()).find(n=>n.type==='textarea').props.onChange({target:{value}});}
try{
 seed();ok(text(render()).includes('AI 작업 시간 만료'));ok(text(render()).includes('취소 메모 (선택)'));
 ok(!JSON.stringify(render()).includes(initialRaw.expiredCancellation.attempt));ok(!text(render()).includes('PRIVATE_'));
 for(const view of [{...aiReview(initialRaw,job),expiredCancellation:undefined},
  {...aiReview(initialRaw,job),status:'completed',expiredCancellation:undefined},
  {...aiReview(initialRaw,job),sourceName:'myseoul_program',status:'queued',canRecheck:true,expiredCancellation:undefined}]){
  seed(view);ok(!text(render()).includes('만료 작업 취소·재검토'));eq(posts.length,0);
 }
 seed();writeNote('남겨둘 선택 메모');begin();eq(states[6],'cancel_expired');button('취소').props.onClick();eq(states[6],null);eq(states[3],'남겨둘 선택 메모');eq(posts.length,0);
 begin();nodes(render()).find(n=>n.props?.['aria-label']==='재검토 최종 확인').props.onKeyDown({key:'Escape'});eq(states[6],null);eq(states[3],'남겨둘 선택 메모');
 for(const note of ['', '  운영자가 입력한 메모  ']){
  seed();writeNote(note);const original=structuredClone(initialRaw.review);await cancel();
  eq(posts.length,1);eq(Object.keys(posts[0]).sort(),['action','attempt','note','requestId','revision','version']);
  eq(posts[0].action,'cancel_expired');eq(posts[0].attempt,initialRaw.expiredCancellation.attempt);eq(posts[0].note,note.trim());
  eq(posts[0].revision,initialRaw.revision);eq(posts[0].version,initialRaw.version);ok(/^[a-f0-9-]{36}$/.test(posts[0].requestId));
  eq(rpcCalls.length,1);eq(rpcCalls[0].name,'admin_seoul_ai_cancel_expired');eq(rpcCalls[0].args.p_actor,actor);
  eq(states[0].status,'cancelled');eq(states[0].recheckPending,true);eq(states[0].values,aiReview(initialRaw,job).values);eq(states[3],'');eq(changed,1);
  eq(initialRaw.review,original);ok(!text(render()).includes('만료 작업 취소·재검토'));eq(reviewed,0);
  button('사실 검토에서 수정').props.onClick();eq(reviewed,1);eq(posts.length,1);
  ok(!rpcCalls.some(c=>/claim|finish|approve|publish|complete_recheck/.test(c.name)));
 }
 seed();mode='delay';begin();const finalClick=button('만료 작업 취소').props.onClick;finalClick();finalClick();await flush();eq(posts.length,1);eq(states[2],true);eq(button('만료 작업 취소·재검토').props.disabled,true);eq(button('입력을 유지하고 최신 상태 확인').props.disabled,true);release();await flush();await flush();eq(states[2],false);
 for(const outcome of ['unknown','malformed']){
  seed();mode=outcome;writeNote('보존할 메모');await cancel();eq(states[5],true);eq(states[3],'보존할 메모');eq(posts.length,1);eq(changed,0);eq(button('만료 작업 취소·재검토').props.disabled,true);
  ok(text(render()).includes('취소 요청을 다시 보내지 말고'));ok(!text(render()).includes('재시도해 주세요'));
  const requestId=posts[0].requestId;mode='success';await refresh();eq(reads,1);eq(posts.length,1);eq(states[5],true);eq(posts[0].requestId,requestId);
  // A new attempt or queued response is NOT proof of this unknown cancellation.
  raw={...raw,version:'e'.repeat(64),expiredCancellation:{attempt:'f'.repeat(64)}};await refresh();eq(states[5],true);eq(posts.length,1);
  raw=structuredClone(heldRaw);await refresh();eq(states[5],false);eq(states[0].recheckPending,true);eq(states[3],'보존할 메모');eq(posts.length,1);ok(text(render()).includes('現在')===false);
 }
 seed();mode='conflict';writeNote('충돌 시 보존');await cancel();eq(states[5],true);eq(states[3],'충돌 시 보존');eq(posts.length,1);eq(changed,0);
 mode='success';raw={...raw,version:'e'.repeat(64),expiredCancellation:{attempt:'f'.repeat(64)}};await refresh();eq(states[5],false);eq(posts.length,1);
 await cancel();eq(posts.length,2);eq(posts[1].version,'e'.repeat(64));eq(posts[1].attempt,'f'.repeat(64));ok(posts[0].requestId!==posts[1].requestId);
 seed();authorized=false;writeNote('인증 만료 시 보존');await cancel();eq(states[0],null);eq(states[3],'인증 만료 시 보존');eq(rpcCalls.length,0);eq(posts.length,1);eq(states[5],true);
 authorized=true;await refresh();eq(states[5],false);eq(states[3],'인증 만료 시 보존');eq(posts.length,1);
 seed();states[1]=true;eq(button('만료 작업 취소·재검토').props.disabled,true);seed();states[2]=true;eq(button('만료 작업 취소·재검토').props.disabled,true);
 console.log(`Expired cancellation component: ${checks} checks passed. Real component/handler, fake Auth/RPC; network/DB/AI 0.`);
}finally{globalThis.fetch=oldFetch;net.Socket.prototype.connect=oldConnect;}
