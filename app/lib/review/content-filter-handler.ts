import { privateResponse } from '../auth/http';
import { isSameOriginPost } from '../auth/urls';
import { ReviewFailure } from './contracts';
import { failure } from './handlers';
import { filterCommand } from './content-filter-store';
import type { ContentFilterStore } from './content-filter-store';
export async function contentFilterRequest(request: Request,id: string,deps: {authorize:()=>Promise<{userId:string}>;store:()=>ContentFilterStore}) {
  try {
    const {userId}=await deps.authorize();
    if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id)) throw new ReviewFailure('invalid_input');
    if(request.method==='GET') return privateResponse(Response.json({item:await deps.store().get(id)}));
    if(!isSameOriginPost(request)) return privateResponse(Response.json({code:'wrong_origin'},{status:403}));
    if(request.headers.get('content-type')?.split(';')[0].trim()!=='application/json' || Number(request.headers.get('content-length'))>160000) throw new ReviewFailure('invalid_input');
    const reader=request.body?.getReader();if(!reader) throw new ReviewFailure('invalid_input');
    const chunks:Uint8Array[]=[];let length=0;
    while(true) {const {value,done}=await reader.read();if(done) break;length+=value.length;if(length>160000){await reader.cancel();throw new ReviewFailure('invalid_input');}chunks.push(value);}
    const bytes=new Uint8Array(length);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
    let raw:unknown;try{raw=JSON.parse(new TextDecoder().decode(bytes));}catch{throw new ReviewFailure('invalid_input');}
    return privateResponse(Response.json({item:await deps.store().save(id,filterCommand(raw),userId)}));
  } catch(e) {return failure(e);}
}
