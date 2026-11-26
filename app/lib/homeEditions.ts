import { programVisit } from './programOutings';
import { todayKst, formatPublicEndpoint } from './applicationDeadlineDisplay';
import { endpointBoundary, occurrences } from './publicContentFilters';
import { homeWeek } from './homeSelection';
import type { LocalizedCuration } from './types';

const settlementGuides = [
  { slug: 'living-458e3b16-fa16-4d00-a6e9-b0beb143d41b', label: '空港からの移動' },
  { slug: 'living-d24cd543-e5d6-4de9-a26c-09a0f9b1ec6b', label: 'スマホの通信' },
  { slug: 'living-1b47f436-f08f-4584-948a-d08fccb2a088', label: '外国人登録' },
] as const;

export function settlementArticles(rows: readonly LocalizedCuration[]) {
  return settlementGuides.flatMap(({ slug, label }) => {
    const row = rows.find(article => article.slug === slug && article.userCategory === 'living');
    return row ? [{ slug, label, title: row.title, imageUrl: row.source_image_url }] : [];
  });
}

export function isSeoulCulture(row: LocalizedCuration) {
  const facts = row.contentFilters;
  if (!facts || facts.category !== row.userCategory || facts.topic.status !== 'known'
    || facts.location.status !== 'known' || !facts.location.value.venues.some(venue => venue.province === '11')) return false;
  return facts.category === 'program' ? facts.topic.value === 'culture_experience'
    : facts.category === 'event' && ['culture_arts', 'festival_exchange'].includes(facts.topic.value);
}

export function cultureContext(row: LocalizedCuration, locale: string, translate: (key: string) => string) {
  const facts = row.contentFilters;
  if (facts?.topic.status !== 'known' || facts.location.status !== 'known') return undefined;
  const topic = translate(`${facts.category === 'program' ? 'programTopics' : 'eventTopics'}.${facts.topic.value}`);
  const regions = facts.location.value.venues.map(({ province, district }) => {
    const name = translate(`provinces.${province}`);
    return district ? name + ' ' + (locale === 'ja' ? translate(`districts.${province}.${district}`) : district) : name;
  });
  return [topic, ...new Set(regions)].join(' · ');
}

export type WeeklyEntry = {
  slug: string; title: string; summary: string; imageUrl: string | null;
  date: string; dayLabel: string; details: string;
};
// Dates arrive in ascending KST calendar order from the verified viewing calendar.
function viewingCalendar(days: string[], locale: string) {
  const ranges: {first: string; last: string}[] = [];
  for (const date of days) {
    const previous = ranges[ranges.length - 1];
    if (previous && Date.parse(date) - Date.parse(previous.last) === 86400000) previous.last = date;
    else ranges.push({first: date, last: date});
  }
  const ja = locale === 'ja';
  const month = (iso: string) => Number(iso.slice(5,7)) + (ja ? '月' : '월');
  const day = (iso: string) => Number(iso.slice(8));
  const oneMonth = days[0].slice(0,7) === days[days.length - 1].slice(0,7);
  if (oneMonth && ranges.length === 1) {
    return {date: day(days[0]) + '–' + day(days[days.length - 1]), dayLabel: month(days[0]), detail: ''};
  }
  const suffix = ja ? '日' : '일', dash = ja ? '〜' : '–';
  const prefix = (iso: string) => month(iso) + (ja ? '' : ' ');
  const detail = ranges.map(({first, last}) => {
    const crossMonth = first.slice(0,7) !== last.slice(0,7);
    const start = (oneMonth ? '' : prefix(first)) + day(first);
    if (first === last) return start + suffix;
    return start + (crossMonth ? suffix : '') + dash + (crossMonth ? prefix(last) : '') + day(last) + suffix;
  }).join(ja ? '、' : ', ');
  const viewingLabel = ja ? '観覧日' : '관람일';
  return {date: oneMonth ? month(days[0]) : viewingLabel, dayLabel: oneMonth ? viewingLabel : '', detail};
}

export function weeklyOutings(rows: readonly LocalizedCuration[], now: number, locale: string) {
  const week = homeWeek(now);
  const monthDay = new Intl.DateTimeFormat(locale, { timeZone: 'Asia/Seoul', month: 'short', day: 'numeric' });
  const month = new Intl.DateTimeFormat(locale, { timeZone: 'Asia/Seoul', month: 'short' });
  const weekday = new Intl.DateTimeFormat(locale, { timeZone: 'Asia/Seoul', weekday: 'long' });
  const candidates = rows.flatMap(row => {
    const visit = row.userCategory === 'program' ? programVisit(row,now,week.end,locale) : undefined;
    const meeting = visit ?? (row.userCategory === 'event' ? occurrences(row).find(o =>
      endpointBoundary(o.start) < week.end && endpointBoundary(o.end, true) > now) : undefined);
    if (!meeting) return [];
    const start = endpointBoundary(meeting.start);
    const from = todayKst(new Date(Math.max(week.start, start)));
    const to = todayKst(new Date(Math.min(week.end, endpointBoundary(meeting.end, true)) - 1));
    const day = (iso: string) => String(Number(iso.slice(8)));
    const date = from === to ? day(from) : day(from) + '–' + day(to);
    const times = [formatPublicEndpoint(meeting.start,locale), formatPublicEndpoint(meeting.end,locale)];
    const location = row.contentFilters?.location;
    const venues = location?.status === 'known' ? location.value.venues.map(v => v.facility || v.address).filter(Boolean) : [];
    let dayLabel = locale === 'ja' ? '今週' : '이번 주';
    if (from === to) {
      dayLabel = weekday.format(new Date(from + 'T12:00:00+09:00'));
    } else if (from.slice(5, 7) !== to.slice(5, 7)) {
      dayLabel = [from, to].map(day => month.format(new Date(day + 'T12:00:00+09:00'))).join(' → ');
    }
    const calendar = visit?.viewingDays && visit.viewingDays.length > 1
      ? viewingCalendar(visit.viewingDays, locale) : undefined;
    const when = calendar ? calendar.detail : times[0] === times[1] ? times[0] : times.join(' – ');
    const entry: WeeklyEntry = {
      slug: row.slug, title: visit?.title ?? row.title, summary: visit?.summary ?? row.summary, imageUrl: row.source_image_url ?? null,
      date: calendar?.date ?? date, dayLabel: calendar?.dayLabel ?? dayLabel,
      details: [when, ...new Set(venues)].filter(Boolean).join(' · ') };
    return [{start, entry, id:row.id}];
  });
  candidates.sort((a,b) => Math.max(a.start,now) - Math.max(b.start,now) || a.entry.slug.localeCompare(b.entry.slug));
  const ids = new Set<string>(), slugs = new Set<string>();
  const unique = candidates.filter(({id,entry}) => {
    if (ids.has(id) || slugs.has(entry.slug)) return false;
    ids.add(id); slugs.add(entry.slug); return true;
  });
  return { label: monthDay.format(week.start) + ' – ' + monthDay.format(week.end - 1), items: unique.slice(0,2).map(c => c.entry) };
}
