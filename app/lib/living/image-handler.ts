import { privateResponse } from '../auth/http';
import { isSameOriginPost } from '../auth/urls';
import { failure } from '../review/handlers';
import { ReviewFailure } from '../review/contracts';
import { imageId, livingImageBytes } from './images';
import { normalizeLivingImage } from './image-upload';
import type { LivingImageStore } from './image-store';

export async function livingImageHandler(request:Request,id:string,deps:{authorize:()=>Promise<{userId:string}>;store:()=>LivingImageStore},admin=true){
  try{
    const actor=admin?(await deps.authorize()).userId:null;
    if(!imageId(id))throw new ReviewFailure('invalid_input');
    if(request.method==='GET'){
      const store=deps.store(),meta=await store.read(id,admin);
      if(admin&&new URL(request.url).searchParams.get('view')==='status')return privateResponse(Response.json({item:{id:meta.id,status:meta.status}}));
      if(meta.status!=='ready')throw new ReviewFailure('not_found');
      const blob=await store.download(meta.path);
      return privateResponse(new Response(blob,{headers:{'Content-Type':'image/webp','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox",'Content-Disposition':'inline'}}));
    }
    if(!admin||request.method!=='POST')return privateResponse(Response.json({code:'invalid_method'},{status:405}));
    if(!isSameOriginPost(request))return privateResponse(Response.json({code:'wrong_origin'},{status:403}));
    const articleId=request.headers.get('x-living-article'),version=request.headers.get('x-living-version');
    const mime=request.headers.get('content-type')?.split(';')[0]??'';
    if(!imageId(articleId)||!version||!/^(0|[a-f0-9]{64})$/.test(version)||!['image/png','image/jpeg','image/webp'].includes(mime))throw new ReviewFailure('invalid_input');
    const reader=request.body?.getReader();if(!reader)throw new ReviewFailure('invalid_input');
    const chunks:Uint8Array[]=[];let length=0;
    while(true){const {value,done}=await reader.read();if(done)break;length+=value.length;if(length>livingImageBytes){await reader.cancel();throw new ReviewFailure('invalid_input');}chunks.push(value);}
    const bytes=new Uint8Array(length);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
    const normalized=await normalizeLivingImage(bytes,mime),store=deps.store();
    let meta=await store.begin(id,articleId,version,normalized.hash,{width:normalized.width,height:normalized.height,size:normalized.size},actor!);
    if(meta.status!=='ready'){
      // A pending duplicate may already have written Storage: never repeat that upload.
      if(!meta.fresh)throw new ReviewFailure('unavailable');
      await store.put(meta.path,normalized.data);meta=await store.finish(id,actor!);
    }
    return privateResponse(Response.json({item:{id:meta.id,status:meta.status}}));
  }catch(e){return failure(e);}
}
