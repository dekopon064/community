import { ReviewFailure } from '../review/contracts';

export const livingImageLimit = 20;
export const livingImageBytes = 4 * 1024 * 1024;
export const imageId = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(v);
export type LivingImage = { id: string; altKo: string; altJa: string };
export function parseLivingImages(value: unknown): LivingImage[] {
  if (!Array.isArray(value) || value.length > livingImageLimit) throw new ReviewFailure('invalid_input');
  const ids = new Set<string>();
  return value.map(v => {
    if (!v || typeof v !== 'object' || Object.keys(v).sort().join(',') !== 'altJa,altKo,id' || !imageId(v.id) || ids.has(v.id)
      || typeof v.altKo !== 'string' || typeof v.altJa !== 'string' || v.altKo.length > 500 || v.altJa.length > 500) throw new ReviewFailure('invalid_input');
    ids.add(v.id); return { id: v.id, altKo: v.altKo, altJa: v.altJa };
  });
}
export const livingImageSrc = (id: string, admin = false) => `/api/${admin ? 'admin/' : ''}living/images/${id}`;
