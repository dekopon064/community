import { privateResponse } from '../auth/http';
import { isSameOriginPost } from '../auth/urls';
import { failure } from './handlers';
import { ReviewFailure } from './contracts';
import { jobUuid } from './ai-queue';

type Dependencies = {
  authorize: () => Promise<{ userId: string }>;
  invoke: (name: string, args: Record<string, string>) => Promise<unknown>;
};

async function requestBody(request: Request) {
  if (request.headers.get('content-type')?.split(';')[0].trim() !== 'application/json') {
    throw new ReviewFailure('invalid_input');
  }
  const reader = request.body?.getReader();
  if (!reader) throw new ReviewFailure('invalid_input');
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let bytes = 0;
  let body = '';
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > 8192) {
        await reader.cancel();
        throw new Error();
      }
      body += decoder.decode(value, { stream: true });
    }
    return JSON.parse(body + decoder.decode());
  } catch {
    throw new ReviewFailure('invalid_input');
  }
}

export async function seoulCorrectionRequest(request: Request, id: string, deps: Dependencies) {
  try {
    const { userId } = await deps.authorize();
    const query = new URL(request.url).search;
    if (!jobUuid.test(id)) throw new ReviewFailure('invalid_input');
    if (request.method === 'GET') {
      if (query === '?view=candidate') return privateResponse(Response.json(
        await deps.invoke('admin_seoul_ai_candidate_review', { p_candidate: id }),
      ));
      if (query) throw new ReviewFailure('invalid_input');
      return privateResponse(Response.json({ draft: await deps.invoke('admin_seoul_ai_draft', { p_job: id }) }));
    }
    if (request.method !== 'POST' || query) throw new ReviewFailure('invalid_input');
    if (!isSameOriginPost(request)) return privateResponse(Response.json({ code: 'wrong_origin' }, { status: 403 }));
    const data = await requestBody(request);
    if (!data || typeof data !== 'object' || Object.keys(data).sort().join() !== 'before,draftId,evidence,field,value'
      || typeof data.draftId !== 'string' || !jobUuid.test(data.draftId)
      || !['ko', 'ja', 'jaTitle'].includes(data.field)
      || ![data.before, data.evidence, data.value].every((v) => typeof v === 'string' && v.trim() === v && v.length > 0)
      || data.before.length > 500 || data.evidence.length > 500 || data.value.length > 100) {
      throw new ReviewFailure('invalid_input');
    }
    const draft = await deps.invoke('admin_request_seoul_ai_correction', {
      p_id: data.draftId, p_job: id, p_actor: userId, p_field: data.field,
      p_before: data.before, p_evidence: data.evidence, p_value: data.value,
    });
    return privateResponse(Response.json({ draft }));
  } catch (error) {
    const code = (error as { code?: string } | null)?.code;
    if (code === 'PT409') return privateResponse(Response.json({ code: 'conflict' }, { status: 409 }));
    if (code === 'PT422') return privateResponse(Response.json({ code: 'invalid_input' }, { status: 422 }));
    return failure(error);
  }
}

