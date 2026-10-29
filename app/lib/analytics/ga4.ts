export type Ga4Config = Readonly<{ measurementId: string; origin: string }>;
export type Ga4Page = { path: string; location: string; language: 'ko' | 'ja'; slug?: string };
const categories = 'policy|program|event|youth_space|living';
const publicPath = new RegExp(`^/(ko|ja)(?:/(?:privacy|qna|feedback|info(?:/category/(?:${categories})|/[a-z0-9][a-z0-9_-]{0,159})?))?$`);

function publicOrigin(value: string): string | null {
  try {
    const u = new URL(value);
    if (u.protocol !== 'https:' || u.username || u.password || u.port || u.pathname !== '/' || u.search || u.hash ||
        !/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}$/i.test(u.hostname) ||
        /\.(localhost|local|internal|test|invalid)$/i.test(u.hostname)) return null;
    return u.origin;
  } catch { return null; }
}

// Activation is deliberately explicit. Before setting the readiness flag, the
// GA4 web stream's Enhanced Measurement must be OFF (including history-based
// pageviews and outbound clicks). send_page_view:false alone does not stop it.
// No environment file, Google account or remote setting is changed by this code.
export function ga4Config(env: Record<string, string | undefined>): Ga4Config | null {
  if (env.NODE_ENV !== 'production' || env.VERCEL_ENV !== 'production' ||
      env.GA4_MANUAL_MEASUREMENT_READY !== 'true' || !/^G-[A-Z0-9]{6,20}$/.test(env.GA4_MEASUREMENT_ID ?? '')) return null;
  const origin = publicOrigin(env.GA4_SITE_ORIGIN ?? '');
  return origin ? Object.freeze({ measurementId: env.GA4_MEASUREMENT_ID!, origin }) : null;
}

export function ga4Page(config: Ga4Config, href: string): Ga4Page | null {
  try {
    const u = new URL(href);
    if (u.origin !== config.origin || u.username || u.password || !publicPath.test(u.pathname)) return null;
    const campaign = new URLSearchParams();
    for (const key of ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_id']) {
      const value = u.searchParams.get(key);
      // Do not forward search terms, auth fragments, IDs or arbitrary URL data.
      if (value && value.length <= 100 && /^[\p{L}\p{N}_.~-]+$/u.test(value)) campaign.set(key, value);
    }
    const query = campaign.toString();
    const detail = /^\/(ko|ja)\/info\/([a-z0-9][a-z0-9_-]{0,159})$/.exec(u.pathname);
    return { path: u.pathname, location: config.origin + u.pathname + (query ? '?' + query : ''),
      language: u.pathname.startsWith('/ja') ? 'ja' : 'ko', ...(detail ? { slug: detail[2] } : {}) };
  } catch { return null; }
}

export function ga4Referrer(config: Ga4Config, value: string): string {
  try {
    const u = new URL(value);
    if (u.username || u.password) return '';
    if (u.origin === config.origin) return ga4Page(config, value)?.path ? u.origin + u.pathname : '';
    // Only the external origin is needed for referral attribution.
    return publicOrigin(u.origin) ?? '';
  } catch { return ''; }
}

export function ga4OfficialUrl(value: string, origin: string): { url: string; domain: string } | null {
  try {
    const u = new URL(value);
    if (!['http:', 'https:'].includes(u.protocol) || u.username || u.password || u.origin === origin ||
        !publicOrigin('https://' + u.host)) return null;
    return { url: u.origin + u.pathname, domain: u.hostname };
  } catch { return null; }
}
