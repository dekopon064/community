import { todayKst } from './applicationDeadlineDisplay';
import { endpointBoundary, eventTiming, programTiming, publicCurationItem } from './publicContentFilters';
import { parseContentFilters } from './contentFilters';
import type { LocalizedCuration } from './types';

// Approved local scope: no editorial pins, inferred topics, or unknown/closed
// fallback. The caller supplies only localized, complete, publicly visible rows.
export const homeLimits = Object.freeze({ featured: 6, deadline: 1, experiences: 2, learning: 2, events: 1 });
const learningTopics = new Set(['language_learning', 'employment_career', 'daily_safety']);
const DAY = 86_400_000;
export type HomeSelection = {
  featured: LocalizedCuration[];
  sections: { deadline: LocalizedCuration[]; experiences: LocalizedCuration[]; learning: LocalizedCuration[]; events: LocalizedCuration[] };
};

export function homeWeek(now: number) {
  if (!Number.isFinite(now)) throw Error('invalid_home_time');
  const today = todayKst(new Date(now));
  const midnight = Date.parse(today + 'T00:00:00+09:00');
  const weekday = new Date(today + 'T00:00:00Z').getUTCDay();
  const start = midnight - ((weekday + 6) % 7) * DAY;
  return { start, end: start + 7 * DAY }; // Monday inclusive, next Monday exclusive in KST.
}

function latest(a: LocalizedCuration, b: LocalizedCuration) {
  const ta = Date.parse(a.created_at), tb = Date.parse(b.created_at);
  return (Number.isFinite(tb) ? tb : 0) - (Number.isFinite(ta) ? ta : 0)
    || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
    || (a.slug < b.slug ? -1 : a.slug > b.slug ? 1 : 0);
}
function topic(item: LocalizedCuration) {
  try {
    const data = parseContentFilters(item.contentFilters);
    return data.category === item.userCategory && data.topic.status === 'known' ? data.topic.value : null;
  } catch { return null; }
}

export function selectHomeContent(rows: readonly LocalizedCuration[], now: number): HomeSelection {
  const week = homeWeek(now), ids = new Set<string>(), slugs = new Set<string>();
  const unique = [...rows].sort(latest).filter(item => {
    if (ids.has(item.id) || slugs.has(item.slug)) return false;
    ids.add(item.id); slugs.add(item.slug); return true;
  });
  const programs = unique.filter(item => item.userCategory === 'program').map(item => ({ item, timing: programTiming(publicCurationItem(item), now) }))
    .filter(entry => entry.timing.state === 'open');
  const events = unique.filter(item => item.userCategory === 'event').map(item => ({ item, timing: eventTiming(publicCurationItem(item), now) }))
    .filter(entry => entry.timing.state === 'ongoing' || entry.timing.state === 'upcoming');
  const deadline = programs.filter(({ timing }) => timing.deadlineKind === 'fixed' && timing.deadline
    && endpointBoundary(timing.deadline) >= week.start && endpointBoundary(timing.deadline) < week.end)
    .sort((a, b) => endpointBoundary(a.timing.deadline!, true) - endpointBoundary(b.timing.deadline!, true) || latest(a.item, b.item));
  // Each section has its own role; intentional cross-section repetition is allowed.
  // Within every result the public ID/slug is unique. Titles never assign a topic.
  return {
    featured: [...programs.map(x => x.item), ...events.map(x => x.item)].sort(latest).slice(0, homeLimits.featured),
    sections: {
      deadline: deadline.slice(0, homeLimits.deadline).map(x => x.item),
      experiences: programs.filter(x => topic(x.item) === 'culture_experience').slice(0, homeLimits.experiences).map(x => x.item),
      learning: programs.filter(x => learningTopics.has(topic(x.item) ?? '')).slice(0, homeLimits.learning).map(x => x.item),
      events: events.sort((a, b) => a.timing.group - b.timing.group || a.timing.order - b.timing.order || latest(a.item, b.item))
        .slice(0, homeLimits.events).map(x => x.item),
    },
  };
}
