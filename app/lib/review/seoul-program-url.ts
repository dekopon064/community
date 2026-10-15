// Validate the stored usable URL, without decoding or rewriting its spelling.
// Keep these routes/query types aligned with ingest/seoul_links.py and the
// private seoul_program_url_valid SQL contract. No network or redirect lookup.
const externalRoutes = new Map<string, { required: string[]; optional: string[] }>([
  ['umppa.seoul.go.kr/icare/user/chilProgrm/orgideaExprnCtzn/BD_selectOrgideaExprnCtzn.do', { required: ['q_progrmCl', 'q_placeCode', 'q_progrmSn'], optional: [] }],
  ['kctg.or.kr/tour/touristSiteView.do', { required: ['tourist_cd'], optional: ['page_no'] }],
  ['www.kctg.or.kr/tour/touristSiteView.do', { required: ['tourist_cd'], optional: ['page_no'] }],
  ['firesafety.eseoul.go.kr/multi/main.do', { required: [], optional: [] }],
  ['culture.gangseo.seoul.kr/gsfc/education/view.do', { required: ['eduSn'], optional: ['menuNo'] }],
]);

export function isSeoulProgramUrl(value: string): boolean {
  if (value.length > 2048 || /[\s\\]/.test(value) || [...value].some(c => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127)) return false;
  if (/^https?:\/\/yeyak\.seoul\.go\.kr\/web\/reservation\/selectReservView\.do\?rsv_svc_id=[A-Za-z0-9_-]+$/.test(value)) return true;
  const match = /^https:\/\/([^/?#]+)(\/[^?#]*)(?:\?([^#]*))?$/.exec(value);
  if (!match) return false;
  const route = externalRoutes.get(match[1] + match[2]);
  if (!route) return false;
  const seen = new Set<string>();
  const query = match[3] ?? '';
  if (query) {
    for (const pair of query.split('&')) {
      const equals = pair.indexOf('=');
      if (equals < 1) return false;
      const name = pair.slice(0, equals);
      if (seen.has(name) || !route.required.includes(name) && !route.optional.includes(name)) return false;
      let decoded: string;
      try { decoded = decodeURIComponent(pair.slice(equals + 1).replace(/\+/g, ' ')); }
      catch { return false; }
      if (name === 'tourist_cd' ? !/^[A-Za-z0-9_-]{1,128}$/.test(decoded) : !(name === 'page_no' && decoded === '') && !/^[0-9]{1,32}$/.test(decoded)) return false;
      seen.add(name);
    }
  }
  return route.required.every(name => seen.has(name));
}
