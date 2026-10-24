import {requireAdmin} from '@/app/lib/auth/admin';
import {getReviewRpcClient} from '@/app/lib/review/server';
import {HomeColorStore} from '@/app/lib/home-colors/admin';
import {homeColorRequest} from '@/app/lib/home-colors/admin-handler';
async function handle(request:Request,context:{params:Promise<{id:string}>}){
 const {id}=await context.params;
 return homeColorRequest(request,id,{authorize:requireAdmin,store:()=>new HomeColorStore(getReviewRpcClient())});
}
export const GET=handle;
export const POST=handle;
