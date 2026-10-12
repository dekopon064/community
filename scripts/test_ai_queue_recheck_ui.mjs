// Actual component handlers, fake React state and fetch. No network/Auth/DB.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
const root=fileURLToPath(new URL('../',import.meta.url));
let states=[],refs=[],cursor=0,refCursor=0,focuses=0,effects=[];
const fakeReact={...React,useState(initial){const i=cursor++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return [states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef(initial){return refs[refCursor++]??={current:initial};},useEffect(fn){effects.push(fn);},useCallback(fn){return fn;}};
const cache=new Map();
function load(name){const filename=path.join(root,name);if(cache.has(filename))return cache.get(filename);if(filename.endsWith('.css'))return {};const exports={};cache.set(filename,exports);
 const code=ts.transpileModule(fs.readFileSync(filename,'utf8'),{fileName:filename,compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
 new Function('require','exports',code)(s=>{if(s==='react')return fakeReact;if(s==='next/link')return {default:()=>null};
  if(s.startsWith('@/')||s.startsWith('.')){const file=s.startsWith('@/')?path.join(root,s.slice(2)):path.resolve(path.dirname(filename),s);for(const suffix of ['.ts','.tsx',''])if(fs.existsSync(file+suffix))return load(path.relative(root,file+suffix));}return require(s);},exports);return exports;}
const Panel=load('app/components/admin/AiQueueReview.tsx').default;
const {LocalAiReviewStore}=load('app/lib/review/ai-review-fixture.ts');
const store=new LocalAiReviewStore(),id='10000000-0000-4000-8000-000000000001',initial=await store.get(id);
let checks=0,posts=0,reads=0,changed=0,closed=0,reviewed=0;const ok=v=>{assert.ok(v);checks++;};const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const nodes=t=>[t,...React.Children.toArray(t?.props?.children).flatMap(child=>typeof child==='object'?nodes(child):[])];
const text=t=>typeof t==='string'||typeof t==='number'?String(t):React.Children.toArray(t?.props?.children).map(text).join('');
const props={jobId:id,onBusy(){},onChanged(){changed++;},onClose(){closed++;},onReview(){reviewed++;}};
function render(){cursor=0;refCursor=0;effects=[];return Panel(props);}
function button(label){const n=nodes(render()).find(n=>n?.type==='button'&&text(n)===label);ok(n);return n;}
function seed(item=initial){states=[structuredClone(item),false,false,'','',false,null,''];refs=[];}
seed();button('닫기').props.onClick();eq(closed,1);let tree=render(),ns=nodes(tree);ok(ns.findIndex(n=>n?.type==='details')<ns.findIndex(n=>n?.type==='dl'));eq(ns.find(n=>n?.type==='details').props.open,undefined);eq(button('AI 대기 보류·재검토로 보내기').props.disabled,true);
ns.find(n=>n?.type==='textarea').props.onChange({target:{value:'보호자 조건 재검토'}});eq(states[3],'보호자 조건 재검토');eq(button('닫기').props.disabled,true);
const trigger={focus(){focuses++;}};button('AI 대기 보류·재검토로 보내기').props.onClick({currentTarget:trigger});eq(states[6],'request_recheck');
nodes(render()).find(n=>n?.props?.['aria-label']==='재검토 최종 확인').props.onKeyDown({key:'Escape'});eq(states[6],null);eq(focuses,1);eq(states[3],'보호자 조건 재검토');
button('AI 대기 보류·재검토로 보내기').props.onClick({currentTarget:trigger});
let release;const waiting=new Promise(resolve=>release=resolve);
const oldFetch=globalThis.fetch;globalThis.fetch=async(_url,options)=>{if(options?.method==='POST'){posts++;await waiting;return Response.json({mode:'local-fixture',item:await store.execute(id,JSON.parse(options.body),'synthetic-actor')});}reads++;return Response.json({mode:'local-fixture',item:await store.get(id)});};
const save=button('확인하고 저장').props.onClick;const one=save();await save();eq(posts,1);release();await one;await new Promise(r=>setImmediate(r));eq(changed,1);eq(states[0].status,'cancelled');eq(states[0].recheckPending,true);eq(states[3],'');eq(states[0].values,initial.values);
button('사실 검토에서 수정').props.onClick();eq(reviewed,1);button('재검토 완료').props.onClick({currentTarget:trigger});button('취소').props.onClick();eq(states[6],null);eq(states[0].recheckPending,true);
// Unknown write outcome: preserve draft; no second write, recovery is GET only.
seed();states[3]='유지할 재검토 사유';button('AI 대기 보류·재검토로 보내기').props.onClick({currentTarget:trigger});
globalThis.fetch=async()=>{posts++;throw Error('timeout');};await button('확인하고 저장').props.onClick();await new Promise(r=>setImmediate(r));eq(states[3],'유지할 재검토 사유');eq(states[5],true);eq(button('AI 대기 보류·재검토로 보내기').props.disabled,true);eq(button('닫기').props.disabled,true);eq(posts,2);
globalThis.fetch=async()=>{reads++;return Response.json({mode:'local-fixture',item:await store.get(id)});};
const recover=button('입력을 유지하고 최신 상태 확인').props.onClick();await recover;await new Promise(r=>setImmediate(r));eq(states[5],false);eq(states[3],'유지할 재검토 사유');eq(reads,1);eq(posts,2);
ok(text(render()).includes('보존한 사유 입력'));button('보존한 사유 입력 취소').props.onClick();eq(states[3],'');
// A committed unknown response is reconciled by reading the same server note.
seed(await store.get(id));states[3]=states[0].note;button('입력을 유지하고 최신 상태 확인').props.onClick();await new Promise(r=>setImmediate(r));eq(states[3],'');eq(posts,2);
states[3]='보존할 사유';
// Authorization loss removes protected source/facts while retaining the note.
globalThis.fetch=async()=>Response.json({code:'signed_out'},{status:401});button('입력을 유지하고 최신 상태 확인').props.onClick();await new Promise(r=>setImmediate(r));eq(states[0],null);eq(states[3],'보존할 사유');
seed({...initial,status:'claimed',canRecheck:false});ok(!nodes(render()).some(n=>n?.type==='textarea'));ok(!text(render()).includes('AI 대기 보류·재검토로 보내기'));
// Actual workspace callback routes each source to its existing facts panel.
const Workspace=load('app/components/admin/ReviewWorkspace.tsx').default;
function workspace(){cursor=0;refCursor=0;effects=[];return Workspace();}
function resetWorkspace(){states=[];refs=[];workspace();states[0]='ai';states[10]=false;}
for(const [source,slot,other] of [['seoul_reservation',3,4],['myseoul_program',4,3]]){
 resetWorkspace();const ai=nodes(workspace()).find(n=>n?.type?.name==='AiQueuePanel');ok(ai);
 ai.props.onReview({...initial,sourceName:source,recheckPending:true,status:'cancelled'});eq(states[0],'facts');eq(states[slot],initial.sourceItemId);eq(states[other],null);states[10]=false;
 ok(nodes(workspace()).some(n=>n?.type?.name===(source==='seoul_reservation'?'ProgramReviewPanel':'MySeoulReviewPanel')));
}
resetWorkspace();let ai=nodes(workspace()).find(n=>n?.type?.name==='AiQueuePanel');ai.props.onReview(initial);eq(states[0],'ai');
ai.props.onBusy(true);ai=nodes(workspace()).find(n=>n?.type?.name==='AiQueuePanel');ai.props.onReview({...initial,recheckPending:true});eq(states[0],'ai');
resetWorkspace();states[18]='다른 초안';ai=nodes(workspace()).find(n=>n?.type?.name==='AiQueuePanel');ai.props.onReview({...initial,recheckPending:true});eq(states[0],'ai');eq(states[18],'다른 초안');
globalThis.fetch=oldFetch;
console.log(`AI queue component handlers: ${checks} checks passed. Fake fetch only; no DB/AI.`);
