import type { RpcClient } from '../review/database-store';
import type { HomePin } from '../homeSelection';

// Public IDs/order only. An unavailable migration/RPC preserves automatic fill.
export async function readHomePins(client: RpcClient): Promise<HomePin[]> {
  try {
    const { data, error } = await client.rpc('public_home_featured_pins', {});
    if (error || !Array.isArray(data) || data.length > 2) return [];
    const pins: HomePin[] = [];
    for (const value of data) {
      if (!value || typeof value !== 'object' || Object.keys(value).sort().join(',') !== 'id,position'
        || typeof value.id !== 'string' || !/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(value.id)
        || ![1, 2].includes(value.position) || pins.some(x => x.id === value.id || x.position === value.position)) return [];
      pins.push({ id: value.id, position: value.position });
    }
    return pins.sort((a, b) => a.position - b.position);
  } catch { return []; }
}
