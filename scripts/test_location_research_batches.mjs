// Actual launcher -> Python bridge -> shared protected Auth with signed fakes
// -> fake Pro/search/page -> durable journal and bounded importable reports.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import {main} from './run_location_research.mjs';
import {createPlanInvestigator} from './location_plan_bridge.mjs';
import {redactResearch,researchJournal} from './location_research_journal.mjs';
http.request=https.request=net.connect=net.createConnection=()=>{throw Error('network forbidden');};
globalThis.fetch=()=>{throw Error('network forbidden');};
const root=fileURLToPath(new URL('../',import.meta.url)),require=createRequire(import.meta.url),ts=require('typescript'),cache=new Map();
function load(file){file=path.resolve(root,file);if(cache.has(file))return cache.get(file);const out={};cache.set(file,out);const code=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;new Function('require','exports',code)(s=>s.startsWith('.')?load(path.resolve(path.dirname(file),s+'.ts')):require(s),out);return out;}
const core=load('app/lib/review/location-research.ts'),worker=load('app/lib/review/location-research-worker.ts');
const temp=fs.mkdtempSync(path.join(root,'scripts/__pycache__/location-batches-'));
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;},ok=v=>{assert.ok(v);checks++;};
const seed={source:'seoul_reservation',description:'만나는 장소: 합성물빛공원 교육장 앞\n활동 장소: 합성산',revision:'a'.repeat(64),version:'b'.repeat(64),factsToken:'c'.repeat(64),factsVersion:3,filterVersion:5};
const items=Array.from({length:53},(_,i)=>({...seed,id:`30000000-0000-4000-8000-${String(i+1).padStart(12,'0')}`,title:`합성 조사 ${i+1}`}));
items[5].description='만나는 장소는 별도 안내\n활동 장소: 합성물빛공원 교육장 앞';
const packet={schema:core.locationResearchSchema,items};
eq(worker.researchRunInput(packet,53).map(b=>b.length),[25,25,3]);
eq(worker.researchRunInput({schema:'location-research-set-v1',batches:[{schema:packet.schema,items:items.slice(0,25)},{schema:packet.schema,items:items.slice(25)}]},53).flat(),items);
for(const value of [{...packet,items:[...items,items[0]]},{...packet,items:[{...items[0],factsVersion:0}]},{...packet,extra:true}]){assert.throws(()=>worker.researchRunInput(value,54));checks++;}
assert.throws(()=>worker.researchRunInput(packet,52));checks++;
const input=path.join(temp,'input.json');fs.writeFileSync(input,JSON.stringify(packet));
function args(output,budget=53,file=input){return ['--input',file,'--output',output,'--provider','chatgpt_plan','--python',process.env.MACHIMOA_TEST_PYTHON,'--max-calls',String(budget),'--execute'];}
const read=file=>JSON.parse(fs.readFileSync(file,'utf8'));
const audit=output=>fs.readFileSync(output+'.audit.jsonl','utf8').trim().split('\n').map(JSON.parse);
async function quiet(fn){const before=console.log;console.log=()=>{};try{return await fn();}finally{console.log=before;}}
function realFakeFactory(scenario,counter){return options=>{
  const offset=counter.batches++*25,workerPath=path.join(temp,`${scenario}-${offset}.py`);
  fs.writeFileSync(workerPath,`import sys,copy\nsys.path.insert(0,${JSON.stringify(path.join(root,'scripts'))})\nimport test_location_plan_research as f\nfrom ingest.ai_provider import create_location_research_adapter\nfrom location_research_worker import serve\nt=f.LocationResearchTests('test_pipe_path_uses_common_auth_and_emits_only_safe_proposals');t.setUp()\ndef factory(provider,**options):\n    values=[]\n    for n in range(${offset},${offset}+options['limit']):\n        value=f.completed()\n        if ${JSON.stringify(scenario)}=='mixed' and n in (1,24):value['output'][2]['content'][0]['text']='{actual fake malformed response'\n        if ${JSON.stringify(scenario)}=='mixed' and n==2:\n            values.append([{'type':'response.output_text.delta','delta':'incomplete fake response'}]);continue\n        if ${JSON.stringify(scenario)}=='mixed' and n==3:\n            value=f.completed({'status':'suggested','evidence':dict(f.EVIDENCE,excerpt='합성물빛공원 교육장 앞 서울 강동구 없는 인용')})\n        if ${JSON.stringify(scenario)}=='auth' and n==26:\n            values.append([{'type':'error','code':'subscription_sharing_user_not_eligible'}]);continue\n        if ${JSON.stringify(scenario)}=='usage' and n==26:value['usage']=None\n        values.append(f.events(value))\n    return create_location_research_adapter(provider,**options,manager=t.owner.manager(),client=f.FakeClient(values),fetch_page=lambda url:f.EVIDENCE['excerpt'])\ntry:serve(sys.stdin,sys.stdout,factory=factory)\nfinally:t.doCleanups()\n`);
  const bridge=createPlanInvestigator({...options,workerPath});bridge.mode='synthetic';return bridge;
};}
const output=path.join(temp,'complete.json'),counter={batches:0};
await quiet(()=>main(args(output),{makePlanInvestigator:realFakeFactory('mixed',counter)}));
const run=read(output),records=audit(output);
eq(counter.batches,3);eq(run.stopped,false);eq(run.targets,items.map(x=>x.id));eq(run.batches.map(x=>x.items),[25,25,3]);
eq(run.batches.reduce((n,x)=>n+x.stats.requests,0),53);eq(run.batches.reduce((n,x)=>n+x.stats.usageUnknownCount,0),1);
eq(records.filter(x=>x.type==='item_started').map(x=>x.snapshot.id),items.map(x=>x.id));
eq(new Set(records.filter(x=>x.type==='item_started').map(x=>x.snapshot.id)).size,53);
eq(records.filter(x=>x.type==='item_result').length,53);
for(let i=0;i<records.length;i++)eq(records[i].sequence,i+1);
const resultRecords=records.filter(x=>x.type==='item_result');
eq(resultRecords[1].diagnostic.code,'research_json_invalid');
ok(resultRecords[1].diagnostic.response.output[2].content[0].text.includes('actual fake malformed response'));
eq(resultRecords[2].diagnostic.responseState,'unknown');eq(resultRecords[2].diagnostic.partialText,'incomplete fake response');
eq(resultRecords[3].diagnostic.code,'research_quote_not_in_page');eq(resultRecords[3].diagnostic.official.checks.quoteInPage,false);
eq(resultRecords[5].code,'proposal_meeting_not_explicit');eq(resultRecords[25].status,'suggested');
for(const batch of run.batches){const report=core.locationReport(read(batch.path));eq(report.mode,'synthetic');ok(report.items.length<=25);}
eq(run.batches.flatMap(x=>read(x.path).items).map(x=>x.snapshot),items);
// Every next request follows a persisted outcome; next batch follows its report.
for(let i=1;i<resultRecords.length;i++){const index=records.indexOf(resultRecords[i-1]);ok(records.slice(index+1).some(x=>x.type==='item_started'&&x.snapshot.id===resultRecords[i].id));}

// Actual observed shape: five search/open/find calls, including a completed
// response with empty output and five terminal tool events. No real response
// text, titles, identifiers or credentials are used in this synthetic replay.
const boundInput=path.join(temp,'search-bound-input.json');
const boundItems=items.map(x=>({...x,description:seed.description}));
fs.writeFileSync(boundInput,JSON.stringify({...packet,items:boundItems}));
function boundFactory(counter,{fault=null}={}){
 const factory=realFakeFactory('search-bound',counter),faultName=JSON.stringify(fault??'none');
 return options=>{
  const bridge=factory(options),offset=(counter.batches-1)*25;
  const file=path.join(temp,`search-bound-${offset}.py`);
  let source=fs.readFileSync(file,'utf8').replace('        value=f.completed()\n',
   '        value=f.tool_response() if n in (0,24,25,51) else f.completed()\n');
  source=source.replace('        values.append(f.events(value))',
   `        if n==25 and ${faultName}=='usage':value['usage']=None\n`+
   `        if n==25 and ${faultName} in ('auth','quota'):\n`+
   `            values.append(f.events(value)[:-1]+[{'type':'error','code':'permission_denied' if ${faultName}=='auth' else 'rate_limit_exceeded'}]);continue\n`+
   '        stream=f.events(value)\n        if n==25:stream[-1][\'response\'][\'output\']=[]\n        values.append(stream)');
  fs.writeFileSync(file,source);return bridge;
 };
}
const boundOutput=path.join(temp,'search-bound.json'),boundCount={batches:0};
await quiet(()=>main(args(boundOutput,53,boundInput),{makePlanInvestigator:boundFactory(boundCount)}));
const boundRun=read(boundOutput),boundLog=audit(boundOutput),boundResults=boundLog.filter(x=>x.type==='item_result');
eq(boundRun.stopped,false);eq(boundCount.batches,3);eq(boundRun.batches.map(x=>x.items),[25,25,3]);
eq(boundRun.batches.reduce((n,b)=>n+b.stats.requests,0),53);
eq(boundRun.batches.reduce((n,b)=>n+b.stats.usageUnknownCount,0),0);
eq(boundRun.batches.reduce((n,b)=>n+b.stats.officialReads,0),49);
eq(boundLog.filter(x=>x.type==='item_started').map(x=>x.snapshot.id),boundItems.map(x=>x.id));
eq(boundResults.filter(x=>x.status==='error').length,4);
for(const index of [0,24,25,51]){
 const result=boundResults[index];eq(result.status,'error');eq(result.diagnostic.code,'research_search_tool_bound');
 eq(result.diagnostic.bounds,{toolCalls:5,maxToolCalls:3,outputTokens:20,maxOutputTokens:2048});
 eq(result.diagnostic.completedSeen,true);eq(result.diagnostic.usage.output_tokens,20);eq(result.diagnostic.official,null);
 if(index===25)eq(result.diagnostic.response.output,[]);
 const next=boundLog.find(x=>x.type==='item_started'&&x.snapshot.id===boundItems[index+1].id);
 ok(result.sequence<next.sequence);
}
for(const receipt of boundRun.batches)core.locationReport(read(receipt.path));
eq(boundRun.batches.flatMap(b=>read(b.path).items).map(x=>x.snapshot),boundItems);
for(const fault of ['auth','usage','quota']){
 const out=path.join(temp,'bound-'+fault+'.json'),count={batches:0};
 await assert.rejects(quiet(()=>main(args(out,53,boundInput),{makePlanInvestigator:boundFactory(count,{fault})})));checks++;
 const stopped=read(out),log=audit(out);
 eq(stopped.stopped,true);eq(count.batches,2);eq(log.filter(x=>x.type==='item_started').length,26);
 eq(stopped.code,fault==='auth'?'permission_denied':fault==='quota'?'rate_limit_exceeded':'research_usage_unknown');
 eq(log.at(-1).type,'run_stopped');
}
// Failure to persist a tool-overflow outcome still prevents the NEXT request.
const boundRecord=path.join(temp,'bound-record.json'),boundRecordCount={batches:0};
let rejectedRecordWrites=0;
await assert.rejects(quiet(()=>main(args(boundRecord,53,boundInput),{
 makePlanInvestigator:boundFactory(boundRecordCount),
 async openFile(file,...rest){const handle=await fsp.open(file,...rest);if(!file.endsWith('.audit.jsonl'))return handle;
  return {close:()=>handle.close(),sync:()=>handle.sync(),writeFile:async line=>{
   const event=JSON.parse(line);
   if(event.type==='item_result'&&event.diagnostic?.code==='research_search_tool_bound'){rejectedRecordWrites++;throw Error('synthetic record failure');}
   return handle.writeFile(line);
  }};
 }
})));checks++;
eq(rejectedRecordWrites,1);eq(boundRecordCount.batches,1);eq(read(boundRecord).code,'research_record_error');
eq(audit(boundRecord).filter(x=>x.type==='item_started').length,1);
eq(read(read(boundRecord).batches[0].path).stats.requests,1);

for(const scenario of ['auth','usage','quota']){
 const out=path.join(temp,scenario+'.json'),count={batches:0};
 const factory=realFakeFactory(scenario,count);
 await assert.rejects(quiet(()=>main(args(out),{makePlanInvestigator(options){
   const bridge=factory(options);
   if(scenario==='quota'){
     const file=path.join(temp,`${scenario}-${(count.batches-1)*25}.py`);
     fs.writeFileSync(file,fs.readFileSync(file,'utf8').replace("=='auth' and n==26", "=='quota' and n==26").replace('subscription_sharing_user_not_eligible','rate_limit_exceeded'));
   }
   return bridge;
 }})));checks++;
 const stopped=read(out),log=audit(out);eq(stopped.stopped,true);eq(count.batches,2);
 eq(stopped.code,scenario==='auth'?'subscription_sharing_user_not_eligible':scenario==='quota'?'rate_limit_exceeded':'research_usage_unknown');
 eq(log.filter(x=>x.type==='item_started').length,27);eq(log.filter(x=>x.type==='batch_started').length,2);
 eq(core.locationReport(read(stopped.batches[0].path)).items.length,25);eq(read(stopped.batches[1].path).partial.items.length,1);
 eq(stopped.targets.length,53);eq(log.at(-1).type,'run_stopped');
}
// Recording/open/report write faults never start the next item or batch.
const evidence={place:'합성물빛공원 교육장 앞',url:'https://parks.seoul.go.kr/synthetic',excerpt:'합성물빛공원 교육장 앞 서울 강동구',province:'11',district:'강동구'};
for(const fault of ['open','start','outcome','sync','report','batch_end']){
 const out=path.join(temp,'record-'+fault+'.json');let calls=0,batches=0,failed=false;
 const openFile=async(file,...rest)=>{
  if(fault==='open'&&file.endsWith('.audit.jsonl'))throw Error('private write error');
  const handle=await fsp.open(file,...rest);
  if(!file.endsWith('.audit.jsonl')&&fault!=='report')return handle;
  return {close:()=>handle.close(),async writeFile(data){
    const type=file.endsWith('.audit.jsonl')?JSON.parse(data).type:null;
    if((fault==='start'&&type==='item_started')||(fault==='outcome'&&type==='item_result')||(fault==='batch_end'&&type==='batch_completed')||(fault==='report'&&file.includes('.batch-001.json'))){failed=true;throw Error('private disk error');}
    if(failed)throw Error('write retried after record failure');
    return handle.writeFile(data);
  },async sync(){if(fault==='sync'){failed=true;throw Error('private sync error');}return handle.sync();}};
 };
 await assert.rejects(quiet(()=>main(args(out),{openFile,makePlanInvestigator(){batches++;return {mode:'synthetic',ready:async()=>{},investigate:async()=>{calls++;return {status:'suggested',evidence};}};}})));checks++;
 eq(calls,['report','batch_end'].includes(fault)?25:fault==='outcome'?1:0);ok(batches<=1);
 if(fault==='batch_end'){const stopped=read(out);eq(stopped.batches.length,1);eq(stopped.batches[0].items,25);eq(stopped.code,'research_record_error');}
}
// A pre-existing audit or later batch report fails BEFORE any authentication.
for(const suffix of ['.audit.jsonl','.batch-003.json']){
 const out=path.join(temp,'collision-'+suffix.replaceAll('.','-')+'.json'),occupied=out+suffix;
 fs.writeFileSync(occupied,'preserve prior artifact');let made=0;
 await assert.rejects(quiet(()=>main(args(out),{makePlanInvestigator(){made++;}})));checks++;
 eq(made,0);eq(fs.readFileSync(occupied,'utf8'),'preserve prior artifact');
}
let factories=0;
await assert.rejects(quiet(()=>main(args(output),{makePlanInvestigator(){factories++;}})));checks++;eq(factories,0);
await quiet(()=>main(args(path.join(temp,'no-execute.json')).filter(x=>x!=='--execute'),{makePlanInvestigator(){throw Error('unexpected auth');}}));eq(fs.existsSync(path.join(temp,'no-execute.json')),false);
const duplicate=path.join(temp,'duplicate.json');fs.writeFileSync(duplicate,JSON.stringify({...packet,items:[items[0],items[0]]}));
await assert.rejects(quiet(()=>main(args(path.join(temp,'duplicate-out.json'),2,duplicate),{makePlanInvestigator(){factories++;}})));checks++;eq(factories,0);
// Journal never serializes credentials, even malicious text from a fake provider.
const cleaned=JSON.stringify(redactResearch({access_token:'private-access',headers:{authorization:'private-header'},text:'Bearer private-bearer https://example.test/?api_key=private-query',nested:'{"refresh_token":"private-refresh"}',jwt:'eyJabc.abcdef.sig'}));
for(const secret of ['private-access','private-header','private-bearer','private-query','private-refresh','eyJabc.abcdef.sig'])ok(!cleaned.includes(secret));
let attempts=0;const broken=researchJournal({writeFile:async()=>{attempts++;throw Error('disk');},sync:async()=>{}});
await assert.rejects(broken({type:'first'}));await assert.rejects(broken({type:'second'}));eq(attempts,1);
console.log(JSON.stringify({checks,result:'passed',batches:[25,25,3],fakeProRequests:53,actualGpt:0,operatingWrites:0,automaticRetries:0,artifacts:temp}));
