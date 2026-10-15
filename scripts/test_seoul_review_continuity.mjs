// Actual review panel handlers with synthetic facts/Auth responses. No network.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
const root=fileURLToPath(new URL('../',import.meta.url));
let states=[],refs=[],cursor=0,refCursor=0,focuses=[];
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
const {programInputFields,preserveProgramDraft,displayProgramDate,programDateInput}=load('app/lib/review/program-ui.ts');
const Panel=load('app/components/admin/ProgramReviewPanel.tsx').default;
const samples=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','test_program_db.py','--fixtures'],{cwd:path.join(root,'scripts'),encoding:'utf8'}));
const facts=structuredClone(samples.fixtures[0].item.program_facts),id='30000000-0000-4000-8000-000000000001';
facts.activity_evidence=[];facts.activity_region='capital';
const item=programItem({id,revision:'a'.repeat(64),version:'b'.repeat(64),schema:'program-scope-v1-local',profile:'program_capital_v1_local',factsVersion:1,
 source:{name:'seoul_reservation',title:'합성 검토',url:facts.official_url,body:'합성 원문'},facts,observedFacts:facts,
 result:{decision:'review_required',disposition:'observe_only',reasons:['activity_location_unknown']},status:'open',aiStatus:'blocked',editableFields:['delivery_mode','activity_region','activity_evidence'],history:[]},id);
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};const ok=v=>{assert.ok(v);checks++;};
const nodes=t=>[t,...React.Children.toArray([t?.props?.children,t?.props?.action]).flatMap(child=>typeof child==='object'?nodes(child):[])];
const text=t=>typeof t==='string'||typeof t==='number'?String(t):React.Children.toArray(t?.props?.children).map(text).join('');
const originalFetch=globalThis.fetch,originalRAF=globalThis.requestAnimationFrame,originalDocument=globalThis.document;
globalThis.fetch=async()=>{throw Error('network forbidden');};
globalThis.requestAnimationFrame=fn=>{fn();};
globalThis.document={getElementById:()=>({closest(){return null;},focus(){focuses.push('input');},scrollIntoView(){}})};
function render(){cursor=0;refCursor=0;const tree=Panel({id,onBlocked(){},onResult(){}});return tree;}
function reset(){states=[structuredClone(item),structuredClone(item.facts),false,false,false];refs=[];}
function saved(){const tree=render(),node=nodes(tree).find(n=>n?.type?.name==='SavedProgramFacts');ok(node);return node.type(node.props);}
function button(tree,label){const node=nodes(tree).find(n=>n?.type==='button'&&(n.props['aria-label']===label||text(n)===label));ok(node);return node;}
try{
 eq(programInputFields(item),['activity_evidence']);
 const changed=structuredClone(facts);changed.activity_evidence=['확인한 서울 개최지'];
 const latest=structuredClone(facts);latest.source_status='reservation_closed';
 eq(preserveProgramDraft(facts,changed,latest,item.editableFields).activity_evidence,changed.activity_evidence);
 eq(preserveProgramDraft(facts,changed,latest,item.editableFields).source_status,'reservation_closed');
 eq(displayProgramDate({status:'ok',value:'2099-10-01',precision:'day'}),'2099.10.01');
 eq(displayProgramDate({status:'ok',value:'2099-10-01T01:02:03Z',precision:'second'}),'2099.10.01 10:02:03');
 eq(programDateInput({status:'ok',value:'2099-10-01T01:02:03Z',precision:'second'}),'2099-10-01T10:02:03');
 reset();let tree=render();const category=nodes(tree).find(n=>n?.type?.name==='ClassificationPanel');ok(text(category.props.reference).includes('합성 원문'));ok(text(category.props.overview).includes('이번에 확인할 사항'));
 const primary=nodes(tree).find(n=>n?.type?.name==='FactFields');eq(primary.props.editable,['activity_evidence']);
 const optionalField=nodes(primary.type(primary.props)).find(n=>n?.type?.name==='OptionalReviewText');ok(optionalField);eq(optionalField.props.value,'');
 optionalField.props.onChange('인용 한 줄');eq(states[1].activity_evidence,['인용 한 줄']);states[1]=structuredClone(item.facts);
 const optionalTree=optionalField.type({...optionalField.props,value:'보존된 인용'});
 eq(optionalTree.type,'details');ok(!optionalTree.props.open);
 const optionalInput=nodes(optionalTree).find(n=>n?.type==='textarea');ok(!optionalInput.props.required);eq(optionalInput.props.value,'보존된 인용');
 let focused=false,prevented=false;const disclosure={open:true,closest(){return null;},querySelector(){return {focus(){focused=true;}};}};
 optionalTree.props.onKeyDown({key:'Escape',currentTarget:disclosure,preventDefault(){prevented=true;}});eq(disclosure.open,false);ok(focused&&prevented);eq(optionalInput.props.value,'보존된 인용');
 prevented=false;disclosure.open=true;disclosure.closest=()=>({});optionalTree.props.onKeyDown({key:'Escape',currentTarget:disclosure,preventDefault(){prevented=true;}});ok(!prevented);eq(disclosure.open,true);
 let row=saved();ok(nodes(row).some(n=>n?.props?.value==='저장된 값 없음'));ok(nodes(row).filter(n=>n?.type?.name==='ReviewValueRow').every(n=>!n.props.status.props.confirmed));
 const regionRef=refs.at(-1);regionRef.current={querySelector:()=>({closest(){return null;},focus(){focuses.push('button');}})};
 button(row,'실제 개최 지역 수정').props.onClick();eq(states[3],true);row=saved();
 const editor=nodes(row).find(n=>n?.type?.name==='FactFields');eq(editor.props.prefix,'program-saved');
 editor.props.onChange({...editor.props.facts,activity_region:'noncapital'});
 button(saved(),'취소').props.onClick();eq(states[1].activity_region,'capital');eq(states[3],false);ok(focuses.includes('button'));
 button(saved(),'개최지의 원문 근거 입력하기').props.onClick();row=saved();
 const input=nodes(row).find(n=>n?.type?.name==='FactFields');input.props.onChange({...input.props.facts,activity_evidence:['서울 확인 근거']});
 button(saved(),'초안에 적용').props.onClick();eq(states[1].activity_evidence,['서울 확인 근거']);eq(states[0].facts.activity_evidence,[]);eq(states[3],false);
 ok(nodes(saved()).some(n=>n?.props?.changedValue==='서울 확인 근거'));
 button(saved(),'실제 개최 지역 수정').props.onClick();row=saved();nodes(row).find(n=>n?.props?.role==='group').props.onKeyDown({key:'Escape',preventDefault(){},stopPropagation(){}});
 eq(states[1].activity_evidence,['서울 확인 근거']);eq(states[3],false);
 states[5]='conflict';let reads=0;
 globalThis.fetch=async(url,options)=>{eq(url,`/api/admin/program-review/${id}`);eq(options.cache,'no-store');eq(options.credentials,'same-origin');ok(!options.method);reads++;return new Response(JSON.stringify({mode:'database',item:{...states[0],version:'c'.repeat(64),facts:latest}}));};
 button(render(),'입력을 유지하고 저장 상태 확인').props.onClick();await new Promise(r=>setImmediate(r));
 eq(reads,1);eq(states[1].activity_evidence,['서울 확인 근거']);eq(states[1].source_status,'reservation_closed');eq(states[0].version,'c'.repeat(64));
 states[5]='unavailable';globalThis.fetch=async()=>{throw Error('ambiguous');};
 button(render(),'입력을 유지하고 저장 상태 확인').props.onClick();await new Promise(r=>setImmediate(r));eq(states[1].activity_evidence,['서울 확인 근거']);
 // Existing filters use the ordinary save flow even with a legacy pending flag.
 const activityData={schema:'content-filters-v1',category:'program',topic:{status:'known',value:'culture_experience'},audience:{status:'known',value:'other'},foreignerProgram:{status:'unknown',value:null},application:{status:'known',value:{deadlineKind:'fixed',start:{value:facts.periods.RCPTBGNDT.value,precision:facts.periods.RCPTBGNDT.precision},end:{value:facts.periods.RCPTENDDT.value,precision:facts.periods.RCPTENDDT.precision},sourceStatus:'open'}},spaceKind:{status:'not_applicable',value:null},schedule:{status:'not_applicable',value:null},location:{status:'known',value:{scope:'specific',venues:[{province:'11',district:null,facility:'',address:''}]}},delivery:{status:'known',value:'onsite'}};
 const capable={...item,activityReview:{supported:true,pending:true,confirmed:false},filterInfo:{schema:'content-filters-v1',revision:item.revision,filterVersion:1,data:activityData,missing:[],origins:{delivery:'operator',location:'operator'}}};
 reset();states[0]=capable;tree=render();
 let overview=nodes(tree).find(n=>n?.type?.name==='ClassificationPanel').props.overview;
 ok(text(overview).includes('아래 필터 저장값으로 판정'));ok(!text(overview).includes('확인 근거'));
 let jump=nodes(overview).find(n=>n?.props?.href==='#review-filter-delivery');ok(jump);
 globalThis.document={getElementById:()=>({querySelector:()=>({closest(){return null;},focus(){focuses.push('filter');},scrollIntoView(){}})})};
 jump.props.onClick({preventDefault(){}});ok(focuses.includes('filter'));
 ok(!nodes(tree).some(n=>n?.type?.name==='ProgramActivityConfirmation'));ok(!nodes(tree).some(n=>n?.type?.name==='FactFields'));
 let filter=nodes(tree).find(n=>n?.type?.name==='FilterReviewPanel');eq(filter.props.reviewFields,['delivery','location']);eq(filter.props.info.data,activityData);
 states[0]={...capable,facts:{...facts,delivery_mode:'unknown',activity_region:'unknown'},result:{...item.result,reasons:['delivery_mode_unknown']}};
 states[1]=structuredClone(states[0].facts);tree=render();
 filter=nodes(tree).find(n=>n?.type?.name==='FilterReviewPanel');eq(filter.props.reviewFields,['delivery','location']);
 ok(!nodes(tree).some(n=>n?.type?.name==='FactFields'));ok(!text(tree).includes('진행 방식·개최 지역 확인 근거'));
 // Other unresolved facts are still editable; only the duplicated venue inputs disappear.
 states[0]={...states[0],editableFields:[...item.editableFields,'residence_scope'],result:{...item.result,reasons:['delivery_mode_unknown','residence_scope_unknown']},facts:{...states[0].facts,residence_scope:'unknown'}};
 states[1]=structuredClone(states[0].facts);tree=render();eq(nodes(tree).find(n=>n?.type?.name==='FactFields').props.editable,['residence_scope']);
 // A filter save reloads the server result; the UI never invents fact completion.
 const serverResult={...states[0],version:'d'.repeat(64),facts:{...states[0].facts,delivery_mode:'offline',activity_region:'capital'},result:{...item.result,reasons:['residence_scope_unknown']}};
 let readsAfterSave=0;globalThis.fetch=async(url,opt)=>{eq(url,`/api/admin/program-review/${id}`);ok(!opt.method);readsAfterSave++;return new Response(JSON.stringify({mode:'database',item:serverResult}));};
 await filter.props.onSaved();eq(readsAfterSave,1);eq(states[0].result.reasons,['residence_scope_unknown']);eq(states[0].facts.delivery_mode,'offline');
 // The existing filter form submits the unchanged values in one ordinary
 // request: no note, extra checkbox, confirmation RPC or automatic retry.
 const Filter=load('app/components/admin/FilterReviewPanel.tsx').default;
 const props={...filter.props,onSaved:async()=>{savedCount++;}};let savedCount=0,posts=0,packet;
 states=[];refs=[];function filters(){cursor=0;refCursor=0;return Filter(props);}
 let ft=filters();eq(button(ft,'이 값으로 확인·저장').props.disabled,false);
 ok(!nodes(ft).some(n=>n?.type==='textarea'));
 let complete;globalThis.fetch=(url,opt)=>{eq(url,`/api/admin/review-filters/${id}`);eq(opt.method,'POST');packet=JSON.parse(opt.body);posts++;return new Promise(r=>complete=r);};
 const form=nodes(ft).find(n=>n?.type==='form');const submitting=form.props.onSubmit({preventDefault(){}});
 await form.props.onSubmit({preventDefault(){}});eq(posts,1);eq(packet.fields,['delivery','location']);ok(!('note' in packet));eq(packet.data,activityData);
 complete(new Response(JSON.stringify({item:{...props.info,id,version:'e'.repeat(64),filterVersion:2,editable:false}})));await submitting;eq(savedCount,1);
 // Ambiguous responses and session errors preserve edited input, without
 // pretending that the server completed the fact review.
 const edited=structuredClone(activityData);edited.location.value.venues[0].district='종로구';
 nodes(filters()).find(n=>n?.type?.name==='FilterInputs').props.onChange(edited);
 globalThis.fetch=async()=>{posts++;return new Response('ambiguous');};
 await nodes(filters()).find(n=>n?.type==='form').props.onSubmit({preventDefault(){}});
 eq(posts,2);eq(savedCount,1);eq(states[0],edited);ok(states[2].includes('자동 재시도하지'));
 globalThis.fetch=async()=>{posts++;return new Response(JSON.stringify({code:'signed_out'}),{status:401});};
 await nodes(filters()).find(n=>n?.type==='form').props.onSubmit({preventDefault(){}});eq(posts,3);eq(savedCount,1);eq(states[0],edited);
 // A saved-row change must be saveable without any unresolved input field.
 // Exercise the actual row editor, panel submit, Auth handler and fake RPC.
 globalThis.document={getElementById:()=>({closest(){return null;},focus(){focuses.push('input');},scrollIntoView(){}})};
 const held=programItem({...item,facts:{...facts,description:'합성 설명. 기존 예약·참가 조건 보존.'},observedFacts:structuredClone(facts),
  result:{decision:'in_scope',disposition:'target',reasons:['ai_recheck_requested']},aiStatus:'cancelled',
  editableFields:['description','target_raw'],filterInfo:capable.filterInfo},id);
 let backend,authError=null,rpcCalls=[],saveRequests=[];
 const fakeStore=new ProgramReviewStore({async rpc(name,args){
  rpcCalls.push({name,args});
  if(name==='admin_program_detail')return {data:backend,error:null};
  eq(name,'admin_program_save');
  if(args.p_revision!==backend.revision||args.p_version!==backend.version)return {data:null,error:{code:'PT409'}};
  if(backend.aiStatus==='claimed'||Object.keys(args.p_patch).some(k=>!backend.editableFields.includes(k)))return {data:null,error:{code:'PT409'}};
  backend={...backend,version:'d'.repeat(64),factsVersion:backend.factsVersion+1,facts:{...backend.facts,...args.p_patch},
   filterInfo:{...backend.filterInfo,filterVersion:2,missing:['topic'],data:{...backend.filterInfo.data,topic:{status:'unknown',value:null}}}};
  return {data:backend,error:null};
 }});
 const deps={authorize:async()=>{if(authError)throw new AdminAccessError(authError);return {userId:'10000000-0000-4000-8000-000000000001'};},store:()=>fakeStore};
 function seedHeld(next=held){states=[structuredClone(next),structuredClone(next.facts),false,false,false];refs=[];backend=structuredClone(next);authError=null;rpcCalls=[];saveRequests=[];}
 function changeRow(label,key,value){button(saved(),label+' 수정').props.onClick();const editor=nodes(saved()).find(n=>n?.type?.name==='FactFields');ok(editor);editor.props.onChange({...editor.props.facts,[key]:value});button(saved(),'초안에 적용').props.onClick();}
 function saveForm(){const form=nodes(render()).find(n=>n?.type==='form');ok(form);return form;}
 const tick=()=>new Promise(r=>setImmediate(r));
 globalThis.fetch=async(url,opt={})=>{
  eq(url,`/api/admin/program-review/${id}`); // Any other source/AI/DB/network route fails.
  if(opt.method==='POST')saveRequests.push(JSON.parse(opt.body));
  return programRequest(new Request('https://example.test'+url,{method:opt.method??'GET',headers:{origin:'https://example.test',...(opt.headers??{})},...(opt.body?{body:opt.body}:{})}),id,deps);
 };
 seedHeld();eq(programInputFields(held),[]);
 ok(!nodes(render()).some(n=>n?.type==='form'));
 changeRow('확인한 프로그램 설명','description','합성 설명 수정. 기존 예약·참가 조건 보존.');
 eq(button(render(),'사실 저장·재평가').props.disabled,false); // Fails against the previous UI.
 ok(!text(render()).includes('확인한 사실 입력'));
 ok(!nodes(render()).some(n=>n?.type?.name==='FactFields'));
 ok(nodes(render()).some(n=>n?.type?.name==='OptionalReviewText'&&n.props.label==='추가 메모'));
 const originalObserved=structuredClone(backend.observedFacts);
 saveForm().props.onSubmit({preventDefault(){}});await tick();await tick();
 eq(saveRequests.length,1);eq(saveRequests[0],{action:'save_facts',revision:held.revision,version:held.version,note:'',patch:{description:'합성 설명 수정. 기존 예약·참가 조건 보존.'},resolve:[]});
 eq(rpcCalls.length,1);eq(rpcCalls[0].args.p_actor,'10000000-0000-4000-8000-000000000001');
 eq(states[0].observedFacts,originalObserved);eq(states[0].source,held.source);eq(states[0].factsVersion,2);
 eq(states[0].aiStatus,'cancelled');eq(states[0].result.reasons,['ai_recheck_requested']);eq(states[0].filterInfo.missing,['topic']);
 eq(states[1],states[0].facts);ok(!nodes(render()).some(n=>n?.type==='form'));ok(!text(render()).includes('미저장 변경'));
 // Identical values and cancelled edits do not create a change or a write.
 seedHeld();changeRow('확인한 프로그램 설명','description',held.facts.description);eq(saveRequests.length,0);ok(!nodes(render()).some(n=>n?.type==='form'));
 button(saved(),'확인한 프로그램 설명 수정').props.onClick();eq(states[3],true);
 let rowEditor=nodes(saved()).find(n=>n?.type?.name==='FactFields');rowEditor.props.onChange({...rowEditor.props.facts,description:'취소할 설명'});
 button(saved(),'취소').props.onClick();eq(states[1].description,held.facts.description);eq(states[3],false);eq(saveRequests.length,0);
 changeRow('확인한 프로그램 설명','description','초안 설명');button(render(),'수정 취소').props.onClick();eq(states[1],held.facts);ok(!nodes(render()).some(n=>n?.type==='form'));
 // Another editable field uses the same patch/save control without input reasons.
 seedHeld();changeRow('대상 안내','target_raw','합성 대상 안내 보완');eq(button(render(),'사실 저장·재평가').props.disabled,false);
 button(saved(),'확인한 프로그램 설명 수정').props.onClick();eq(button(render(),'사실 저장·재평가').props.disabled,true);
 saveForm().props.onSubmit({preventDefault(){}});await tick();eq(saveRequests.length,0);
 button(saved(),'취소').props.onClick();saveForm().props.onSubmit({preventDefault(){}});await tick();await tick();eq(Object.keys(saveRequests[0].patch),['target_raw']);
 // Existing server permissions and processed states remain authoritative.
 for(const next of [{...held,editableFields:[]},{...held,aiStatus:'claimed',editableFields:[]},{...held,status:'resolved',aiStatus:'completed',editableFields:[]}]){
  seedHeld(next);ok(!nodes(render()).some(n=>n?.type==='form'));ok(!nodes(saved()).some(n=>n?.props?.['data-edit-program']==='description'));
 }
 // Classification activity and any save in progress prevent submitting.
 seedHeld();changeRow('확인한 프로그램 설명','description','분류 중 초안');
 nodes(render()).find(n=>n?.type?.name==='ClassificationPanel').props.onActive(true);ok(!nodes(render()).some(n=>n?.type==='form'));
 nodes(render()).find(n=>n?.type?.name==='ClassificationPanel').props.onActive(false);
 nodes(render()).find(n=>n?.type?.name==='ClassificationPanel').props.onBlocked(true);eq(button(render(),'분류 검토 중…').props.disabled,true);
 saveForm().props.onSubmit({preventDefault(){}});await tick();eq(saveRequests.length,0);
 nodes(render()).find(n=>n?.type?.name==='ClassificationPanel').props.onBlocked(false);
 let finish;const deferred=new Promise(r=>finish=r);const routed=globalThis.fetch;
 globalThis.fetch=async(...args)=>{await deferred;return routed(...args);};
 const pendingForm=saveForm();pendingForm.props.onSubmit({preventDefault(){}});pendingForm.props.onSubmit({preventDefault(){}});
 eq(button(render(),'저장 중…').props.disabled,true);finish();await tick();await tick();eq(saveRequests.length,1);globalThis.fetch=routed;
 // Conflict, lost session and ambiguous responses preserve applied drafts.
 for(const code of ['conflict','signed_out','unavailable']){
  seedHeld();changeRow('확인한 프로그램 설명','description','오류 후 보존할 설명');
  if(code==='conflict')backend.version='f'.repeat(64);
  if(code==='signed_out')authError=code;
  let attempts=0;globalThis.fetch=async(...args)=>{attempts++;if(code==='unavailable')throw Error('timeout');return routed(...args);};
  saveForm().props.onSubmit({preventDefault(){}});await tick();await tick();eq(attempts,1);eq(states[1].description,'오류 후 보존할 설명');eq(states[5],code);
  eq(rpcCalls.length,code==='conflict'?1:0);
  globalThis.fetch=async(url,opt)=>{attempts++;ok(!opt.method);return Response.json({mode:'database',item:{...held,version:'e'.repeat(64)}});};
  button(render(),'입력을 유지하고 저장 상태 확인').props.onClick();await tick();eq(attempts,2);eq(states[1].description,'오류 후 보존할 설명');eq(states[0].version,'e'.repeat(64));
  globalThis.fetch=routed;
 }
 // A note remains cancelable if the actual fact change is reverted.
 seedHeld();changeRow('확인한 프로그램 설명','description','메모와 함께 수정');
 nodes(render()).find(n=>n?.type?.name==='OptionalReviewText').props.onChange('선택 메모');
 changeRow('확인한 프로그램 설명','description',held.facts.description);eq(button(render(),'사실 저장·재평가').props.disabled,true);
 button(render(),'수정 취소').props.onClick();eq(states[7],'');ok(!nodes(render()).some(n=>n?.type==='form'));
 // Existing missing-input and restored-review forms still render.
 reset();ok(nodes(render()).some(n=>n?.type==='form'));
 seedHeld({...held,restoredReviewPending:true,editableFields:[]});eq(button(render(),'사실 저장·재평가').props.disabled,false);
 ok(!text(render()).includes('확인한 사실 입력'));
 // Replay the preserved 16 external URL values through the actual panel's
 // saved-row editor, ordinary GET/POST handlers and fake authorized RPC.
 // These are synthetic held items, not the operational source facts or state.
 const external=JSON.parse(fs.readFileSync(path.join(root,'scripts/fixtures/seoul_admin_external_links.json'),'utf8'));
 eq(external.links.length,16);
 for(const link of external.links){
  const externalHeld={...held,source:{...held.source,url:link.url},facts:{...held.facts,official_url:link.url},observedFacts:{...held.observedFacts,official_url:link.url}};
  seedHeld(externalHeld);globalThis.fetch=routed;
  const response=await programRequest(new Request(`https://example.test/api/admin/program-review/${id}`),id,deps);
  eq(response.status,200);const loaded=programItem((await response.json()).item,id);states[0]=loaded;states[1]=structuredClone(loaded.facts);
  const reference=nodes(render()).find(n=>n?.type?.name==='ClassificationPanel').props.reference;
  const links=nodes(reference).filter(n=>n?.type==='a'&&n.props.href===link.url);ok(links.length>=1);
  const originalSource=structuredClone(loaded.source),originalObserved=structuredClone(loaded.observedFacts);
  button(saved(),'확인한 프로그램 설명 수정').props.onClick();eq(states[3],true);
  let editor=nodes(saved()).find(n=>n?.type?.name==='FactFields');ok(editor);
  editor.props.onChange({...editor.props.facts,description:'외부 링크 합성 설명. 취소할 초안'});
  button(saved(),'취소').props.onClick();eq(states[1].description,loaded.facts.description);eq(saveRequests.length,0);
  changeRow('확인한 프로그램 설명','description','외부 링크 합성 설명 보완. 고유 참가·예약 조건 보존.');
  eq(button(render(),'사실 저장·재평가').props.disabled,false);
  saveForm().props.onSubmit({preventDefault(){}});await tick();await tick();
  eq(saveRequests.length,1);eq(Object.keys(saveRequests[0].patch),['description']);
  eq(states[0].facts.official_url,link.url);eq(states[0].source,originalSource);eq(states[0].observedFacts,originalObserved);
  eq(states[0].history,loaded.history);eq(states[0].factsVersion,loaded.factsVersion+1);eq(states[0].aiStatus,'cancelled');
  eq(states[0].result.reasons,['ai_recheck_requested']);eq(states[1],states[0].facts);ok(!nodes(render()).some(n=>n?.type==='form'));
 }
 console.log(JSON.stringify({syntheticOnly:true,checks,result:'passed',externalUrls:16,externalConnections:0}));
}finally{globalThis.fetch=originalFetch;globalThis.requestAnimationFrame=originalRAF;globalThis.document=originalDocument;}
