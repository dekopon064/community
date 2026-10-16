// Explicit local research batch. Common Pro authentication happens only with
// --provider chatgpt_plan --execute. Never imports DB/save/collection workers.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
import {createPlanInvestigator} from './location_plan_bridge.mjs';
import {researchJournal,ResearchRecordError} from './location_research_journal.mjs';
const require=createRequire(import.meta.url),ts=require('typescript');
const root=fileURLToPath(new URL('../',import.meta.url)),cache=new Map();
const stopCodes=new Set(['research_auth_required','research_usage_unknown','research_output_or_tool_bound','research_record_error','research_runtime_invalid','research_response_unknown','research_call_budget',
  'chatgpt_plan_reauthentication_required','chatgpt_plan_permission_missing','plan_refresh_result_unknown','subscription_sharing_unsupported_capability','subscription_sharing_route_not_supported',
  'subscription_sharing_usage_limit_exceeded','subscription_sharing_usage_unavailable','subscription_sharing_user_not_eligible','plan_http_400','plan_http_401','plan_http_403','plan_http_404','plan_http_429',
  'subscription_sharing_invalid_user','chatpass_v2_scope_not_authorized','chatpass_v2_invalid_authorization_context','subscription_sharing_user_unavailable','rate_limit_exceeded','insufficient_quota','invalid_api_key','permission_denied']);
const stopCode=error=>stopCodes.has(error?.code)?error.code:'research_runtime_invalid';
function load(file){
  file=path.resolve(root,file);if(cache.has(file))return cache.get(file);
  const exports={};cache.set(file,exports);
  const source=require('node:fs').readFileSync(file,'utf8');
  const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  new Function('require','exports',code)(s=>s.startsWith('.')?load(path.resolve(path.dirname(file),s+'.ts')):require(s),exports);return exports;
}
export async function main(args=process.argv.slice(2),deps={}){
  if(args.includes('--help')){console.log('node scripts/run_location_research.mjs --input FILE --output NEW_FILE --provider chatgpt_plan --python EXISTING_PYTHON --max-calls TOTAL [--execute]\n고정한 전체 입력(또는 location-research-set-v1의 batches)을 25건씩 연속 처리합니다. 출력 옆 .audit.jsonl에 응답·근거·실패 이유를 항목별로 기록합니다. 여러 묶음은 .batch-001.json 등으로 따로 불러옵니다.\n--execute 없이는 인증·검색·GPT를 실행하지 않습니다. 기존 공통 Pro 인증을 재사용하며 필요한 재인증은 별도로 진행합니다. 유료 API 전환·DB 저장·같은 항목 자동 재시도는 없습니다.\n시험용 별도 경로: --input FILE --output NEW_FILE --investigator TRUSTED_MODULE --max-calls TOTAL');return;}
  const execute=args.includes('--execute');
  if(args.filter(x=>x==='--execute').length>1)throw Error('invalid_arguments');
  args=args.filter(x=>x!=='--execute');
  const plan=args.includes('--provider'),flags=plan?['--input','--output','--provider','--python','--max-calls']:['--input','--output','--investigator','--max-calls'];
  if(args.length!==flags.length*2||args.some((v,i)=>i%2===0&&!flags.includes(v))||new Set(args.filter((_,i)=>i%2===0)).size!==flags.length)throw Error('invalid_arguments');
  const values=Object.fromEntries(args.reduce((a,v,i)=>{if(i%2===0)a.push([v,args[i+1]]);return a;},[]));
  if(plan&&values['--provider']!=='chatgpt_plan'||!plan&&execute)throw Error('invalid_arguments');
  if(!Number.isSafeInteger(Number(values['--max-calls']))||Number(values['--max-calls'])<1||Number(values['--max-calls'])>10000)throw Error('research_call_budget');
  if(plan&&!execute){console.log(JSON.stringify({mode:'validation-only',provider:'chatgpt_plan',auth:0,search:0,gpt:0,reviewWrites:0,requires:'explicit_execute'}));return;}
  const inputPath=path.resolve(values['--input']),outputPath=path.resolve(values['--output']);
  if(inputPath===outputPath||inputPath===outputPath+'.audit.jsonl')throw Error('new_output_required');
  const inputFile=await fs.open(inputPath,'r');let bytes;
  try{if((await inputFile.stat()).size>64*1024*1024)throw Error('input_too_large');bytes=await inputFile.readFile();if(bytes.length>64*1024*1024)throw Error('input_too_large');}finally{await inputFile.close();}
  const input=JSON.parse(bytes.toString('utf8'));
  const {researchLocations,researchRunInput,locationResearchInstructions}=load('app/lib/review/location-research-worker.ts');
  const {locationResearchSchema}=load('app/lib/review/location-research.ts');
  const batches=researchRunInput(input,Number(values['--max-calls'])),count=batches.reduce((n,b)=>n+b.length,0);
  // Reserve a new output before loading/calling a provider. Existing artifacts
  // never trigger another generation just because the final write would fail.
  const files=[],written=new Set(),results=[],runId=randomUUID();let investigator,record,output;
  const reserve=async file=>{try{const handle=await (deps.openFile??fs.open)(file,'wx',0o600);files.push(handle);return handle;}catch{throw new ResearchRecordError();}};
  const write=async(file,value)=>{if(written.has(file))throw new ResearchRecordError();written.add(file);try{await file.writeFile(JSON.stringify(value,null,2));await file.sync();}catch{throw new ResearchRecordError();}};
  const manifest={schema:'location-research-run-v1',runId,stopped:false,targets:batches.flat().map(x=>x.id),batches:results};
  try{
    output=await reserve(outputPath);
    record=researchJournal(await reserve(outputPath+'.audit.jsonl'));
    const batchFiles=[];
    for(let i=0;i<batches.length;i++){
      const file=batches.length===1?outputPath:outputPath+`.batch-${String(i+1).padStart(3,'0')}.json`;
      if(file===inputPath)throw Error('new_output_required');
      batchFiles.push({path:file,handle:batches.length===1?output:await reserve(file)});
    }
    // All destinations and all target snapshots are validated/reserved BEFORE
    // authentication. An existing result/audit file can never trigger generation.
    await record({type:'run_started',runId,items:count,batches:batches.length,maxCalls:Number(values['--max-calls']),targets:manifest.targets});
    const custom=plan?null:await import(pathToFileURL(path.resolve(values['--investigator'])).href);
    if(custom&&batches.length>1&&typeof custom.createInvestigator!=='function')throw Error('bounded_factory_required');
    let mode;
    for(let i=0;i<batches.length;i++){
      await record({type:'batch_started',runId,batch:i+1,ids:batches[i].map(x=>x.id)});
      const batchId=randomUUID();let completedReport;
      try{
        if(plan){const {districtChoices}=load('app/lib/contentFilters.ts');investigator=(deps.makePlanInvestigator??createPlanInvestigator)({python:values['--python'],choices:districtChoices,instructions:locationResearchInstructions,limit:batches[i].length});mode=investigator.mode??'research';}
        else {investigator=custom.createInvestigator?await custom.createInvestigator({limit:batches[i].length}):custom.investigator;mode=custom.mode;}
        if(!['research','synthetic'].includes(mode)||!investigator)throw Error('official_research_runtime_required');
        const report=await researchLocations({schema:locationResearchSchema,items:batches[i]},investigator,
          {batchId,createdAt:new Date().toISOString(),mode,maxCalls:batches[i].length,record:event=>record({runId,batch:i+1,...event})});
        completedReport=report;
        await write(batchFiles[i].handle,report);
        const receipt={batch:i+1,path:batchFiles[i].path,items:report.items.length,stats:investigator.stats??null};
        await record({type:'batch_completed',...receipt});results.push(receipt);
      }catch(error){
        const partial=error.partial??completedReport;
        const failure={stopped:true,code:stopCode(error),...(partial?{partial}:{}),stats:investigator?.stats??null};
        if(!written.has(batchFiles[i].handle))await write(batchFiles[i].handle,failure);
        results.push({batch:i+1,path:batchFiles[i].path,stopped:true,items:partial?.items?.length??0,stats:failure.stats});
        manifest.stopped=true;manifest.code=failure.code;
        throw error;
      }finally{const active=investigator;investigator=null;await active?.close?.();}
    }
    if(batches.length>1)await write(output,manifest);
    await record({type:'run_completed',runId,items:count,batches:batches.length});
    console.log(JSON.stringify({items:count,batches:batches.length,mode,reviewWrites:0,...(plan&&batches.length===1?{stats:results[0].stats}:{}),audit:outputPath+'.audit.jsonl'}));
  }catch(error){
    manifest.stopped=true;manifest.code=stopCode(error);
    if(output&&!written.has(output))await write(output,manifest);
    if(record)await record({type:'run_stopped',runId,code:manifest.code,completedBatches:results.filter(x=>!x.stopped).length});
    throw error;
  }finally{try{await investigator?.close?.();}finally{const closed=await Promise.allSettled(files.map(file=>file.close()));if(closed.some(x=>x.status==='rejected'))throw new ResearchRecordError();}}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(()=>{console.error('개최지역 조사 중단: 입력·호출 상한·공식 조사 연결을 확인하세요. 자동 재시도하지 않습니다.');process.exitCode=1;});
