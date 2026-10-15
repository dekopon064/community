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
 new Function('require','exports',code)(s=>{if(s==='react')return fakeReact;if(s==='next/link')return {default:()=>null};
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
const nodes=t=>[t,...React.Children.toArray([t?.props?.children,t?.props?.action]).flatMap(c=>typeof c==='object'?nodes(c):[])];
const store=new ProgramReviewStore({async rpc(name,args){calls.push({name,args});eq(name,'admin_program_save');
 if(rpcError)return {data:null,error:{code:rpcError}};
 if(args.p_version!==row.version)return {data:null,error:{code:'PT409'}};
 eq(args.p_actor,actor);eq(args.p_resolve,['body_period_needs_confirmation']);eq(args.p_patch,{periods:item.facts.periods});
 row={...row,version:'f'.repeat(64),factsVersion:row.factsVersion+1,facts:{...row.facts,missing:row.facts.missing.filter(x=>x!=='body_period_needs_confirmation')},result:{decision:'review_required',disposition:'observe_only',reasons:['activity_location_unknown']},history:[{action:'save_facts',actor,at:'2026-10-15T00:00:00Z',note:'',fields:['reconfirmed:periods','resolved:body_period_needs_confirmation']},...row.history]};
 return {data:row,error:null};}});
const deps={authorize:async()=>({userId:actor}),store:()=>store},url=`https://example.test/api/admin/program-review/${id}`;
const requests=[];
globalThis.fetch=async(pathname,options)=>{eq(pathname,`/api/admin/program-review/${id}`);requests.push(JSON.parse(options.body));return programRequest(new Request(url,{...options,headers:{...options.headers,origin:'https://example.test'}}),id,deps);};
globalThis.requestAnimationFrame=()=>{};
function reset(){states=[structuredClone(item),structuredClone(item.facts),false,false,false];refs=[];row=structuredClone(raw);calls=[];requests.length=0;rpcError=null;}
function render(){cursor=0;refCursor=0;return Panel({id,onBlocked(){},onResult(){}});}
function save(tree=render()){const n=nodes(tree).find(x=>x?.type==='button'&&x.props.type==='submit');ok(n);return n;}
function choose(){const n=nodes(render()).find(x=>x?.type==='input'&&x.props.type==='checkbox');ok(n);n.props.onChange({target:{checked:true}});}
const tick=()=>new Promise(r=>setImmediate(r));
reset();eq(save().props.disabled,true);choose();eq(save().props.disabled,false);eq(states[1],item.facts);
const command=buildProgramSave(item,item.facts,'',['body_period_needs_confirmation']);eq(command.patch,{periods:item.facts.periods});
for(const resolve of [[],['body_api_period_conflict'],['body_period_needs_confirmation','fee_conflict']])eq(canReconfirmProgramPeriods(item,resolve),false);
eq(canReconfirmProgramPeriods({...item,editableFields:[]},['body_period_needs_confirmation']),false);
const form=nodes(render()).find(n=>n?.type==='form');form.props.onSubmit({preventDefault(){}});await tick();await tick();
eq(requests.length,1);eq(calls.length,1);eq(states[0].facts.periods,item.facts.periods);eq(states[0].observedFacts,item.observedFacts);eq(states[0].source,item.source);eq(states[0].filterInfo,item.filterInfo);eq(states[0].factsVersion,item.factsVersion+1);eq(states[0].history.slice(1),item.history);eq(states[1],states[0].facts);
for(const code of ['PT409','PT422','PT500']){reset();choose();rpcError=code;nodes(render()).find(n=>n?.type==='form').props.onSubmit({preventDefault(){}});await tick();await tick();eq(requests.length,1);eq(calls.length,1);eq(states[1],item.facts);eq(states[9],['body_period_needs_confirmation']);}
reset();choose();states[3]=true;eq(save().props.disabled,true);states[3]=false;states[4]=true;eq(save().props.disabled,true);
for(const denied of ['signed_out','forbidden','auth_error']){const n=calls.length;const response=await programRequest(new Request(url,{method:'POST',headers:{origin:'https://example.test','content-type':'application/json'},body:JSON.stringify(command)}),id,{...deps,authorize:async()=>{throw new AdminAccessError(denied);}});eq(response.status,{signed_out:401,forbidden:403,auth_error:503}[denied]);eq(calls.length,n);}
const n=calls.length;eq((await programRequest(new Request(url,{method:'POST',headers:{origin:'https://evil.test','content-type':'application/json'},body:JSON.stringify(command)}),id,deps)).status,403);eq(calls.length,n);
console.log(JSON.stringify({checks,result:'passed',realPanel:true,fakeAuthRpc:true,network:0,ai:0,approval:0,publication:0}));
