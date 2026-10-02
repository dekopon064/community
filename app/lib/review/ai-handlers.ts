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
  if([...query.keys()].some(k=>!["offset","watch"].includes(k))||query.getAll("offset").length>1||query.getAll("watch").length>1)throw new ReviewFailure("invalid_input");
  const raw=query.get("offset")??"0",ids=query.get("watch");
  if(!/^\d{1,6}$/.test(raw)||Number(raw)>100000||ids&&ids.length>3699)throw new ReviewFailure("invalid_input");
  const watch=ids?ids.split(","):[];
  if(watch.length>100||watch.some(id=>!jobUuid.test(id)))throw new ReviewFailure("invalid_input");
  const store=deps.store(),snapshot=await store.read(Number(raw),[...new Set(watch)]);
  return privateResponse(Response.json({...snapshot,mode:store.mode}));
 }catch(e){return failure(e);}
}

