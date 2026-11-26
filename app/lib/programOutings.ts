import { filterDay, filterEndpoint, type FilterOccurrence } from './contentFilters';
import { endpointBoundary } from './publicContentFilters';
import type { LocalizedCuration } from './types';

export const viewingSubjects = {
  exhibition: ['전시 일반 관람', '展示の一般観覧'],
  garden: ['정원 일반 관람', '庭園の一般観覧'],
  facility: ['시설 일반 관람', '施設の一般見学'],
  other: ['직접 입력', '個別入力'],
} as const;
export type Viewing = {
  subject: keyof typeof viewingSubjects; reservationNotRequired: true;
  labelKo?: string; labelJa?: string;
  from: string; through: string; weekdays: number[]; exceptions: string[];
};
export function parseViewing(input: unknown): Viewing {
  if (!input || typeof input !== 'object') throw Error('invalid_viewing');
  const v = input as Viewing;
  const custom = v.subject === 'other';
  const readable = (label: unknown) => typeof label === 'string' && label.trim().length > 0 && label.length <= 80 && !/[<>\r\n]/.test(label);
  if (custom && (!readable(v.labelKo) || !readable(v.labelJa))) throw Error('invalid_viewing');
  if (typeof v.subject !== 'string' || !Object.hasOwn(viewingSubjects, v.subject) || v.reservationNotRequired !== true ||
      Object.keys(v).length !== (custom ? 8 : 6) || filterDay(v.from) > filterDay(v.through) ||
      !Array.isArray(v.weekdays) || !v.weekdays.length || v.weekdays.length > 7 ||
      v.weekdays.some(d => !Number.isInteger(d) || d < 0 || d > 6) ||
      new Set(v.weekdays).size !== v.weekdays.length || !Array.isArray(v.exceptions) ||
      v.exceptions.length > 366 || v.exceptions.some(d => filterDay(d) < v.from || d > v.through)) throw Error('invalid_viewing');
  return {subject:v.subject, reservationNotRequired:true, from:v.from, through:v.through,
    ...(custom ? {labelKo:v.labelKo!.trim(), labelJa:v.labelJa!.trim()} : {}),
    weekdays:[...v.weekdays].sort(), exceptions:[...new Set(v.exceptions)].sort()};
}

export function sameViewing(a: Viewing | null | undefined, b: Viewing | null | undefined) {
  if (a == null || b == null) return (a ?? null) === (b ?? null);
  try { return JSON.stringify(parseViewing(a)) === JSON.stringify(parseViewing(b)); }
  catch { return JSON.stringify(a) === JSON.stringify(b); }
}

type Visit = FilterOccurrence & {
  summary: string;
  title?: string;
  viewingDays?: string[];
};

// Inspect the wording around a work name; the original public title is always
// displayed verbatim, either in the heading or underneath it.
function viewingCopy(title: string, activity: string, hasBookedSession: boolean, ja: boolean) {
  const wording = title.trim().replace(/^(?:〈[^〉]+〉|《[^》]+》|「[^」]+」|『[^』]+』)\s*/u, '');
  const otherActivity = /해설|체험|수업|강좌|워크숍|투어|解説|体験|教室|講座|ワークショップ|ツアー/u;
  const bookingWording = wording.replace(/(?:사전\s*)?예약\s*(?:없이|없음|없는|불필요)|予約(?:なし|不要|のいらない)/gu, '');
  // A named guided program in the public title is enough to disambiguate
  // the card. It does not establish a booking requirement or a session date.
  const namesGuidedProgram = !wording.includes(activity) && /(?:해설|도슨트|解説|ドーセント|ドセント)(?:\s*(?:프로그램|プログラム))?$/u.test(wording);
  if (wording !== activity && (namesGuidedProgram || /예약|예매|신청|予約|申込|申し込/u.test(bookingWording)
      || (hasBookedSession && otherActivity.test(wording) && !otherActivity.test(activity)))) {
    return {title: activity, summary: ja ? '記事名：' + title : '글 제목 · ' + title};
  }
  return {summary: wording.includes(activity) ? '' : activity};
}
export function programVisit(row: LocalizedCuration, now: number, weekEnd: number, locale: string): Visit | undefined {
  const data = row.programOuting;
  if (!data || typeof data !== 'object' || row.userCategory !== 'program' || (row.contentFilters && row.contentFilters.category !== 'program') || row.contentFilters?.delivery.value === 'online') return;
  const {viewing, sessions} = data as {viewing?: unknown; sessions?: unknown};
  const visits: Visit[] = [];
  const ja = locale === 'ja';
  const datedSessions = Array.isArray(sessions) ? sessions : [];
  const hasBookedSession = datedSessions.some(session => session?.officialBooking === true);
  if (viewing) {
    try {
      const v = parseViewing(viewing);
      const kstMidnight = Math.floor((now + 9*3600000)/86400000)*86400000 - 9*3600000;
      const viewingDays: string[] = [];
      for (let t = kstMidnight; t < weekEnd; t += 86400000) {
        const noon = new Date(t + 12*3600000), date = noon.toISOString().slice(0,10);
        if (date < v.from || date > v.through || !v.weekdays.includes(noon.getUTCDay()) || v.exceptions.includes(date)) continue;
        viewingDays.push(date);
      }
      if (viewingDays.length) {
        // The first open day remains the selection and ordering key.
        const endpoint = {value: viewingDays[0], precision: 'day' as const};
        const activity = v.subject === 'other' ? (ja ? v.labelJa! : v.labelKo!) : viewingSubjects[v.subject][ja ? 1 : 0];
        visits.push({start: endpoint, end: endpoint, viewingDays, ...viewingCopy(row.title, activity, hasBookedSession, ja)});
      }
    } catch { /* Unverified viewing dates cannot supply a visit. */ }
  }
  const multipleActivities = Boolean(viewing) || hasBookedSession;
  for (const session of datedSessions) {
    // Only a reviewed, explicitly walk-in session may supply its date.
    if (session?.officialBooking !== false) continue;
    try {
      const start = filterEndpoint(session.start), end = filterEndpoint(session.end);
      if (start.value.slice(0,10) === end.value.slice(0,10) && start.precision === end.precision &&
          endpointBoundary(start) <= endpointBoundary(end,true) && endpointBoundary(start) < weekEnd &&
          (start.precision === 'day' ? endpointBoundary(end,true) > now : endpointBoundary(start) >= now)) {
        const label = multipleActivities
          ? (ja ? '予約不要の回' : '예약 없이 참여하는 회차') : '';
        visits.push({start, end, summary: label});
      }
    } catch { /* Legacy or incomplete evidence is optional. */ }
  }
  return visits.sort((a,b) => endpointBoundary(a.start)-endpointBoundary(b.start))[0];
}
