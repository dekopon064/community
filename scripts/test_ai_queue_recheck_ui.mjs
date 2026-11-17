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
function load(name){const filename=path.join(root,name);if(cache.has(filename))return cache.get(filename);if(filename.endsWith('.json'))return {default:JSON.parse(fs.readFileSync(filename,'utf8'))};if(filename.endsWith('.css'))return {};const exports={};cache.set(filename,exports);
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
seed();button('닫기').props.onClick();eq(closed,1);let tree=render(),ns=nodes(tree);ok(ns.findIndex(n=>n?.type==='details')<ns.findIndex(n=>n?.type==='dl'));eq(ns.find(n=>n?.type==='details').props.open,undefined);eq(button('AI 대기 보류·재검토로 보내기').props.disabled,false);
ns.find(n=>n?.type==='textarea').props.onChange({target:{value:'보호자 조건 재검토'}});eq(states[3],'보호자 조건 재검토');eq(button('닫기').props.disabled,true);
const trigger={focus(){focuses++;}};button('AI 대기 보류·재검토로 보내기').props.onClick({currentTarget:trigger});eq(states[6],'request_recheck');
nodes(render()).find(n=>n?.props?.['aria-label']==='재검토 최종 확인').props.onKeyDown({key:'Escape'});eq(states[6],null);render();effects[3]();eq(focuses,1);eq(states[3],'보호자 조건 재검토');
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
seed({...initial,status:'claimed',canRecheck:false,canExclude:false});ok(!nodes(render()).some(n=>n?.type==='textarea'));ok(!text(render()).includes('AI 대기 보류·재검토로 보내기'));
// No note required; final confirmation still protects the transition.
seed();let emptyCommand;
globalThis.fetch=async(_url,options)=>{emptyCommand=JSON.parse(options.body);return Response.json({mode:'local-fixture',item:{...initial,status:'cancelled',canRecheck:false,recheckPending:true,version:'c'.repeat(64)}});};
eq(button('AI 대기 보류·재검토로 보내기').props.disabled,false);button('AI 대기 보류·재검토로 보내기').props.onClick({currentTarget:trigger});await button('확인하고 저장').props.onClick();await new Promise(r=>setImmediate(r));eq(emptyCommand.note,'');ok(text(render()).includes('입력하지 않음'));
// Quick exclude on queued AND held states; no edit of the fact/filter payload.
for(const [held,retry] of [[false,false],[false,true],[true,false]]){
 seed({...initial,recheckPending:held,status:held?'cancelled':'queued',canRecheck:!held&&!retry});let command;
 globalThis.fetch=async(_url,options)=>{command=JSON.parse(options.body);return Response.json({mode:'local-fixture',item:{...initial,status:'cancelled',canRecheck:false,canExclude:false,recheckPending:false}});};
 button('휴지통으로 보내기').props.onClick({currentTarget:trigger});eq(states[6],'exclude');button('취소').props.onClick();eq(states[6],null);
 button('휴지통으로 보내기').props.onClick({currentTarget:trigger});ok(text(render()).includes(initial.title+'」'));nodes(render()).find(n=>n?.type==='select').props.onChange({target:{value:'region_not_suitable'}});await button('확인하고 제외').props.onClick();await new Promise(r=>setImmediate(r));eq(command.action,'exclude');eq(command.reasonCode,'region_not_suitable');ok(!('facts' in command));eq(states[0].canExclude,false);eq(states[0].values,initial.values);
}
seed({...initial,canExclude:false});ok(!text(render()).includes('휴지통으로 보내기'));
{
 seed({...initial,canRecheck:false,canExclude:true});
 let command;
 globalThis.fetch=async(_url,options)=>{command=JSON.parse(options.body);return Response.json({mode:'local-fixture',item:{...initial,status:'cancelled',canExclude:false,canRecheck:false}});};
 button('휴지통으로 보내기').props.onClick({currentTarget:trigger});
 const selectReason=value=>nodes(render()).find(n=>n?.type==='select').props.onChange({target:{value}});
 selectReason('period_ended');
 const confirmation=nodes(render()).find(n=>n?.props?.['aria-label']==='재검토 최종 확인');
 eq(nodes(confirmation).find(n=>n?.type==='select').props.value,'period_ended');
 ok(!nodes(confirmation).some(n=>n?.type==='textarea'||n?.type==='input'));
 ok(!text(confirmation).includes('전화 접수'));
 await button('확인하고 제외').props.onClick();
 await new Promise(resolve=>setImmediate(resolve));
 eq(command.reasonCode,'period_ended');ok(!Object.hasOwn(command,'note'));
}
seed();states[3]='유지할 메모';eq(button('휴지통으로 보내기').props.disabled,true);
seed();button('휴지통으로 보내기').props.onClick({currentTarget:trigger});globalThis.fetch=async()=>{throw Error('timeout');};await button('확인하고 제외').props.onClick();await new Promise(r=>setImmediate(r));eq(states[5],true);eq(button('휴지통으로 보내기').props.disabled,true);eq(states[0].values,initial.values);

// Actual saved-MySeoul row editor applies one draft field, preserves other drafts,
// supports Esc/focus return and refuses applying a stale opened version.
const {SavedMySeoulFacts}=load('app/components/admin/MySeoulReviewPanel.tsx');
const myFacts={description:'합성 원문 설명을 보존합니다.',target:'기존 어린이 대상',conditions:['보호자 동반'],delivery_mode:'offline',periods:{application:[],operation:[]}};
const myItem={facts:myFacts,editableFields:['description','target','conditions'],version:'a'.repeat(64)};
let myDraft={...myFacts,description:'다른 행에서 작성 중인 설명'},myChanged;
function myRender(item=myItem){cursor=0;refCursor=0;effects=[];return SavedMySeoulFacts({item,draft:myDraft,onChange:v=>{myDraft=v;myChanged=v;},disabled:false,onEditing(){}});}
function myButton(label,item=myItem){const node=nodes(myRender(item)).find(n=>n?.type==='button'&&text(n)===label);ok(node);return node;}
states=[];refs=[];let row=nodes(myRender()).find(n=>n?.props?.action?.props?.['aria-label']==='참여 대상 수정');ok(row);row.props.action.props.onClick();
const factEditor=nodes(myRender()).find(n=>n?.type?.name==='FactEditor');ok(factEditor);factEditor.props.onChange({...factEditor.props.value,target:'수정한 대상'});
myButton('초안에 적용').props.onClick();eq(myChanged.target,'수정한 대상');eq(myChanged.description,'다른 행에서 작성 중인 설명');eq(myItem.facts.target,'기존 어린이 대상');
row=nodes(myRender()).find(n=>n?.props?.action?.props?.['aria-label']==='참여 대상 수정');row.props.action.props.onClick();
const group=nodes(myRender()).find(n=>n?.props?.['aria-label']==='참여 대상 편집');group.props.onKeyDown({key:'Escape',preventDefault(){},stopPropagation(){}});eq(states[0],null);eq(myDraft.target,'수정한 대상');
row=nodes(myRender()).find(n=>n?.props?.action?.props?.['aria-label']==='참여 대상 수정');row.props.action.props.onClick();eq(myButton('초안에 적용',{...myItem,version:'b'.repeat(64)}).props.disabled,true);ok(text(myRender({...myItem,version:'b'.repeat(64)})).includes('입력은 보존했습니다'));

// Saved MySeoul facts use the same row toggle without touching another applied draft.
states=[];refs=[];myChanged=null;row=nodes(myRender()).find(n=>n?.props?.action?.props?.['aria-label']==='참여 대상 수정');row.props.action.props.onClick();
row=nodes(myRender()).find(n=>n?.props?.action?.props?.['aria-label']==='참여 대상 수정 취소');ok(row);eq(row.props.action.props.disabled,false);eq(row.props.action.props['aria-expanded'],true);
const other=nodes(myRender()).find(n=>n?.props?.action?.props?.['aria-label']==='프로그램 설명 수정');eq(other.props.action.props.disabled,true);other.props.action.props.onClick();eq(states[0],'target');
row.props.action.props.onClick();eq(states[0],null);eq(myChanged,null);eq(myDraft.description,'다른 행에서 작성 중인 설명');eq(myDraft.target,'수정한 대상');
// Actual workspace callback routes each source to its existing facts panel.
const Workspace=load('app/components/admin/ReviewWorkspace.tsx').default;
function workspace(){cursor=0;refCursor=0;effects=[];return Workspace();}
function resetWorkspace(){states=[];refs=[];workspace();states[0]='ai';states[13]=false;}
for(const [source,slot,other] of [['seoul_reservation',3,4],['myseoul_program',4,3]]){
 resetWorkspace();const ai=nodes(workspace()).find(n=>n?.type?.name==='AiQueuePanel');ok(ai);
 ai.props.onReview({...initial,sourceName:source,recheckPending:true,status:'cancelled'});eq(states[0],'facts');eq(states[slot],initial.sourceItemId);eq(states[other],null);states[13]=false;
 ok(nodes(workspace()).some(n=>n?.type?.name===(source==='seoul_reservation'?'ProgramReviewPanel':'MySeoulReviewPanel')));
}
resetWorkspace();let ai=nodes(workspace()).find(n=>n?.type?.name==='AiQueuePanel');ai.props.onReview(initial);eq(states[0],'ai');
ai.props.onBusy(true);ai=nodes(workspace()).find(n=>n?.type?.name==='AiQueuePanel');ai.props.onReview({...initial,recheckPending:true});eq(states[0],'ai');
resetWorkspace();states[21]='다른 초안';ai=nodes(workspace()).find(n=>n?.type?.name==='AiQueuePanel');ai.props.onReview({...initial,recheckPending:true});eq(states[0],'ai');eq(states[21],'다른 초안');
// Only the authoritative failed-Seoul capability exposes the existing recheck
// controls. No quick exclusion or automatic POST/AI execution is introduced.
seed({...initial,status:'failed',canRecheck:true,canExclude:false});
ok(text(render()).includes('AI 작업 실패 · 재검토 가능'));
eq(button('AI 대기 보류·재검토로 보내기').props.disabled,false);
ok(!text(render()).includes('휴지통으로 보내기'));
seed({...initial,status:'failed',canRecheck:false,canExclude:false});
ok(text(render()).includes('현재 상태에서는 재검토 전환 불가'));
ok(!text(render()).includes('AI 대기 보류·재검토로 보내기'));
seed({...initial,status:'failed',canRecheck:true,canExclude:false,
 failureDetail:{stage:'japanese_validation',code:'ai_schema_error',rule:'schedule_times',reason:'missing',expected:[[600,690]],actual:[[600,750]]}});
ok(text(render()).includes('정식 실패 저장 당시 진단'));ok(text(render()).includes('10:00–11:30 / 검사값 10:00–12:30'));
globalThis.fetch=oldFetch;
console.log(`AI queue component handlers: ${checks} checks passed. Fake fetch only; no DB/AI.`);

// Use the real failed-item component with a frozen attempt and a fake GET.
const {SeoulFailedDraft}=load('app/components/admin/SeoulAiCorrection.tsx');
const {sessionDecision}=load('app/lib/review/seoul-session-decision.ts');
const commonLine='❏ 운영일시 : 2026. 9. 12.(토) - 12. 31.(토) ※남은 기간 내 매주 토요일 11~13시 운영';
for (const day of [21,28]) {
  const sessionLine='- 답사 일시는 11.'+day+'(토) 11~13시입니다.';
  const description=sessionLine+'\n'+commonLine;
  const facts={description,conditions:[commonLine,'고유 조건'],periods:Object.fromEntries(
    ['SVCOPNBGNDT','SVCOPNENDDT'].map(k=>[k,{value:'2026-11-'+day}]))};
  const decision=sessionDecision(facts);
  eq(decision.conflict.expected,'목');eq(decision.conflict.actual,'토');
  ok(decision.patch.description.includes(sessionLine));ok(decision.patch.description.includes('12. 31.'));
  eq(decision.patch.conditions,[decision.conflict.corrected,'고유 조건']);ok(facts.description.includes('31.(토)'));
  eq(sessionDecision({...facts,description:description.replace(sessionLine,'날짜 미정')}),null);
  states=[];effects=[];cursor=0;
  const snapshot={description,observed:description,draft:{stage:'korean_validation',diagnostic:{
    rule:'calendar_weekday',reason:'mismatch',expected:4,actual:6,location:{field:'content_ko'}},output:{ko:'합성 요약'}}};
  globalThis.fetch=async(url,init)=>{ok(url.endsWith('?view=failed-schedule'));ok(!init.method);return Response.json({snapshot});};
  const props={jobId:id,sourceItemId:id};
  SeoulFailedDraft(props);const cleanup=effects[0]();await new Promise(resolve=>setTimeout(resolve,0));
  cursor=0;const rendered=text(SeoulFailedDraft(props));cleanup();
  for(const v of [sessionLine,commonLine,'수집 원문의 전체 운영 안내','안내 토요일 / 달력 목요일','한국어 본문 검증','한국어 있음','일본어 없음']) ok(rendered.includes(v));
}
console.log('PASS: both frozen session conflicts, retained outputs, operator decision and original facts.');

const {recordedWeekTable}=load('app/lib/review/seoul-session-decision.ts');
const flat=recordedWeekTable('시간 / 요일\n화\n수\n목\n금\n토\n일\n16:00\n5회차\n(일본어)\n5회차(중국어)\n5회차(영어)\n4회차\n4회차');
eq(flat.headers.length,6);eq(flat.rows[0].cells.length,5);eq(flat.rows[0].cells[0],'5회차(일본어)');eq(flat.grouped,false);
ok(recordedWeekTable('시간 / 요일\n평일\n주말\n16:00\n3 회차\n3 회차(일요일 제외)').grouped);
