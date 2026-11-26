import { privateResponse } from '../auth/http';
import { isSameOriginPost } from '../auth/urls';
import { ReviewFailure } from './contracts';
import { failure } from './handlers';
import { jobUuid } from './ai-queue';
import type { RpcClient } from './database-store';

export type SuitabilityDecision = {group:'exclude'|'check'|'keep';clause:string;quote:string;reason:string;question:string;note:string};
export type SuitabilityRow = {id:string;title:string;key:string;source:string;queue:'facts'|'ai';currentStage:'facts'|'ai'|'processing'|'candidate'|'unknown';moved:boolean;reused:boolean;
  state:'waiting'|'unconfirmed'|'done';decision:SuitabilityDecision|null};
export type SuitabilityReport = {id:string;policy:string;readAt:string;items:SuitabilityRow[]};

async function requireEmptyBody(request: Request) {
  const reader = request.body?.getReader();
  if (!reader) return;
  try {
    // A bodyless POST can still arrive from Next's Node adapter as a stream.
    while (true) {
      const {done, value} = await reader.read();
      if (done) return;
      if (value.byteLength > 0) {
        void reader.cancel().catch(() => {});
        throw new ReviewFailure('invalid_input');
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function suitabilityRequest(request: Request, deps:{authorize:()=>Promise<{userId:string}>;client:()=>RpcClient}) {
  try {
    const {userId} = await deps.authorize();
    const query = new URL(request.url).searchParams;
    const run = query.get('run');
    if (run !== null && !jobUuid.test(run)) throw new ReviewFailure('invalid_input');
    if (request.method === 'GET') {
      const {data,error} = await deps.client().rpc('suitability_report',{p_run:run});
      if (error) throw new ReviewFailure('unavailable');
      return privateResponse(Response.json({report:data}));
    }
    if (request.method !== 'POST' || !isSameOriginPost(request))
      return privateResponse(Response.json({code:'wrong_origin'},{status:403}));
    const item = query.get('item'), receipt = query.get('request');
    if (!run || !item || !receipt || !jobUuid.test(item) || !jobUuid.test(receipt))
      throw new ReviewFailure('invalid_input');
    await requireEmptyBody(request);
    const {data,error} = await deps.client().rpc('suitability_exclude',{p_run:run,p_item:item,p_request:receipt,p_actor:userId});
    if (error?.code==='PT404' || error?.code==='PT409')
      return privateResponse(Response.json({id:item,result:'skipped'}));
    if (error?.code==='PT422' || error?.code==='23514')
      return privateResponse(Response.json({id:item,result:'failed'}));
    if (error || !['skipped','moved'].includes(String(data))) throw new ReviewFailure('unavailable');
    return privateResponse(Response.json({id:item,result:data}));
  } catch(error) { return failure(error); }
}
