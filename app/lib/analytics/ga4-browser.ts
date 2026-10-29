import { ga4OfficialUrl, ga4Page, ga4Referrer, type Ga4Config, type Ga4Page } from './ga4';

type Params = Record<string, string | boolean>;
type Command = (...args: unknown[]) => void;
type AnalyticsWindow = Window & Pick<typeof globalThis, 'MutationObserver'> & { dataLayer?: IArguments[]; gtag?: Command; __machimoaGa4?: Ga4Runtime };
export type Ga4Runtime = { config: Ga4Config; connect(): () => void; sync(): void };

// One document-wide runtime survives StrictMode and locale-layout remounts.
// The Window parameter is the only test seam; no production bypass flag exists.
export function createGa4Runtime(config: Ga4Config, browser: Window): Ga4Runtime | null {
  const win = browser as AnalyticsWindow, doc = browser.document;
  const disableKey = 'ga-disable-' + config.measurementId;
  const existingDisable = Object.getOwnPropertyDescriptor(win, disableKey);
  if (existingDisable?.get || existingDisable?.set || existingDisable?.configurable === false || win.gtag || win.dataLayer?.length) return null;
  let optedOut = existingDisable?.value === true;
  let clients = 0, loaded = false, broken = false, pending = false, generation = 0;
  let audience: 'unknown' | 'public' | 'excluded' = 'unknown';
  let lastPath: string | null = null, previousPublic = '', firstView = true;
  let observer: MutationObserver | null = null;
  let gtag: Command | null = null;

  const page = () => ga4Page(config, win.location.href);
  const content = (p: Ga4Page) => {
    if (!p.slug) return null;
    const element = doc.querySelector<HTMLElement>('[data-ga4-content-slug]');
    return element?.dataset.ga4ContentSlug === p.slug && element.dataset.ga4ContentLanguage === p.language
      ? element : null;
  };
  const canCollect = () => {
    const p = page();
    return !broken && !optedOut && clients > 0 && audience === 'public' && !!p && lastPath === p.path &&
      (!p.slug || !!content(p)) && win.navigator.doNotTrack !== '1';
  };
  try {
    // Google checks this property before cookies or transmission. A getter also
    // excludes private navigation immediately, before React effects can run.
    Object.defineProperty(win, disableKey, { configurable: false, get: () => !canCollect(),
      set: (value: unknown) => { optedOut = value === true; } });
  } catch { return null; }

  function stopObserving() { observer?.disconnect(); observer = null; }
  function startObserving() {
    if (observer) return;
    const next = new win.MutationObserver(() => sync());
    next.observe(doc.body, { childList: true, subtree: true, attributes: true,
      attributeFilter: ['data-ga4-content-slug', 'data-ga4-content-language', 'data-ga4-content-title'] });
    observer = next;
  }
  function boot() {
    if (loaded) return;
    loaded = true;
    win.dataLayer ??= [];
    // gtag's documented command queue uses Arguments objects, not saved data.
    // eslint-disable-next-line prefer-rest-params -- Keep Google's documented gtag Arguments queue format.
    gtag = function () { win.dataLayer!.push(arguments); };
    win.gtag = gtag;
    gtag('js', new Date());
    gtag('set', { send_page_view: false, allow_google_signals: false, allow_ad_personalization_signals: false });
    const script = doc.createElement('script');
    script.id = 'machimoa-ga4'; script.async = true;
    script.src = 'https://www.googletagmanager.com/gtag/js?id=' + config.measurementId;
    script.addEventListener('error', () => { broken = true; }, { once: true });
    doc.head.appendChild(script);
  }
  function refresh(force = false) {
    if (!clients || !page() || pending && !force) return;
    audience = 'unknown'; pending = true;
    const current = ++generation;
    // Reuse the existing verified administrator guard; never send its response,
    // user UUID, display name or any authentication data to Google.
    void win.fetch('/api/admin/access', { credentials: 'same-origin', cache: 'no-store' })
      .then(async response => {
        const data: unknown = await response.json();
        const status = data && typeof data === 'object' && 'status' in data ? data.status : null;
        return response.status === 401 && status === 'signed_out' || response.status === 403 && status === 'forbidden';
      }).catch(() => false).then(allowed => {
        if (current !== generation) return;
        pending = false;
        audience = clients && page() && allowed ? 'public' : 'excluded';
        if (audience === 'public') sync();
      });
  }
  function sync() {
    if (!clients || broken || optedOut || win.navigator.doNotTrack === '1') return;
    const p = page();
    if (!p) {
      stopObserving(); lastPath = null; previousPublic = ''; audience = 'unknown'; pending = false; generation++;
      return;
    }
    if (audience === 'unknown') { refresh(); return; }
    if (audience !== 'public') return;
    const marker = content(p);
    // Wait for the correct published detail, not a streamed loading shell or a
    // preceding locale's content. A 404 never supplies this marker.
    if (p.slug && !marker) { startObserving(); return; }
    stopObserving();
    if (lastPath === p.path) return;
    const params: Params = { page_location: p.location, page_referrer: previousPublic || (firstView ? ga4Referrer(config, doc.referrer) : ''),
      page_title: marker?.dataset.ga4ContentTitle?.slice(0, 300) || 'Machimoa ' + p.path,
      content_language: p.language, ...(p.slug ? { content_id: p.slug } : {}) };
    lastPath = p.path;
    try {
      boot();
      // Retain GA4's native engagement measurement. Do not invent a second
      // dwell-time timer or send synthetic user_engagement events.
      gtag!('config', config.measurementId, { ...params, send_page_view: false, allow_google_signals: false, allow_ad_personalization_signals: false });
      gtag!('event', 'page_view', { ...params, send_to: config.measurementId });
      previousPublic = config.origin + p.path;
      firstView = false;
    } catch { broken = true; }
  }
  function click(event: MouseEvent) {
    if (event.defaultPrevented || event.type === 'click' && event.button !== 0 || event.type === 'auxclick' && event.button !== 1 || !canCollect()) return;
    const target = event.target as Element | null;
    const anchor = target?.closest?.<HTMLAnchorElement>('a[data-ga4-official-link]');
    const placement = anchor?.dataset.ga4OfficialLink;
    const p = page();
    if (!anchor || !p?.slug || !['mobile_source', 'trust_panel'].includes(placement ?? '')) return;
    const link = ga4OfficialUrl(anchor.href, config.origin);
    if (!link) return;
    // Synchronous enqueue only: never prevent navigation, wait or retry clicks.
    try { gtag?.('event', 'official_link_click', { send_to: config.measurementId, page_location: p.location,
      content_id: p.slug, content_language: p.language, link_url: link.url, link_domain: link.domain,
      link_placement: placement!, outbound: true }); } catch { broken = true; }
  }
  const focus = () => refresh();
  const account = () => {
    // A newly eligible identity must not inherit another account's view ledger.
    lastPath = null; previousPublic = '';
    refresh(true);
  };
  return {
    config,
    sync,
    connect() {
      clients++;
      if (clients === 1) {
        audience = 'unknown';
        doc.addEventListener('click', click); doc.addEventListener('auxclick', click);
        win.addEventListener('focus', focus); win.addEventListener('pageshow', focus);
        win.addEventListener('machimoa-account-change', account);
      }
      sync();
      let released = false;
      return () => {
        if (released) return; released = true; clients--;
        if (clients) return;
        stopObserving();
        doc.removeEventListener('click', click); doc.removeEventListener('auxclick', click);
        win.removeEventListener('focus', focus); win.removeEventListener('pageshow', focus);
        win.removeEventListener('machimoa-account-change', account);
      };
    },
  };
}

export function browserGa4(config: Ga4Config, browser: Window): Ga4Runtime | null {
  const win = browser as AnalyticsWindow;
  if (win.__machimoaGa4) return win.__machimoaGa4.config.measurementId === config.measurementId &&
    win.__machimoaGa4.config.origin === config.origin ? win.__machimoaGa4 : null;
  const runtime = createGa4Runtime(config, browser);
  if (runtime) win.__machimoaGa4 = runtime;
  return runtime;
}
