// Actual panel -> handler -> store, with synthetic Auth/RPC. No live I/O.
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
const raw=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','scripts/test_seoul_review_evidence.py','--export'],{cwd:root,encoding:'utf8'}))[0][1];
const {filterInfo,ContentFilterStore}=load('app/lib/review/content-filter-store.ts');
const {contentFilterRequest}=load('app/lib/review/content-filter-handler.ts');
const {AdminAccessError}=load('app/lib/auth/admin-policy.ts');
const {default:Panel,filterFieldsToSave,filterSaveBody}=load('app/components/admin/FilterReviewPanel.tsx');
const info=filterInfo(raw.filterInfo,raw.revision),id=raw.id,actor='00000000-0000-4000-8000-000000000001';
const unknown={status:'unknown',value:null},known=value=>({status:'known',value});
let checks=0,calls=[],requests=[],rpcError=null,saved=0,row,authError=null;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;},ok=v=>{assert.ok(v);checks++;};
const nodes=t=>[t,...React.Children.toArray([t?.props?.children,t?.props?.action]).flatMap(c=>typeof c==='object'?nodes(c):[])];
const store=new ContentFilterStore({async rpc(name,args){calls.push({name,args});eq(name,'admin_content_filter_save');eq(args.p_actor,actor);
 if(rpcError)return {data:null,error:{code:rpcError}};
 if(args.p_version!==raw.version||args.p_filter_version!==info.filterVersion)return {data:null,error:{code:'PT409'}};
 row={...row,version:'f'.repeat(64),filterVersion:info.filterVersion+1,data:{...row.data,...args.p_patch},missing:row.missing.filter(k=>!Object.hasOwn(args.p_patch,k)),origins:{...row.origins,...Object.fromEntries(Object.keys(args.p_patch).map(k=>[k,'operator']))}};
 return {data:row,error:null};}});
const deps={authorize:async()=>{if(authError)throw new AdminAccessError(authError);return {userId:actor};},store:()=>store};
const url=`https://example.test/api/admin/review-filters/${id}`;
globalThis.fetch=async(p,options)=>{eq(p,`/api/admin/review-filters/${id}`);eq(options.cache,'no-store');requests.push(JSON.parse(options.body));
 const response=await contentFilterRequest(new Request(url,{...options,headers:{...options.headers,origin:'https://example.test'}}),id,deps);
 ok(response.headers.get('cache-control').includes('no-store'));return response;};
function reset(){states=[];refs=[];calls=[];requests=[];rpcError=null;authError=null;saved=0;row={...structuredClone(info),id,version:raw.version,editable:true};}
function render(extra={}){cursor=0;refCursor=0;return Panel({id,version:raw.version,info,disabled:false,onBlocked(){},onSaved:async()=>{saved++;},...extra});}
function choose(patch){nodes(render()).find(n=>n?.type?.name==='FilterInputs').props.onChange({...states[0],...patch});}
const button=t=>nodes(t??render()).find(n=>n?.type==='button'&&n.props.type==='submit');
const submit=()=>nodes(render()).find(n=>n?.type==='form').props.onSubmit({preventDefault(){}});
reset();eq(button().props.disabled,true);
choose({topic:known('culture_experience')});eq(button().props.disabled,false);
await submit();eq(requests.length,1);eq(calls.length,1);eq(saved,1);
eq(requests[0].fields,['topic']);eq(calls[0].args.p_patch,{topic:known('culture_experience')});
eq(calls[0].args.p_revision,raw.revision);eq(calls[0].args.p_version,raw.version);eq(calls[0].args.p_filter_version,info.filterVersion);
eq(row.origins.delivery,'automatic');eq(row.data.location,unknown);eq(row.data.application,info.data.application);
// The real parent remounts this panel on filterVersion after reloading detail.
states=[];refs=[];eq(button(render({info:row,version:row.version})).props.disabled,true);
reset();render();choose({topic:known('culture_experience')});nodes(render()).find(n=>n?.type==='button'&&n.props.children==='입력 취소').props.onClick();eq(states[0],info.data);eq(button().props.disabled,true);
choose({topic:known('culture_experience')});nodes(render()).find(n=>n?.type?.name==='SavedFilterValues').props.onEditing('topic');eq(button().props.disabled,true);
eq(button(render({disabled:true})).props.disabled,true);states[5]=null;states[1]=true;eq(button().props.disabled,true);
for(const code of ['PT409','PT422','PT500']){reset();render();choose({topic:known('culture_experience')});rpcError=code;const before=structuredClone(states[0]);await submit();eq(calls.length,1);eq(requests.length,1);eq(states[0],before);eq(saved,0);ok(states[2]);}
for(const code of ['signed_out','forbidden','auth_error']){reset();render();choose({topic:known('culture_experience')});authError=code;await submit();eq(calls.length,0);eq(requests.length,1);eq(saved,0);eq(states[0].topic,known('culture_experience'));}
reset();render();const changed={...info.data,topic:known('culture_experience')},command=filterSaveBody(info,raw.version,changed,['topic','delivery','location']);
eq(filterFieldsToSave({...info,data:changed},{...changed,topic:unknown},['topic','location']),['topic']);
eq(filterFieldsToSave({...info,data:changed},changed,['topic','location']),['topic']);
for(const origin of ['https://evil.test',null]){const headers={'content-type':'application/json'};if(origin)headers.origin=origin;
 const response=await contentFilterRequest(new Request(url,{method:'POST',headers,body:JSON.stringify(command)}),id,deps);eq(response.status,403);eq(calls.length,0);}
const response=await contentFilterRequest(new Request(url,{method:'POST',headers:{origin:'https://example.test','content-type':'application/json'},body:JSON.stringify({...command,version:'c'.repeat(64)})}),id,deps);eq(response.status,409);eq(calls.length,1);
console.log(JSON.stringify({checks,result:'passed',actualPanel:true,fakeAuthRpc:true,network:0,operatingWrites:0,ai:0,approval:0,publication:0}));
