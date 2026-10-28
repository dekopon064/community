import sharp from 'sharp';
import { createHash } from 'node:crypto';
import { ReviewFailure } from '../review/contracts';
import { livingImageBytes } from './images';

export async function normalizeLivingImage(bytes: Uint8Array, mime: string) {
  if (!bytes.length || bytes.length > livingImageBytes) throw new ReviewFailure('invalid_input', { images: '이미지는 한 장당 4MiB 이내로 선택해 주세요.' });
  const b = Buffer.from(bytes);
  const format = b.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10])) ? 'png'
    : b[0] === 255 && b[1] === 216 && b[2] === 255 ? 'jpeg'
    : b.subarray(0,4).toString() === 'RIFF' && b.subarray(8,12).toString() === 'WEBP' ? 'webp' : null;
  if (!format || mime !== `image/${format}`) throw new ReviewFailure('invalid_input', { images: '정상 PNG·JPEG·WebP 이미지 파일을 선택해 주세요.' });
  try {
    const input = sharp(b, { limitInputPixels: 16_000_000, failOn: 'error', sequentialRead: true });
    const meta = await input.metadata();
    if (meta.format !== format || (meta.pages ?? 1) !== 1) throw Error('format');
    // Preserve all pixels/text; strip metadata and never execute SVG/HTML. No resizing or AI.
    const { data, info } = await input.rotate().webp({ lossless: true }).timeout({ seconds: 3 }).toBuffer({ resolveWithObject: true });
    if (data.length > livingImageBytes) throw Error('size');
    return { data, hash: createHash('sha256').update(data).digest('hex'), width: info.width, height: info.height, size: data.length };
  } catch { throw new ReviewFailure('invalid_input', { images: '이미지를 읽지 못했습니다. 정지 이미지·4MiB 이내·1,600만 픽셀 이내인지 확인해 주세요.' }); }
}
