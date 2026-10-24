import type { CandidateItem } from '../review/contracts';
import type { RpcClient } from '../review/database-store';
import { analyzeHomeImage } from './analysis';
import { downloadHomeImage } from './download';

export type HomeColorOutcome = 'completed' | 'completed_default' | 'failed' | 'no_image' | 'unchanged' | 'unavailable';
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function preparePublishedHomeColor(client: RpcClient, item: CandidateItem, actor: string,
  loadImage: (url: string) => Promise<Uint8Array> = downloadHomeImage): Promise<HomeColorOutcome> {
  if (item.status !== 'published' || !item.publishedId || !uuid.test(item.publishedId) || !uuid.test(item.id) || !uuid.test(actor)) return 'unavailable';
  let claim;
  try {
    const out = await client.rpc('admin_home_color_claim', { p_id: item.publishedId, p_candidate: item.id, p_actor: actor });
    if (out.error || !out.data || typeof out.data !== 'object') return 'unavailable';
    claim = out.data as Record<string, unknown>;
  } catch { return 'unavailable'; }
  if (claim.state === 'no_image') return 'no_image';
  if (claim.state === 'settled') return 'unchanged';
  if (claim.state !== 'claimed' || typeof claim.token !== 'string' || !uuid.test(claim.token) || typeof claim.url !== 'string') return 'unavailable';
  let tone = 'default', state: 'completed' | 'failed' = 'failed', reason = 'analysis_failed';
  try {
    const result = await analyzeHomeImage(await loadImage(claim.url));
    tone = result.tone; reason = result.reason; state = 'completed';
  } catch { /* Fixed, non-secret diagnostic; no URL/error text or retry. */ }
  try {
    const out = await client.rpc('admin_home_color_finish', { p_id: item.publishedId, p_token: claim.token, p_actor: actor, p_tone: tone, p_state: state, p_reason: reason });
    if (out.error || !out.data || typeof out.data !== 'object') return 'unavailable';
    const result = out.data as Record<string, unknown>;
    if (result.state === 'completed' && state === 'completed' && result.tone === tone) return tone === 'default' ? 'completed_default' : 'completed';
    return result.state === 'failed' && result.tone === 'default' ? 'failed' : 'unavailable';
  } catch { return 'unavailable'; } // Completion may have committed: never repeat it.
}
