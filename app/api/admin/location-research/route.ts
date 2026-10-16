import { requireAdmin } from '@/app/lib/auth/admin';
import { getReviewRpcClient } from '@/app/lib/review/server';
import { ProgramReviewStore } from '@/app/lib/review/program-store';
import { MySeoulReviewStore } from '@/app/lib/review/myseoul-store';
import { ContentFilterStore } from '@/app/lib/review/content-filter-store';
import { ReviewFailure } from '@/app/lib/review/contracts';
import { locationResearchRequest } from '@/app/lib/review/location-research-handler';

export async function POST(request:Request) {
  return locationResearchRequest(request,{
    authorize:requireAdmin,
    review:async(id,source)=>{
      const client=getReviewRpcClient();
      const item=source==='seoul_reservation'?await new ProgramReviewStore(client).get(id):
        source==='myseoul_program'?await new MySeoulReviewStore(client).get(id):null;
      if(!item)throw new ReviewFailure('invalid_input');
      if(typeof item.facts.description!=='string')throw new ReviewFailure('unavailable');
      return {...item,facts:{description:item.facts.description},factsVersion:Number(item.factsVersion)};
    },
    filters:()=>new ContentFilterStore(getReviewRpcClient()),
  });
}
