import { getPublicLivingImageStore } from '@/app/lib/living/public-images';
import { livingImageHandler } from '@/app/lib/living/image-handler';
export const runtime='nodejs';
export async function GET(request:Request,{params}:{params:Promise<{id:string}>}){
  return livingImageHandler(request,(await params).id,{authorize:async()=>{throw Error('public read has no admin identity');},store:getPublicLivingImageStore},false);
}
