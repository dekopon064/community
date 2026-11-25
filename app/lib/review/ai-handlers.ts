import { privateResponse } from "../auth/http";
import { failure } from "./handlers";
import { ReviewFailure } from "./contracts";
import { jobUuid } from "./ai-queue";
import type { AiQueueStore } from "./ai-queue";
export async function readAiQueue(request:Request,deps:{authorize:()=>Promise<{userId:string}>;store:()=>AiQueueStore}){
 try{
  await deps.authorize();
  if(request.method!=="GET")return privateResponse(Response.json({code:"invalid_input"},{status:405}));
  const query=new URL(request.url).searchParams;
  const includeTotal=query.get('includeTotal');
  if([...query.keys()].some(k=>!["offset","watch","includeTotal"].includes(k)||query.getAll(k).length>1) ||
    (includeTotal!==null && includeTotal!=='1')) throw new ReviewFailure("invalid_input");
  const raw=query.get("offset")??"0",ids=query.get("watch");
  if(!/^\d{1,6}$/.test(raw)||Number(raw)>100000||ids&&ids.length>3699)throw new ReviewFailure("invalid_input");
  const watch=ids?ids.split(","):[];
  if(watch.length>100||watch.some(id=>!jobUuid.test(id)))throw new ReviewFailure("invalid_input");
  const store=deps.store(),snapshot=await store.read(Number(raw),[...new Set(watch)]);
  if(includeTotal==='1') {
    const requested=Number(raw), waiting=new Set<string>();
    let visible=snapshot, offset=requested;
    for(let start=0; ; start+=25) {
      if(start>100000) throw new ReviewFailure('unavailable');
      const page=start===requested ? snapshot : await store.read(start,[]);
      for(const job of page.items) if(job.status==='queued') waiting.add(job.jobId);
      if(start<=requested && (start===0 || page.items.length || page.held?.length)) {
        visible=page;offset=start;
      }
      if(!page.hasMore) break;
    }
    return privateResponse(Response.json({...visible,observed:snapshot.observed,offset,waitingTotal:waiting.size,mode:store.mode}));
  }
  return privateResponse(Response.json({...snapshot,mode:store.mode}));
 }catch(e){return failure(e);}
}

