// Actual UI, validation and handler modules with fake Auth/RPC only.
import assert from 'node:assert/strict';
import fs from 'node:fs';import path from 'node:path';import {createRequire} from 'node:module';import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url)),require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
const cache=new Map();function load(name){const file=path.resolve(root,name);if(cache.has(file))return cache.get(file);const out={};cache.set(file,out);new Function('require','exports',ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText)(s=>{if(s.startsWith('@/')||s.startsWith('.')){const p=s.startsWith('@/')?path.join(root,s.slice(2)):path.resolve(path.dirname(file),s);for(const ext of ['.ts','.tsx',''])if(fs.existsSync(p+ext))return load(path.relative(root,p+ext));}return require(s);},out);return out;}
let checks=0;const ok=v=>{assert.ok(v);checks++;},eq=(a,b)=>{assert.deepEqual(a,b);checks++;},deny=f=>{assert.throws(f);checks++;};
const {emptyContentFilters,parseContentFilters,missingContentFilters}=load('app/lib/contentFilters.ts');
const {filterCommand,filterDetail,ContentFilterStore}=load('app/lib/review/content-filter-store.ts');
const {classificationCommand,classificationMissing}=load('app/lib/review/classification.ts');
const {FilterInputs,filterSaveBody}=load('app/components/admin/FilterReviewPanel.tsx');
const known=value=>({status:'known',value}),day=value=>({value,precision:'day'}),revision='a'.repeat(64),version='b'.repeat(64),id='40000000-0000-4000-8000-000000000901';
const data={...emptyContentFilters('program'),topic:known('language_learning'),delivery:known('online'),audience:known('other'),location:{status:'not_applicable',value:null},application:known({deadlineKind:'fixed',start:day('2026-10-01'),end:day('2026-10-31'),sourceStatus:'unknown'})};
const info={schema:data.schema,revision,filterVersion:1,data,missing:[],origins:{}},command={revision,version,filterVersion:1,data,fields:['application']};
const facts={productType:'event_program',category:'program',scope:'nationwide',regions:[],evidence:'합성 원문: 전국 대상',foreignEligibility:'unknown',delivery:'online',deadlineKind:'fixed',deadlineOn:'2026-10-31',eventStart:'',eventEnd:''};
const classification={revision,version,classificationVersion:0,facts,filters:data,note:'합성 원문을 확인한 프로그램 분류입니다.'};
eq(filterCommand(command),command);eq(classificationCommand(classification),classification);eq(classificationMissing(facts,data),[]);eq(missingContentFilters(data),[]);
for(const application of [{...data.application.value,start:null},{deadlineKind:'none',start:null,end:null,sourceStatus:'unknown'}]){
 const legacy={...data,application:known(application)};eq(parseContentFilters(legacy),legacy);ok(missingContentFilters(legacy).includes('application'));ok(classificationMissing(facts,legacy).includes('filter:application'));
 deny(()=>filterCommand({...command,data:legacy}));deny(()=>filterSaveBody(info,version,legacy,['application']));deny(()=>classificationCommand({...classification,filters:legacy}));
 eq(filterCommand({...command,data:legacy,fields:['topic']}).data,legacy);eq(filterDetail({...info,data:legacy,id,version,editable:true},id).data,legacy);
}
for(const start of [null,day('2026-11-01'),day('2026-02-30')])deny(()=>filterCommand({...command,data:{...data,application:known({...data.application.value,start})}}));
deny(()=>filterCommand({...command,data:{...data,application:known({...data.application.value,end:null})}}));
deny(()=>classificationCommand({...classification,facts:{...facts,deadlineKind:'none',deadlineOn:''}}));
const minute={value:'2026-10-31T18:00:00+09:00',precision:'minute'};eq(filterCommand({...command,data:{...data,application:known({...data.application.value,end:minute})}}).data.application.value.end,minute);
let calls=[];await new ContentFilterStore({rpc:async(name,args)=>{calls.push({name,args});return{error:null,data:{...info,id,version,editable:true,filterVersion:2}};}}).save(id,filterCommand(command),id);eq(calls.length,1);eq(calls[0].args.p_patch,{application:data.application});eq(calls[0].args.p_actor,id);ok(!calls.some(c=>/ai|claim|publish|enqueue/.test(c.name)));
const nodes=t=>[t,...React.Children.toArray(t?.props?.children).flatMap(c=>typeof c==='object'?nodes(c):[])];
let edited;const tree=FilterInputs({data,fields:['application'],disabled:false,onChange:v=>edited=v});
ok(!nodes(tree).some(n=>n?.type==='select'));const endpoints=nodes(tree).filter(n=>typeof n?.type==='function'&&n.props.label?.startsWith('신청 '));eq(endpoints.length,2);
for(const node of endpoints){ok(node.props.required);const expanded=node.type(node.props);const input=nodes(expanded).find(n=>n?.type==='input'&&n.props.type==='date');ok(input.props.required);eq(nodes(expanded).find(n=>n?.props?.type==='checkbox').props.checked,false);}
endpoints[0].props.onChange(day('2026-10-02'));eq(edited.application.value.start,day('2026-10-02'));eq(edited.application.value.deadlineKind,'fixed');eq(data.application.value.start,day('2026-10-01'));
const stale={...data,application:known({deadlineKind:'none',start:null,end:null,sourceStatus:'unknown'})};const staleTree=FilterInputs({data:stale,fields:['application'],disabled:false,onChange:v=>edited=v});eq(nodes(staleTree).filter(n=>typeof n?.type==='function'&&n.props.required).length,2);eq(stale.application.value.deadlineKind,'none');
const {myseoulReviewReasons}=load('app/components/admin/MySeoulReviewPanel.tsx');
const reasons=myseoulReviewReasons({reasonGuidance:[{code:'content_filter:topic',text:'분야',supported:false}],filterInfo:{missing:['topic','application']}});eq(reasons.map(r=>r.code),['content_filter:topic','content_filter:application']);
console.log(JSON.stringify({checks,syntheticOnly:true,externalConnections:0,result:'passed'}));
