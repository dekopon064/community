// Actual queue component and Auth handler; synthetic RPC and React, no network.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
const root=fileURLToPath(new URL('../',import.meta.url));
net.Socket.prototype.connect=()=>{throw Error('network forbidden');};
let states=[],refs=[],cursor=0,refCursor=0,effects=[];
const fakeReact={...React,useState(initial){const i=cursor++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return [states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef(initial){return refs[refCursor++]??={current:initial};},useEffect(fn){effects.push(fn);},useCallback(fn){return fn;}};
const cache=new Map();
function load(name){const filename=path.join(root,name);if(cache.has(filename))return cache.get(filename);if(filename.endsWith('.css'))return {};const exports={};cache.set(filename,exports);
 const code=ts.transpileModule(fs.readFileSync(filename,'utf8'),{fileName:filename,compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
 new Function('require','exports',code)(s=>{if(s==='react')return fakeReact;if(s==='next/link')return {default:()=>null};if(s.startsWith('@/')||s.startsWith('.')){const file=s.startsWith('@/')?path.join(root,s.slice(2)):path.resolve(path.dirname(filename),s);for(const suffix of ['.ts','.tsx',''])if(fs.existsSync(file+suffix))return load(path.relative(root,file+suffix));}return require(s);},exports);return exports;}
const Panel=load('app/components/admin/AiQueuePanel.tsx').default;
const {readAiQueue}=load('app/lib/review/ai-handlers.ts'),{DatabaseAiQueueStore}=load('app/lib/review/ai-queue.ts');
const {AdminAccessError}=load('app/lib/auth/admin-policy.ts');
let checks=0,reads=0,rpcs=0,authorized=true,unavailable=false,onReviewCalls=0;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;},ok=v=>{assert.ok(v);checks++;};
const nodes=t=>[t,...React.Children.toArray(t?.props?.children).flatMap(child=>typeof child==='object'?nodes(child):[])];
const text=t=>typeof t==='string'||typeof t==='number'?String(t):React.Children.toArray(t?.props?.children).map(text).join('');
function row(n,status='queued'){
 return {jobId:`10000000-0000-4000-8000-${String(n).padStart(12,'0')}`,sourceItemId:`20000000-0000-4000-8000-${String(n).padStart(12,'0')}`,revision:'a'.repeat(64),currentRevision:true,status,title:'합성 '+status+' '+n,sourceName:'seoul_reservation',completedAt:null,retryCount:0,nextRetryAt:null,leaseState:status==='claimed'?'expired':'none',errorCode:null,resultState:null};
}
const ready=row(1),claimed=row(2,'claimed'),failed=row(3,'failed'),held=row(4,'cancelled'),blocked=row(5);
const snapshot={checkedAt:'2026-10-15T00:00:00Z',items:[ready,claimed,failed],held:[held],observed:[],hasMore:false};
const deps={authorize:async()=>{if(!authorized)throw new AdminAccessError('signed_out');return {userId:ready.sourceItemId};},store:()=>new DatabaseAiQueueStore({async rpc(name,args){rpcs++;eq(name,'admin_review_ai_queue');if(unavailable)throw Error('unknown RPC response');return {data:{...snapshot,observed:args.p_watch.map(id=>id===blocked.jobId?blocked:[ready,claimed,failed,held].find(j=>j.jobId===id))},error:null};}})};
globalThis.fetch=async(url,options)=>{reads++;eq(options.method,undefined);eq(options.cache,'no-store');eq(options.credentials,'same-origin');return readAiQueue(new Request('https://example.test'+url),deps);};
function render(){cursor=0;refCursor=0;effects=[];return Panel({active:true,onBusy(){},onReview(){onReviewCalls++;}});}
function section(label){return nodes(render()).find(n=>n?.type==='section'&&n.props['aria-label']===label);}
function button(label){const n=nodes(render()).find(n=>n?.type==='button'&&text(n)===label);ok(n);return n;}
function seed(s=null){states=[null,false,s,0,false,'','','local-fixture'];refs=[];render();}
async function refresh(){button('새로고침').props.onClick();await new Promise(resolve=>setImmediate(resolve));}
seed(snapshot);
ok(text(section('실행 가능한 대기 항목')).includes(ready.title));
for(const job of [claimed,failed,held]){ok(!text(section('실행 가능한 대기 항목')).includes(job.title));ok(text(section('처리·실패·재검토 상태')).includes(job.title));}
ok(!text(render()).includes(blocked.title));ok(text(render()).includes('사람 사실 review'));
await refresh();eq(reads,1);eq(rpcs,1);eq(onReviewCalls,0);
eq(states[2].items.map(j=>j.jobId),snapshot.items.map(j=>j.jobId));
// Selection and recovery detail still work for an expired attempt.
const recoveryButton=nodes(section('처리·실패·재검토 상태')).find(n=>n?.type==='button');recoveryButton.props.onClick();eq(states[0],claimed.jobId);
ok(nodes(render()).some(n=>n?.type?.name==='AiQueueReview'&&n.props.jobId===claimed.jobId));
seed({...snapshot,items:[claimed,failed]});
ok(text(render()).includes('현재 AI 작업 대기 항목이 없습니다.'));ok(section('처리·실패·재검토 상태'));ok(!section('실행 가능한 대기 항목'));
seed(snapshot);unavailable=true;const n=reads;await refresh();eq(reads,n+1);eq(states[2],snapshot);eq(states[5],'unavailable');ok(text(render()).includes('마지막으로 확인한 상태'));eq(onReviewCalls,0);
unavailable=false;authorized=false;const oldRpc=rpcs;await refresh();eq(states[2],null);eq(states[0],null);eq(rpcs,oldRpc);
authorized=true;seed(snapshot);states[1]=true;eq(button('새로고침').props.disabled,true);eq(button('다음 목록').props.disabled,true);
eq(onReviewCalls,0);
console.log('AI-ready component/Auth/fake RPC checks:',checks,'write/AI/retry calls: 0');
