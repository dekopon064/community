// One subprocess/session per frozen batch. No tokens or DB credentials cross IPC.
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const safeCodes=new Set(['research_call_budget','research_auth_required','research_usage_unknown','research_output_or_tool_bound',
 'research_response_unknown','official_read_unavailable','subscription_sharing_unsupported_capability',
 'subscription_sharing_route_not_supported','subscription_sharing_usage_limit_exceeded','subscription_sharing_usage_unavailable',
 'subscription_sharing_user_not_eligible','chatgpt_plan_reauthentication_required','chatgpt_plan_permission_missing',
 'plan_refresh_result_unknown','plan_http_400','plan_http_401','plan_http_403','plan_http_404','plan_http_429']);
export class ResearchRuntimeError extends Error {
 constructor(code){super('location_research_stopped');this.code=safeCodes.has(code)?code:'research_response_unknown';}
}
function safeStats(raw){
 const count=v=>Number.isSafeInteger(v)&&v>=0;
 if(!raw||!count(raw.requests)||!count(raw.officialReads)||!count(raw.usageUnknownCount)||!Array.isArray(raw.usage)||
  raw.requests>25||raw.officialReads>25||raw.usage.length>25||raw.usageUnknownCount!==raw.requests-raw.usage.length||
  raw.usage.some(x=>!x||!count(x.input_tokens)||!count(x.output_tokens)||!count(x.reasoning_tokens)||x.reasoning_tokens>x.output_tokens))return null;
 return {requests:raw.requests,officialReads:raw.officialReads,usageUnknownCount:raw.usageUnknownCount,
  usage:raw.usage.map(x=>({input_tokens:x.input_tokens,output_tokens:x.output_tokens,reasoning_tokens:x.reasoning_tokens}))};
}
export function createPlanInvestigator({python,choices,instructions,limit,
 spawnProcess=spawn,workerPath=fileURLToPath(new URL('./location_research_worker.py',import.meta.url))}){
 let child=null,pending=null,buffer='',ready=false,closed=false,stats=null,sentRequests=0;
 function stop(){if(pending){clearTimeout(pending.timer);pending.reject(new ResearchRuntimeError('research_response_unknown'));pending=null;}closed=true;}
 function start(){
  if(child||closed)throw new ResearchRuntimeError();
  child=spawnProcess(python,['-X','utf8',workerPath,'--worker'],{windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,AI_PROVIDER:'chatgpt_plan'}});
  child.stdout.setEncoding('utf8');child.stderr.resume();
  child.on('error',stop);child.on('exit',stop);child.stdin.on('error',stop);
  child.stdout.on('data',chunk=>{
   buffer+=chunk;if(buffer.length>256000){stop();child.kill();return;}
   let at;while((at=buffer.indexOf('\n'))>=0){
    const line=buffer.slice(0,at);buffer=buffer.slice(at+1);
    if(!pending){stop();child.kill();return;}
    const current=pending;pending=null;clearTimeout(current.timer);
    try{const data=JSON.parse(line);if(data?.stats)stats=safeStats(data.stats);if(data?.ok===true)current.resolve(data);else current.reject(new ResearchRuntimeError(data?.code));}
    catch{current.reject(new ResearchRuntimeError());stop();child.kill();return;}
   }
  });
 }
 function request(message){
  if(closed||!child||pending)return Promise.reject(new ResearchRuntimeError());
  return new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>{stop();child.kill();},300000);
   pending={resolve,reject,timer};
   child.stdin.write(JSON.stringify(message)+'\n',error=>{if(error)stop();});
  });
 }
 return {
  mode:'research',
  get stats(){return stats&&stats.requests>=sentRequests?stats:{requests:null,confirmedRequests:stats?.requests??0,
   requestAttempts:sentRequests,officialReads:null,usage:stats?.usage??[],usageUnknownCount:sentRequests-(stats?.usage.length??0)};},
  async ready(){if(ready)return;start();await request({action:'ready',limit,choices,instructions});ready=true;},
  async investigate(item){if(!ready)throw new ResearchRuntimeError();sentRequests++;const out=await request({action:'investigate',item});return out.answer;},
  async close(){
   if(!child)return;
   try{if(!closed&&!pending)await Promise.race([request({action:'close'}),new Promise(resolve=>setTimeout(resolve,1000))]);}
   catch{/* No retries or credential diagnostics. */}
   finally{
    child.stdin.end();
    if(!closed)await new Promise(resolve=>{const timer=setTimeout(()=>{child.kill();resolve();},1000);child.once('exit',()=>{clearTimeout(timer);resolve();});});
    stop();
   }
  },
 };
}
