import { filterKeys, provinceLabels } from '../contentFilters';
import type { ContentFilters, FilterKey } from '../contentFilters';
import type { MySeoulFacts } from './myseoul-contract';
import type { FilterInfo } from './content-filter-store';

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

// Explicit public input may confirm editable legacy facts. A venue
// selection is not a source quote, and an unknown location proves no scope.
export function factsFromFilterSelection(facts: MySeoulFacts, before: ContentFilters, next: ContentFilters, editable: string[]): MySeoulFacts {
  const result = structuredClone(facts);
  if ((!same(before.delivery, next.delivery) || facts.delivery_mode === 'unknown') && editable.includes('delivery_mode')) {
    if (next.delivery.status === 'known') result.delivery_mode = next.delivery.value === 'onsite' ? 'offline' : next.delivery.value;
    else if (next.delivery.status === 'unknown') result.delivery_mode = 'unknown';
  }
  if ((!same(before.location, next.location) || facts.activity_region === 'unknown') && editable.includes('activity_region') && result.delivery_mode !== 'online'
    && next.location.status === 'known' && next.location.value.scope === 'specific'
    && next.location.value.venues.length > 0 && next.location.value.venues.every(v => Object.hasOwn(provinceLabels, v.province))) {
    result.activity_region = 'capital';
  }
  return result;
}

// Facts saves can also refresh derived filters. Preserve operator edits to
// other fields while adopting the returned version and unchanged fields.
export function mergeMySeoulFilters(saved: ContentFilters, draft: ContentFilters, next: ContentFilters): ContentFilters {
  if (saved.category !== next.category || draft.category !== next.category) return structuredClone(draft);
  const result = structuredClone(next);
  for (const key of filterKeys) if (!same(saved[key], draft[key])) Object.assign(result, { [key]: structuredClone(draft[key]) });
  return result;
}

export function myseoulFilterFields(info: FilterInfo, editable: string[]): FilterKey[] {
  const order: FilterKey[] = ['topic', 'delivery', 'audience', 'location', 'application', 'schedule', 'spaceKind'];
  return order.filter(k => info.missing.includes(k)
    || (k === 'delivery' && info.data.category === 'program' && editable.includes('delivery_mode'))
    || (k === 'location' && (editable.includes('activity_region') || editable.includes('venue')))
    || (k === 'application' && info.data.category === 'program' && info.missing.length > 0
      && info.data.application.status === 'known' && info.data.application.value.start === null));
}

export function assertMySeoulFilterContinuation(previous: { revision: string; category: string }, next: { revision: string; status: string; filterInfo?: FilterInfo }) {
  if (next.revision !== previous.revision || next.status !== 'open' || !next.filterInfo
    || next.filterInfo.revision !== previous.revision || next.filterInfo.data.category !== previous.category) {
    throw Error('사실 저장 후 원문·카테고리 또는 처리 상태가 변경됐습니다. 공개 필터는 저장하지 않았으며 입력을 보존합니다.');
  }
}
