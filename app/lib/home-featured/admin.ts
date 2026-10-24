import type { RpcClient } from '../review/database-store';
import { ReviewFailure } from '../review/contracts';

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const hash = /^[a-f0-9]{64}$/;
export type FeaturedPin = { id: string; position: 1 | 2; title: string; eligible: boolean };
export type FeaturedDetail = { id: string; publishedId: string; revision: string; version: string; stateVersion: number;
  position: 1 | 2 | null; eligible: boolean; pins: FeaturedPin[] };
export type FeaturedCommand = { revision: string; version: string; targetId: string; position: 1 | 2 | null; requestId: string };
function object(raw: unknown): Record<string, unknown> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new ReviewFailure('invalid_input');
  return raw as Record<string, unknown>;
}
export function featuredCommand(raw: unknown): FeaturedCommand {
  const v = object(raw);
  if (Object.keys(v).sort().join(',') !== 'position,requestId,revision,targetId,version'
    || typeof v.revision !== 'string' || !hash.test(v.revision) || typeof v.version !== 'string' || !hash.test(v.version)
    || typeof v.targetId !== 'string' || !uuid.test(v.targetId) || typeof v.requestId !== 'string' || !uuid.test(v.requestId)
    || v.position !== null && v.position !== 1 && v.position !== 2) throw new ReviewFailure('invalid_input');
  return { revision: v.revision, version: v.version, targetId: v.targetId, requestId: v.requestId, position: v.position };
}
export function featuredDetail(raw: unknown, id: string): FeaturedDetail {
  try {
    const v = object(raw);
    if (v.id !== id || typeof v.publishedId !== 'string' || !uuid.test(v.publishedId)
      || typeof v.revision !== 'string' || !hash.test(v.revision) || typeof v.version !== 'string' || !hash.test(v.version)
      || !Number.isSafeInteger(v.stateVersion) || Number(v.stateVersion) < 0 || typeof v.eligible !== 'boolean'
      || v.position !== null && v.position !== 1 && v.position !== 2 || !Array.isArray(v.pins) || v.pins.length > 2) throw Error('invalid');
    const pins: FeaturedPin[] = v.pins.map((value, i) => {
      const p = object(value);
      if (typeof p.id !== 'string' || !uuid.test(p.id) || p.position !== i + 1 || typeof p.title !== 'string'
        || !p.title.trim() || typeof p.eligible !== 'boolean') throw Error('invalid');
      return { id: p.id, title: p.title, position: p.position as 1 | 2, eligible: p.eligible };
    });
    if (new Set(pins.map(x => x.id)).size !== pins.length || (pins.find(x => x.id === v.publishedId)?.position ?? null) !== v.position) throw Error('invalid');
    return { id, publishedId: v.publishedId, revision: v.revision, version: v.version, stateVersion: Number(v.stateVersion),
      position: v.position, eligible: v.eligible, pins };
  } catch { throw new ReviewFailure('unavailable'); }
}
export class FeaturedStore {
  constructor(private client: RpcClient) {}
  private async invoke(name: string, args: Record<string, unknown>) {
    try {
      const { data, error } = await this.client.rpc(name, args);
      if (error) throw new ReviewFailure(error.message === 'home_featured_conflict' ? 'conflict'
        : error.message === 'home_featured_not_found' ? 'not_found'
        : ['home_featured_invalid', 'home_featured_full', 'home_featured_ineligible'].includes(error.message ?? '') ? 'invalid_input' : 'unavailable');
      return data;
    } catch (e) { if (e instanceof ReviewFailure) throw e; throw new ReviewFailure('unavailable'); }
  }
  async get(id: string) { return featuredDetail(await this.invoke('admin_review_home_featured', { p_id: id }), id); }
  async save(id: string, command: FeaturedCommand, actor: string) {
    const item = featuredDetail(await this.invoke('admin_review_set_home_featured', {
      p_id: id, p_revision: command.revision, p_version: command.version, p_target: command.targetId,
      p_position: command.position, p_request: command.requestId, p_actor: actor,
    }), id);
    if (item.revision !== command.revision || item.version === command.version
      || (item.pins.find(x => x.id === command.targetId)?.position ?? null) !== command.position) throw new ReviewFailure('unavailable');
    return item;
  }
}
