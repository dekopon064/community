import type { RpcClient } from '../review/database-store';
import type { HomeItem } from '../homePresentation';
import { homeCardPalette, type HomeTone } from '../homeCardPalette';

export async function attachHomeCardColors(items: readonly HomeItem[], client: RpcClient): Promise<HomeItem[]> {
  const fallback = () => items.map(item => ({ ...item, tone: 'default' as const }));
  if (!items.length) return [];
  try {
    const { data, error } = await client.rpc('public_home_card_colors', { p_ids: items.map(item => item.id) });
    if (error || !Array.isArray(data)) return fallback();
    const requested = new Set(items.map(item => item.id)), colors = new Map<string, { tone: HomeTone; ready: boolean }>();
    for (const row of data) {
      if (!row || typeof row !== 'object' || !requested.has(row.id) || colors.has(row.id) || typeof row.ready !== 'boolean'
        || typeof row.tone !== 'string' || !Object.hasOwn(homeCardPalette, row.tone)) return fallback();
      colors.set(row.id, { tone: row.tone, ready: row.ready });
    }
    // Only preparation suppresses a new card briefly. The server releases it to
    // default on expiry; neither reads nor page views start/restart analysis.
    return items.filter(item => colors.get(item.id)?.ready).map(item => ({ ...item, tone: colors.get(item.id)!.tone }));
  } catch { return fallback(); }
}
