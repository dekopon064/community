import { privateResponse } from '../auth/http';
import { isSameOriginPost } from '../auth/urls';
import { failure } from '../review/handlers';
import { ReviewFailure } from '../review/contracts';
import { livingCommand, livingId } from './contract';
import type { LivingStore } from './store';
export async function livingHandler(request:Request,deps:{authorize:()=>Promise<{userId:string}>;store:()=>LivingStore}) {
  try{
    const {userId}=await deps.authorize();
    if(request.method==='GET'){
      const params=new URL(request.url).searchParams,id=params.get('id');const raw=params.get('offset')??'0';
      if(id&&!livingId(id)||!/^\d{1,6}$/.test(raw))throw new ReviewFailure('invalid_input');
      const store=deps.store();return privateResponse(Response.json({mode:store.mode,...(id?{item:await store.get(id)}:{items:await store.list(Number(raw))})}));
    }
    if(request.method!=='POST')return privateResponse(Response.json({code:'invalid_method'},{status:405}));
    if(!isSameOriginPost(request))return privateResponse(Response.json({code:'wrong_origin'},{status:403}));
    if(request.headers.get('content-type')?.split(';')[0].trim()!=='application/json')throw new ReviewFailure('invalid_input');
    const reader=request.body?.getReader();if(!reader)throw new ReviewFailure('invalid_input');
    const chunks:Uint8Array[]=[];let size=0;
    while(true){const {value,done}=await reader.read();if(done)break;size+=value.length;if(size>2*1024*1024){await reader.cancel();throw new ReviewFailure('invalid_input');}chunks.push(value);}
    const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
    let body:unknown;try{body=JSON.parse(new TextDecoder().decode(bytes));}catch{throw new ReviewFailure('invalid_input');}
    const command=livingCommand(body),store=deps.store();
    return privateResponse(Response.json({mode:store.mode,item:await store.write(command,userId)}));
  }catch(error){return failure(error);}
}
