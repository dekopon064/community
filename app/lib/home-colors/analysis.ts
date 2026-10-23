import sharp from 'sharp';
import type { HomeTone } from '../homeCardPalette';

export const imageByteLimit = 2 * 1024 * 1024;
export type ColorResult = { tone: HomeTone; reason: 'matched' | 'ambiguous' };

// Ignore transparent margins, white/gray areas and near-black lettering. A
// clearly dominant chromatic family is required; multi-color posters may default.
export function sampleTone(rgba: Uint8Array): ColorResult {
  const weights: Record<Exclude<HomeTone, 'default'>, number> = { orange: 0, yellow: 0, green: 0, blue: 0, purple: 0, red: 0 };
  let visible = 0, chromatic = 0;
  for (let i = 0; i + 3 < rgba.length; i += 4) {
    const alpha = rgba[i + 3] / 255;
    if (alpha < .5) continue;
    visible++;
    const r = rgba[i] / 255, g = rgba[i + 1] / 255, b = rgba[i + 2] / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b), delta = max - min;
    if (max < .2 || !delta || delta / max < .18) continue;
    let h = max === r ? (g - b) / delta : max === g ? 2 + (b - r) / delta : 4 + (r - g) / delta;
    h = (h * 60 + 360) % 360;
    const family = h < 15 || h >= 315 ? 'red' : h < 45 ? 'orange' : h < 75 ? 'yellow' : h < 185 ? 'green' : h < 260 ? 'blue' : 'purple';
    weights[family] += delta * alpha;
    chromatic++;
  }
  const ranked = Object.entries(weights).sort((a, b) => b[1] - a[1]);
  const total = ranked.reduce((sum, [, weight]) => sum + weight, 0);
  if (!visible || chromatic / visible < .08 || !total || ranked[0][1] / total < .55) return { tone: 'default', reason: 'ambiguous' };
  return { tone: ranked[0][0] as HomeTone, reason: 'matched' };
}

// Existing installed Sharp runtime; buffers only, no image paths/files/cache.
export async function analyzeHomeImage(bytes: Uint8Array): Promise<ColorResult> {
  if (!bytes.length || bytes.length > imageByteLimit) throw Error('image_size');
  // Check raster signatures before invoking any decoder, so an SVG/XML response
  // disguised as image/png never enters a vector/document renderer.
  const header = Buffer.from(bytes.subarray(0, 64));
  const raster = header.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))
    || header[0] === 255 && header[1] === 216 && header[2] === 255
    || ['GIF87a', 'GIF89a'].includes(header.subarray(0, 6).toString('ascii'))
    || header.subarray(0, 4).toString('ascii') === 'RIFF' && header.subarray(8, 12).toString('ascii') === 'WEBP'
    || header.subarray(4, 8).toString('ascii') === 'ftyp' && /avif|avis/.test(header.subarray(8).toString('ascii'));
  if (!raster) throw Error('image_format');
  const input = sharp(bytes, { limitInputPixels: 16_000_000, failOn: 'error', sequentialRead: true });
  const metadata = await input.metadata();
  if (!metadata.format || !['jpeg', 'png', 'webp', 'gif', 'heif'].includes(metadata.format)) throw Error('image_format');
  const { data } = await input.rotate().resize(48, 48, { fit: 'inside', withoutEnlargement: true })
    .toColourspace('srgb').ensureAlpha().raw().timeout({ seconds: 2 }).toBuffer({ resolveWithObject: true });
  return sampleTone(data);
}
