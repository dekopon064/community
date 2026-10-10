import { requireAdmin } from '@/app/lib/auth/admin';
import { getReviewRpcClient } from '@/app/lib/review/server';
import { ClassificationStore } from '@/app/lib/review/classification-store';
import { classificationRequest } from '@/app/lib/review/classification-handler';
async function handle(request:Request,context:{params:Promise<{id:string}>}) {
  const {id}=await context.params;
  return classificationRequest(request,id,{authorize:requireAdmin,store:()=>new ClassificationStore(getReviewRpcClient())});
}
export const GET=handle;
export const POST=handle;
