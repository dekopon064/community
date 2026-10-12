import { privateResponse } from '../auth/http';
import { isSameOriginPost } from '../auth/urls';
import { failure } from './handlers';
import { ReviewFailure } from './contracts';
import { jobUuid } from './ai-queue';
import { aiRecheckCommand } from './ai-review';
import type { AiReviewStore } from './ai-review';
export async function aiReviewRequest(request:Request,id:string,deps:{authorize:()=>Promise<{userId:string}>;store:()=>AiReviewStore}){
 try{
  const {userId}=await deps.authorize();
  if(!jobUuid.test(id)||new URL(request.url).search)throw new ReviewFailure('invalid_input');
  if(request.method==='GET'){const store=deps.store();return privateResponse(Response.json({mode:store.mode,item:await store.get(id)}));}
  if(request.method!=='POST')return privateResponse(Response.json({code:'invalid_input'},{status:405}));
  if(!isSameOriginPost(request))return privateResponse(Response.json({code:'wrong_origin'},{status:403}));
  if(request.headers.get('content-type')?.split(';')[0].trim()!=='application/json'||Number(request.headers.get('content-length'))>8192)throw new ReviewFailure('invalid_input');
  const reader=request.body?.getReader();if(!reader)throw new ReviewFailure('invalid_input');
  const chunks:Uint8Array[]=[];let length=0;
  while(true){const {done,value}=await reader.read();if(done)break;length+=value.length;if(length>8192){await reader.cancel();throw new ReviewFailure('invalid_input');}chunks.push(value);}
  const bytes=new Uint8Array(length);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  let raw;try{raw=JSON.parse(new TextDecoder().decode(bytes));}catch{throw new ReviewFailure('invalid_input');}
  const command=aiRecheckCommand(raw),store=deps.store();
  return privateResponse(Response.json({mode:store.mode,item:await store.execute(id,command,userId)}));
 }catch(e){return failure(e);}
}
