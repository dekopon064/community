import { lookup } from 'node:dns/promises';
import { request } from 'node:https';
import { BlockList, isIP } from 'node:net';
import { sourceImageUrl } from '../sourceImages';
import { imageByteLimit } from './analysis';

const blocked = new BlockList();
const pngSignature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
for (const [ip, prefix] of [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8], ['169.254.0.0', 16],
  ['172.16.0.0', 12], ['192.0.0.0', 24], ['192.0.2.0', 24], ['192.88.99.0', 24], ['192.168.0.0', 16],
  ['198.18.0.0', 15], ['198.51.100.0', 24], ['203.0.113.0', 24], ['224.0.0.0', 4], ['240.0.0.0', 4],
] as const) blocked.addSubnet(ip, prefix, 'ipv4');
const globalV6 = new BlockList(); globalV6.addSubnet('2000::', 3, 'ipv6');
const blockedV6 = new BlockList();
blockedV6.addSubnet('2001::', 23, 'ipv6'); blockedV6.addSubnet('2001:db8::', 32, 'ipv6');
blockedV6.addSubnet('2002::', 16, 'ipv6'); blockedV6.addSubnet('3fff::', 20, 'ipv6');

export function isPublicImageAddress(address: string): boolean {
  return isIP(address) === 4 ? !blocked.check(address, 'ipv4')
    : isIP(address) === 6 && globalV6.check(address, 'ipv6') && !blockedV6.check(address, 'ipv6');
}

type ImageRequest = typeof request;
type ImageLookup = (hostname: string) => Promise<readonly { address: string; family: number }[]>;

// Dependency injection exercises the real downloader without any external DNS/HTTP.
export function imageDownloader(resolve: ImageLookup, connect: ImageRequest) {
  return async (value: string): Promise<Uint8Array> => {
    const safe = sourceImageUrl(value);
    if (!safe || safe !== value) throw Error('image_url');
    const url = new URL(safe), controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const addresses = await Promise.race([
        resolve(url.hostname),
        new Promise<never>((_, reject) => controller.signal.addEventListener('abort', () => reject(Error('image_timeout')), { once: true })),
      ]);
      if (!addresses.length || addresses.some(a => !isPublicImageAddress(a.address))) throw Error('image_address');
      if (controller.signal.aborted) throw Error('image_timeout');
      // Connect to the checked IP, retaining the original hostname for TLS and
      // Host. No second DNS lookup, redirects, credentials or request retries.
      return await new Promise<Uint8Array>((resolveBytes, reject) => {
        const req = connect({ hostname: addresses[0].address, family: addresses[0].family, port: 443,
          servername: url.hostname, method: 'GET', path: url.pathname + url.search, agent: false,
          signal: controller.signal, headers: { Host: url.hostname, Accept: 'image/jpeg,image/png,image/webp,image/gif,image/avif' } }, res => {
          const type = res.headers['content-type']?.split(';')[0].trim().toLowerCase();
          const declared = res.headers['content-length'];
          // Some official download endpoints label real PNG files as binary.
          // Admit only that MIME provisionally; verify PNG bytes below, then
          // retain the analyzer's full raster decode/pixel limits.
          const binaryPng = type === 'application/octet-stream';
          if (res.statusCode !== 200 || !type || !binaryPng && !['image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/avif'].includes(type)
            || declared && (!/^\d+$/.test(declared) || Number(declared) > imageByteLimit)) {
            res.destroy(); reject(Error('image_response')); return;
          }
          let length = 0, stopped = false; const chunks: Buffer[] = [];
          res.on('data', (chunk: Buffer) => {
            if (stopped) return;
            length += chunk.length;
            if (length > imageByteLimit) { stopped = true; res.destroy(); reject(Error('image_size')); }
            else chunks.push(chunk);
          });
          res.on('end', () => {
            if (stopped) return;
            const bytes = Buffer.concat(chunks, length);
            if (binaryPng && !bytes.subarray(0, 8).equals(pngSignature)) reject(Error('image_format'));
            else resolveBytes(bytes);
          });
          res.on('error', () => reject(Error('image_download')));
          res.on('aborted', () => reject(Error('image_download')));
        });
        req.on('error', () => reject(Error('image_download'))); req.end();
      });
    } finally { clearTimeout(timer); }
  };
}

export const downloadHomeImage = imageDownloader(hostname => lookup(hostname, { all: true, verbatim: true }), request);
