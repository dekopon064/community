import { privateResponse } from '../auth/http';
import { isSameOriginPost } from '../auth/urls';
import { ReviewFailure } from '../review/contracts';
import { failure } from '../review/handlers';
import { featuredCommand, type FeaturedStore } from './admin';

export async function featuredRequest(request: Request, id: string, deps: { authorize: () => Promise<{ userId: string }>; store: () => FeaturedStore }) {
  try {
    const { userId } = await deps.authorize();
    if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(id)) throw new ReviewFailure('invalid_input');
    if (request.method === 'GET') return privateResponse(Response.json({ item: await deps.store().get(id) }));
    if (request.method !== 'POST') throw new ReviewFailure('invalid_input');
    if (!isSameOriginPost(request)) return privateResponse(Response.json({ code: 'wrong_origin' }, { status: 403 }));
    if (request.headers.get('content-type')?.split(';')[0].trim() !== 'application/json' || Number(request.headers.get('content-length')) > 4096) throw new ReviewFailure('invalid_input');
    const reader = request.body?.getReader(); if (!reader) throw new ReviewFailure('invalid_input');
    const chunks: Uint8Array[] = []; let size = 0;
    while (true) { const { value, done } = await reader.read(); if (done) break; size += value.length;
      if (size > 4096) { await reader.cancel(); throw new ReviewFailure('invalid_input'); } chunks.push(value); }
    const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    let raw: unknown; try { raw = JSON.parse(new TextDecoder().decode(bytes)); } catch { throw new ReviewFailure('invalid_input'); }
    return privateResponse(Response.json({ item: await deps.store().save(id, featuredCommand(raw), userId) }));
  } catch (e) { return failure(e); }
}
