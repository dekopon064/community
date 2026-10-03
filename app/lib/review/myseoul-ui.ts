import { ReviewFailure } from './contracts';
import { myseoulCommand } from './myseoul-contract';
import type { MySeoulFacts, MySeoulField, MySeoulPeriod } from './myseoul-contract';

export const myseoulLabels: Record<MySeoulField, string> = {
  description: '프로그램 설명', target: '참여 대상', conditions: '명시된 참여 조건',
  application_actor: '개인·기관 신청 여부', delivery_mode: '실제 진행 방식', activity_region: '실제 개최 지역',
  venue: '개최 장소', activity_evidence: '개최지·진행 방식의 근거', residence_scope: '온라인 참여 대상 지역',
  residence: '거주 조건', residence_evidence: '거주 조건의 근거', public_category: '공개 카테고리',
  purpose: '활동 성격과 분류 근거', qualification_note: '명시 자격 확인 근거', periods: '신청·운영 기간',
  session_evidence: '회차·요일·시간·집결 안내', application_methods: '신청 방법', application_links: '신청 링크',
  fees: '비용 구성', source_status: '원문의 모집 상태',
};
export const myseoulChoices: Record<string, Record<string, string>> = {
  application_actor: { unknown: '확인 필요', individual: '개인 신청 가능', institution_only: '개인 신청 불가 · 기관 전용' },
  delivery_mode: { offline: '오프라인', online: '온라인', mixed: '온·오프라인 혼합' },
  activity_region: { capital: '서울·경기·인천' },
  residence_scope: { unknown: '확인 필요', nationwide: '전국·지역 제한 없음', includes_capital: '수도권 포함', capital: '수도권 거주자', noncapital_only: '비수도권 거주자 전용' },
  public_category: { unknown: '확인 필요', program: '프로그램', event: '행사' },
};
export const myseoulFeeLabels: Record<string, string> = { tuition: '수강료', admission: '입장료', materials: '재료비', extra_fee: '기타 비용' };
export const myseoulArrayFields = new Set(['conditions', 'activity_evidence', 'residence_evidence', 'session_evidence', 'application_methods', 'application_links', 'source_status']);
export type MySeoulPeriods = { application: MySeoulPeriod[]; operation: MySeoulPeriod[] };
export type MySeoulFee = { component: string; evidence: string[] };
export function myseoulPatch(saved: MySeoulFacts, draft: MySeoulFacts, editable: string[]) {
  const lines = (values: string[]) => values.map(v => v.trim()).filter(Boolean);
  return Object.fromEntries(editable.filter(k => JSON.stringify(saved[k]) !== JSON.stringify(draft[k])).map(k => {
    let value = draft[k];
    if (myseoulArrayFields.has(k)) value = lines(value as string[]);
    if (k === 'fees') value = (value as MySeoulFee[]).map((f, index) => JSON.stringify(f) === JSON.stringify((saved.fees as MySeoulFee[])[index]) ? f : { ...f, evidence: lines(f.evidence) });
    return [k, value];
  }).filter(([k, v]) => JSON.stringify(saved[k as string]) !== JSON.stringify(v)));
}
export function reviewPeriodAxes(reasons: string[]): ('application' | 'operation')[] {
  return (['application', 'operation'] as const).filter(axis => reasons.some(r => r === `${axis}_period_unknown` || r.endsWith(`:${axis}`) || r === 'source_change_conflict:periods' || r === 'application_state_unknown' || r === 'source_fact_conflict:status'));
}
export function visibleMySeoulFields(editable: string[], facts: MySeoulFacts): MySeoulField[] {
  return (Object.keys(myseoulLabels) as MySeoulField[]).filter(k => editable.includes(k) && k !== 'activity_evidence' && !(facts.delivery_mode === 'online' && ['activity_region', 'venue'].includes(k)));
}
type SaveItem = { revision: string; version: string; facts: MySeoulFacts; editableFields: string[]; result: { reasons: string[] } };
export function buildMySeoulSave(item: SaveItem, draft: MySeoulFacts, fields?: string[], axes?: ('application' | 'operation')[]) {
  const allowed = visibleMySeoulFields(item.editableFields, draft);
  if (fields?.some(k => !allowed.includes(k as MySeoulField))) throw new ReviewFailure('invalid_input');
  const patch = fields ? Object.fromEntries(fields.map(k => [k, draft[k]])) : myseoulPatch(item.facts, draft, allowed);
  if (patch.periods) {
    const periods = patch.periods as MySeoulPeriods;
    const selected = axes ?? reviewPeriodAxes(item.result.reasons).filter(axis => fields || JSON.stringify(periods[axis]) !== JSON.stringify((item.facts.periods as MySeoulPeriods)[axis]));
    if (selected.some(axis => !reviewPeriodAxes(item.result.reasons).includes(axis))) throw new ReviewFailure('invalid_input');
    patch.periods = Object.fromEntries(selected.map(axis => [axis, periods[axis]]));
    if (!selected.length) delete patch.periods;
  }
  if (!Object.keys(patch).length) throw new ReviewFailure('invalid_input', { form: '확인할 사실을 선택해 주세요.' });
  return myseoulCommand({ action: 'save_facts', revision: item.revision, version: item.version, patch });
}
// A scoped save must not discard another issue's unsubmitted edits.
export function mergeMySeoulDraft(saved: MySeoulFacts, draft: MySeoulFacts, next: MySeoulFacts, patch: Partial<Record<MySeoulField, unknown>>) {
  const merged = structuredClone(next);
  for (const key of Object.keys(myseoulLabels) as MySeoulField[]) {
    if (key === 'periods') {
      const submitted = (patch.periods ?? {}) as Partial<MySeoulPeriods>;
      for (const axis of ['application', 'operation'] as const) {
        if (!Object.hasOwn(submitted, axis) && JSON.stringify((saved.periods as MySeoulPeriods)[axis]) !== JSON.stringify((draft.periods as MySeoulPeriods)[axis])) {
          (merged.periods as MySeoulPeriods)[axis] = structuredClone((draft.periods as MySeoulPeriods)[axis]);
        }
      }
    } else if (!Object.hasOwn(patch, key) && JSON.stringify(saved[key]) !== JSON.stringify(draft[key])) merged[key] = structuredClone(draft[key]);
  }
  return merged;
}
export function displayMySeoulValue(key: string, value: unknown): string {
  if (key === 'periods') {
    const periods = value as MySeoulPeriods;
    return (['application', 'operation'] as const).map(axis => `${axis === 'application' ? '신청 기간' : '운영 기간'}: ${periods[axis].map(p => `${p.label}: ${p.endpoints.map(e => e.value.replace('T', ' ').replace(':00+09:00', '') + (e.precision === 'day' ? ' (날짜 기준)' : '')).join(' ~ ') || '일정 확인 필요'} · 원문: ${p.raw}`).join('\n') || '미확인'}`).join('\n');
  }
  if (key === 'fees') return (value as MySeoulFee[]).map(f => `${myseoulFeeLabels[f.component]}: ${f.evidence.join(' / ')}`).join('\n') || '미확인';
  if (Array.isArray(value)) return value.join('\n') || '미표기';
  return myseoulChoices[key]?.[String(value)] ?? (typeof value === 'string' && value ? value : '미확인');
}
