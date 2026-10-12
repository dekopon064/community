import { requireAdmin } from '@/app/lib/auth/admin';
import { aiReviewRequest } from '@/app/lib/review/ai-review-handlers';
import { getAiReviewStore } from '@/app/lib/review/ai-server';
async function handle(request:Request,context:{params:Promise<{id:string}>}){
 const {id}=await context.params;
 return aiReviewRequest(request,id,{authorize:requireAdmin,store:getAiReviewStore});
}
export const GET=handle;
export const POST=handle;
