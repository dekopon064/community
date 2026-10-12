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
globalThis.document={getElementById:()=>({focus(){focuses.push('input');},scrollIntoView(){}})};
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
 let row=saved();ok(nodes(row).some(n=>n?.props?.value==='저장된 값 없음'));ok(nodes(row).filter(n=>n?.type?.name==='ReviewValueRow').every(n=>!n.props.status.props.confirmed));
 const regionRef=refs.at(-1);regionRef.current={querySelector:()=>({focus(){focuses.push('button');}})};
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
 // Same values must still produce a confirmation command, without fabricating facts.
 const activityData={location:{status:'known',value:{scope:'specific',venues:[{province:'11',district:null,facility:'',address:''}]}},delivery:{status:'known',value:'onsite'}};
 const capable={...item,activityReview:{supported:true,pending:true,confirmed:false},filterInfo:{filterVersion:1,data:activityData}};
 reset();states[0]=capable;tree=render();
 const capableCategory=nodes(tree).find(n=>n?.type?.name==='ClassificationPanel');
 ok(!text(capableCategory.props.overview).includes('원문 근거를 입력'));
 const jump=nodes(capableCategory.props.overview).find(n=>n?.props?.href==='#program-activity-confirm');ok(jump);jump.props.onClick({preventDefault(){}});ok(focuses.includes('input'));
 ok(!nodes(tree).some(n=>n?.type?.name==='FactFields')); // no redundant facility/evidence form
 // The server now offers the same explicit action for unknown delivery with
 // already-saved capital/onsite filters. No client-created completion state.
 reset();states[0]={...capable,facts:{...facts,delivery_mode:'unknown',activity_region:'unknown'},result:{...item.result,reasons:['delivery_mode_unknown']}};
 states[1]=structuredClone(states[0].facts);tree=render();
 const deliveryCategory=nodes(tree).find(n=>n?.type?.name==='ClassificationPanel');
 ok(text(deliveryCategory.props.overview).includes('실제 진행 방식과 개최 지역을 원문과 대조해 확인·저장'));
 ok(nodes(deliveryCategory.props.overview).some(n=>n?.props?.href==='#program-activity-confirm'));
 ok(!nodes(tree).some(n=>n?.type?.name==='FactFields'));
 ok(nodes(tree).some(n=>n?.type?.name==='ProgramActivityConfirmation'));
 // Missing capability keeps the ordinary online/unknown fact form available.
 states[0]={...states[0],activityReview:{supported:true,pending:false,confirmed:false}};tree=render();
 eq(nodes(tree).find(n=>n?.type?.name==='FactFields').props.editable,['delivery_mode','activity_region','activity_evidence']);
 const Activity=load('app/components/admin/ProgramActivityConfirmation.tsx').default;
 let sent=[];const props={item:capable,disabled:false,onBlocked(){},onSubmit:async cmd=>{sent.push(cmd);}};
 function activity(){cursor=0;refCursor=0;return Activity(props);}
 states=[];refs=[];let activityTree=activity();
 eq(button(activityTree,'진행 방식·개최 지역 확인·저장').props.disabled,true);
 eq(states[0],activityData);ok(text(activityTree).includes('기존 값이 맞으면 다시 입력하지 않고'));
 nodes(activityTree).find(n=>n?.type==='textarea').props.onChange({target:{value:'공식 원문의 서울 개최값을 재확인'}});
 nodes(activity()).find(n=>n?.type==='input').props.onChange({target:{checked:true}});
 activityTree=activity();eq(button(activityTree,'진행 방식·개최 지역 확인·저장').props.disabled,false);
 ok(nodes(activityTree).filter(n=>n?.type?.name==='ReviewStatus').every(n=>!n.props.confirmed));
 await activityTree.props.onSubmit({preventDefault(){}});
 eq(sent.length,1);eq(sent[0].action,'confirm_activity');eq(sent[0].factsVersion,1);eq(sent[0].filters,activityData);ok(!('patch' in sent[0]));
 // Returned errors/reads cannot discard input or grant local completion.
 eq(states[1],'공식 원문의 서울 개최값을 재확인');eq(states[2],true);
 props.item={...capable,version:'c'.repeat(64)};activityTree=activity();
 eq(button(activityTree,'진행 방식·개최 지역 확인·저장').props.disabled,true);
 await activityTree.props.onSubmit({preventDefault(){}});eq(sent.length,1);eq(states[1],'공식 원문의 서울 개최값을 재확인');
 activityTree.props.onKeyDown({key:'Escape',preventDefault(){},currentTarget:{focus(){focuses.push('activity');}}});
 eq(states[1],'');eq(states[2],false);eq(states[4],props.item.version);ok(focuses.includes('activity'));
 nodes(activity()).find(n=>n?.type==='textarea').props.onChange({target:{value:'별도 입력'}});
 button(activity(),'입력 취소').props.onClick();eq(states[1],'');eq(states[0],activityData);
 // A pending confirmation never produces a second write or local completion.
 let release;let posts=0;props.onSubmit=()=>{posts++;return new Promise(r=>release=r);};
 nodes(activity()).find(n=>n?.type==='textarea').props.onChange({target:{value:'원문 대조 근거'}});
 nodes(activity()).find(n=>n?.type==='input').props.onChange({target:{checked:true}});
 activityTree=activity();const pending=activityTree.props.onSubmit({preventDefault(){}});
 await activityTree.props.onSubmit({preventDefault(){}});eq(posts,1);
 ok(nodes(activity()).filter(n=>n?.type?.name==='ReviewStatus').every(n=>!n.props.confirmed));
 release();await pending;
 props.disabled=true;await activity().props.onSubmit({preventDefault(){}});eq(posts,1);eq(states[1],'원문 대조 근거');
 console.log(JSON.stringify({syntheticOnly:true,checks,result:'passed',externalConnections:0}));
}finally{globalThis.fetch=originalFetch;globalThis.requestAnimationFrame=originalRAF;globalThis.document=originalDocument;}
