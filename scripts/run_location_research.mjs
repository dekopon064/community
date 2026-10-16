// Explicit local research batch. Common Pro authentication happens only with
// --provider chatgpt_plan --execute. Never imports DB/save/collection workers.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
import {createPlanInvestigator} from './location_plan_bridge.mjs';
const require=createRequire(import.meta.url),ts=require('typescript');
const root=fileURLToPath(new URL('../',import.meta.url)),cache=new Map();
function load(file){
  file=path.resolve(root,file);if(cache.has(file))return cache.get(file);
  const exports={};cache.set(file,exports);
  const source=require('node:fs').readFileSync(file,'utf8');
  const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  new Function('require','exports',code)(s=>s.startsWith('.')?load(path.resolve(path.dirname(file),s+'.ts')):require(s),exports);return exports;
}
export async function main(args=process.argv.slice(2),deps={}){
  if(args.includes('--help')){console.log('node scripts/run_location_research.mjs --input FILE --output NEW_FILE --provider chatgpt_plan --python EXISTING_PYTHON --max-calls N [--execute]\n--execute 없이는 인증·검색·GPT를 실행하지 않습니다. 기존 공통 Pro 인증을 재사용하며 필요한 재인증은 별도로 진행합니다. 유료 API 전환·DB 저장은 없습니다.\n시험용 별도 경로: --input FILE --output NEW_FILE --investigator TRUSTED_MODULE --max-calls N');return;}
  const execute=args.includes('--execute');
  if(args.filter(x=>x==='--execute').length>1)throw Error('invalid_arguments');
  args=args.filter(x=>x!=='--execute');
  const plan=args.includes('--provider'),flags=plan?['--input','--output','--provider','--python','--max-calls']:['--input','--output','--investigator','--max-calls'];
  if(args.length!==flags.length*2||args.some((v,i)=>i%2===0&&!flags.includes(v))||new Set(args.filter((_,i)=>i%2===0)).size!==flags.length)throw Error('invalid_arguments');
  const values=Object.fromEntries(args.reduce((a,v,i)=>{if(i%2===0)a.push([v,args[i+1]]);return a;},[]));
  if(plan&&values['--provider']!=='chatgpt_plan'||!plan&&execute)throw Error('invalid_arguments');
  if(!Number.isSafeInteger(Number(values['--max-calls']))||Number(values['--max-calls'])<1||Number(values['--max-calls'])>25)throw Error('research_call_budget');
  if(plan&&!execute){console.log(JSON.stringify({mode:'validation-only',provider:'chatgpt_plan',auth:0,search:0,gpt:0,reviewWrites:0,requires:'explicit_execute'}));return;}
  const inputPath=path.resolve(values['--input']),outputPath=path.resolve(values['--output']);
  if(inputPath===outputPath)throw Error('new_output_required');
  const bytes=await fs.readFile(inputPath);if(bytes.length>2*1024*1024)throw Error('input_too_large');
  const input=JSON.parse(bytes.toString('utf8'));
  const {researchLocations,researchInput,locationResearchInstructions}=load('app/lib/review/location-research-worker.ts');
  researchInput(input,Number(values['--max-calls']));
  // Reserve a new output before loading/calling a provider. Existing artifacts
  // never trigger another generation just because the final write would fail.
  const output=await fs.open(outputPath,'wx');
  let investigator;
  try{
    let provider;
    if(plan){
      const {districtChoices}=load('app/lib/contentFilters.ts');
      investigator=(deps.makePlanInvestigator??createPlanInvestigator)({python:values['--python'],choices:districtChoices,instructions:locationResearchInstructions,limit:Number(values['--max-calls'])});
      provider={mode:investigator.mode??'research',investigator};
    }else{provider=await import(pathToFileURL(path.resolve(values['--investigator'])).href);investigator=provider.investigator;}
    if(!['research','synthetic'].includes(provider.mode)||!provider.investigator)throw Error('official_research_runtime_required');
    let report;
    try{report=await researchLocations(input,provider.investigator,{batchId:randomUUID(),createdAt:new Date().toISOString(),mode:provider.mode,maxCalls:Number(values['--max-calls'])});}
    catch(error){
      await output.writeFile(JSON.stringify({stopped:true,code:error.partial?error.code:'research_stopped_no_retry',...(error.partial?{partial:error.partial}:{}),...(plan?{stats:investigator.stats}:{})},null,2));
      throw Error('research_stopped_no_retry');
    }
    await output.writeFile(JSON.stringify(report,null,2));
    console.log(JSON.stringify({items:report.items.length,mode:report.mode,reviewWrites:0,...(plan?{stats:investigator.stats}:{})}));
  }finally{try{await investigator?.close?.();}finally{await output.close();}}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(()=>{console.error('개최지역 조사 중단: 입력·호출 상한·공식 조사 연결을 확인하세요. 자동 재시도하지 않습니다.');process.exitCode=1;});
