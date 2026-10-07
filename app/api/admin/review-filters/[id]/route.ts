import { requireAdmin } from '@/app/lib/auth/admin';
import { getReviewRpcClient } from '@/app/lib/review/server';
import { ContentFilterStore } from '@/app/lib/review/content-filter-store';
import { contentFilterRequest } from '@/app/lib/review/content-filter-handler';
async function handle(request:Request,context:{params:Promise<{id:string}>}) {
  const {id}=await context.params;
  return contentFilterRequest(request,id,{authorize:requireAdmin,store:()=>new ContentFilterStore(getReviewRpcClient())});
}
export const GET=handle;
export const POST=handle;
