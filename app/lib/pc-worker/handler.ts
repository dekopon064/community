import { privateResponse } from '../auth/http';
import { isSameOriginPost } from '../auth/urls';
import { ReviewFailure } from '../review/contracts';
import { failure } from '../review/handlers';
import { workerGrantInput } from './contracts';

export async function workerGrantRequest(request: Request, deps: {
  authorize: () => Promise<{userId:string}>;
  issue: (input: ReturnType<typeof workerGrantInput>, actor: string, origin: string) => string;
}) {
  try {
    const { userId } = await deps.authorize();
    if (request.method !== 'POST') return privateResponse(Response.json({code:'invalid_input'},{status:405}));
    if (!isSameOriginPost(request)) return privateResponse(Response.json({code:'wrong_origin'},{status:403}));
    if (new URL(request.url).search || request.headers.get('content-type')?.split(';')[0] !== 'application/json') throw new ReviewFailure('invalid_input');
    const reader = request.body?.getReader(); if (!reader) throw new ReviewFailure('invalid_input');
    const chunks:Uint8Array[]=[]; let length=0;
    while(true){ const {done,value}=await reader.read(); if(done)break; length+=value.length;
      if(length>4096){await reader.cancel();throw new ReviewFailure('invalid_input');} chunks.push(value); }
    let input;
    try { const bytes=new Uint8Array(length);let at=0;for(const part of chunks){bytes.set(part,at);at+=part.length;}
      input=workerGrantInput(JSON.parse(new TextDecoder().decode(bytes))); }
    catch { throw new ReviewFailure('invalid_input'); }
    return privateResponse(Response.json({ticket:deps.issue(input,userId,new URL(request.url).origin)}));
  } catch(error) { return failure(error); }
}
