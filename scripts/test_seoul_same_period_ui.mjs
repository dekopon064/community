// Actual review panel handlers with synthetic facts/Auth responses. No network.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
const root=fileURLToPath(new URL('../',import.meta.url));
let states=[],refs=[],cursor=0,refCursor=0;
const fakeReact={...React,useState(initial){const i=cursor++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return [states[i],v=>{states[i]=typeof v==='function'?v(states[i]):v;}];},useRef(initial){return refs[refCursor++]??={current:initial};},useEffect(){}};
const cache=new Map();
function load(name){const filename=path.join(root,name);if(cache.has(filename))return cache.get(filename);const exports={};cache.set(filename,exports);
 const code=ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
 new Function('require','exports',code)(s=>{if(s.endsWith('.css'))return {};if(s==='react')return fakeReact;if(s==='next/link')return {default:()=>null};
  if(s.startsWith('@/')||s.startsWith('.')){const file=s.startsWith('@/')?path.join(root,s.slice(2)):path.resolve(path.dirname(filename),s);for(const suffix of ['.ts','.tsx',''])if(fs.existsSync(file+suffix))return load(path.relative(root,file+suffix));}return require(s);},exports);return exports;}
const {programItem}=load('app/lib/review/program-store.ts');
const {ProgramReviewStore}=load('app/lib/review/program-store.ts');
const {programRequest}=load('app/lib/review/program-handlers.ts');
const {AdminAccessError}=load('app/lib/auth/admin-policy.ts');
const Panel=load('app/components/admin/ProgramReviewPanel.tsx').default;

const raw=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','scripts/test_seoul_review_connections.py','--export-ui'],{cwd:root,encoding:'utf8'}));
const item=programItem(raw,raw.id),id=item.id,actor='00000000-0000-4000-8000-000000000001';
const {buildProgramSave,canReconfirmProgramPeriods}=load('app/lib/review/program-ui.ts');
let checks=0,calls=[],row=structuredClone(raw),rpcError=null;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const ok=v=>{assert.ok(v);checks++;};
const Decision=load('app/components/admin/ProgramPeriodDecision.tsx').default;
const nodes=t=>[t,...React.Children.toArray([t?.props?.children,t?.props?.overview]).flatMap(c=>typeof c==='object'?nodes(c):[])];
const store=new ProgramReviewStore({async rpc(name,args){
 calls.push({name,args});eq(name,'admin_program_period_decision');eq(args.p_actor,actor);
 if(rpcError)return {data:null,error:{code:rpcError}};
 if(args.p_version!==row.version)return {data:null,error:{code:'PT409'}};
 const hold=args.p_decision==='hold';
 row={...row,version:'f'.repeat(64),factsVersion:row.factsVersion+1,
    facts:{...row.facts,...args.p_patch,missing:hold?row.facts.missing:[]},
    result:{...row.result,reasons:hold?row.result.reasons:[]},
    history:[{action:'save_facts',actor,at:'2026-11-17T00:00:00Z',note:'',fields:['period:'+args.p_decision]},...row.history]};
 return {data:row,error:null};
}});
const deps={authorize:async()=>({userId:actor}),store:()=>store},url=`https://example.test/api/admin/program-review/${id}`;
const requests=[];
globalThis.fetch=async(pathname,options)=>{eq(pathname,`/api/admin/program-review/${id}`);requests.push(JSON.parse(options.body));return programRequest(new Request(url,{...options,headers:{...options.headers,origin:'https://example.test'}}),id,deps);};
globalThis.requestAnimationFrame=()=>{};
function reset(evidence,dates){row=structuredClone(raw);row.facts.period_evidence=[evidence];row.source.body=row.facts.description='운영기간: '+evidence;
 for(const [index,key] of ['RCPTBGNDT','RCPTENDDT','SVCOPNBGNDT','SVCOPNENDDT'].entries()){
   const value=dates[index]+'+09:00';row.facts.periods[key]={raw:value,value,status:'ok',precision:'second'};
 }
 row.observedFacts=structuredClone(row.facts);
 states=[programItem(row,id),structuredClone(row.facts),false,false,false];refs=[];calls=[];requests.length=0;rpcError=null;
}
function panel(){cursor=0;refCursor=0;return Panel({id,onBlocked(){},onResult(){}});}
function decision(){const child=nodes(panel()).find(n=>n?.type===Decision);return child && Decision(child.props);}
function button(text){return nodes(decision()).find(n=>n?.type==='button'&&typeof n.props.children==='string'&&n.props.children===text);}
const tick=()=>new Promise(r=>setImmediate(r));
const tour=['2026년 11월 16일 14:00-16:00 / 2026년 11월 23일 14:00-16:00 (해당 일자 중 택 1)',
 ['2026-11-06T00:00:00','2026-11-23T00:00:00','2026-11-06T00:00:00','2026-11-23T00:00:00']];
const dance=['2026년 11월 7일(토) ~ 11월 28일(토), 매주 토요일 클래스당 총 4회',
 ['2026-11-04T16:01:00','2026-11-27T18:00:00','2026-11-04T00:00:00','2026-11-28T00:00:00']];
for(const [fixture,expected] of [[tour,'2026-11-16'],[dance,'2026-11-07']]){
 reset(...fixture);const saved=structuredClone(row);let view=decision();
 ok(nodes(view).some(n=>n?.props?.children===saved.source.body));ok(!nodes(panel()).some(n=>n?.type==='input'&&n.props.type==='checkbox'));
 const proposed=nodes(view).find(n=>n?.type==='button'&&Array.isArray(n.props.children)&&n.props.children.includes('로 수정'));ok(proposed&&!proposed.props.disabled);
 proposed.props.onClick();await tick();await tick();
 eq(requests.length,1);eq(calls.length,1);eq(calls[0].args.p_resolve,['body_period_needs_confirmation']);eq(requests[0].periodDecision,'edit');
 eq(states[0].facts.periods.SVCOPNBGNDT.value,expected);eq(states[0].facts.periods.SVCOPNBGNDT.precision,'day');
 for(const key of ['RCPTBGNDT','RCPTENDDT','SVCOPNENDDT'])eq(states[0].facts.periods[key],saved.facts.periods[key]);
 eq(states[0].observedFacts,saved.observedFacts);eq(decision(),undefined);
}
for(const evidence of [
 dance[0].replace("28일(토)","28일(금)"),
 tour[0]+" (변경 가능)",
 "일정 미정",
]){
 reset(evidence,tour[1]);
 ok(!nodes(decision()).some(n=>n?.type==='button'&&Array.isArray(n.props.children)&&n.props.children.includes('로 수정')));
 ok(button('보류')&&!button('보류').props.disabled);
}
reset(...tour);states[0].source.body="다른 내용";ok(!nodes(decision()).some(n=>n?.type==='button'&&Array.isArray(n.props.children)&&n.props.children.includes('로 수정')));
reset(...tour);const initial=structuredClone(row.facts.periods);
button('보류').props.onClick();await tick();await tick();eq(calls.length,1);eq(states[0].facts.periods,initial);eq(button('보류').props.disabled,true);
button('현재 값 유지').props.onClick();await tick();await tick();eq(calls.length,2);eq(states[0].facts.periods,initial);eq(states[0].history[1].fields,['period:hold']);eq(decision(),undefined);
reset(...tour);let view=decision();
nodes(view).find(n=>n?.props?.id==='decision-SVCOPNBGNDT').props.onChange({target:{value:'2026-11-12T09:30'}});
eq(button('현재 값 유지').props.disabled,true);eq(button('입력한 날짜로 수정').props.disabled,false);
button('입력한 날짜로 수정').props.onClick();await tick();await tick();eq(states[0].facts.periods.SVCOPNBGNDT.value,'2026-11-12T09:30:00+09:00');
for(const code of ['PT409','PT422','PT500']){reset(...tour);rpcError=code;button('현재 값 유지').props.onClick();await tick();await tick();eq(requests.length,1);eq(calls.length,1);eq(states[1],row.facts);ok(button('보류'));}
reset(...dance);states[3]=true;eq(button('현재 값 유지').props.disabled,true);states[3]=false;states[4]=true;eq(button('보류').props.disabled,true);
const command={...buildProgramSave(item,item.facts,'',['body_period_needs_confirmation']),periodDecision:'keep'};
for(const denied of ['signed_out','forbidden','auth_error']){const n=calls.length;const response=await programRequest(new Request(url,{method:'POST',headers:{origin:'https://example.test','content-type':'application/json'},body:JSON.stringify(command)}),id,{...deps,authorize:async()=>{throw new AdminAccessError(denied);}});eq(response.status,{signed_out:401,forbidden:403,auth_error:503}[denied]);eq(calls.length,n);}
eq((await programRequest(new Request(url,{method:'POST',headers:{origin:'https://evil.test','content-type':'application/json'},body:JSON.stringify(command)}),id,deps)).status,403);
console.log(JSON.stringify({checks,result:'passed',realPanel:true,fakeAuthRpc:true,network:0,ai:0}));
