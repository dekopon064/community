import { requireAdmin } from '@/app/lib/auth/admin';
import { getReviewRpcClient } from '@/app/lib/review/server';
import { DatabaseLivingImageStore } from '@/app/lib/living/image-store';
import { livingImageHandler } from '@/app/lib/living/image-handler';
export const runtime='nodejs';
const deps={authorize:requireAdmin,store:()=>new DatabaseLivingImageStore(getReviewRpcClient())};
export async function GET(request:Request,{params}:{params:Promise<{id:string}>}){return livingImageHandler(request,(await params).id,deps);}
export async function POST(request:Request,{params}:{params:Promise<{id:string}>}){return livingImageHandler(request,(await params).id,deps);}
