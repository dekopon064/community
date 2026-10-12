import { districtChoices } from './contentFilters';
import japaneseReadings from './districtJapaneseReadings';

// Display-only name-stem keys, not translations or persisted geography values.
// 66 keys derive from approved docs/ingest-inputs/region_ja_glossary.v1.yaml:
// remove 区/市/郡 and normalize the approved katakana stem to hiragana.
// Incheon 서구 retains the existing key/西区 label. Its ソグ reading is verified at:
// https://japanese.visitkorea.or.kr/svc/contents/contentsView.do?vcontsId=69889
// The stem ソ supplies its key; no alias from 서해구 is inferred.
const readings: Readonly<Record<string, Readonly<Record<string, string>>>> = japaneseReadings;
const korean = new Intl.Collator('ko-KR', { usage: 'sort', sensitivity: 'variant' });
const japanese = new Intl.Collator('ja-JP', { usage: 'sort', sensitivity: 'variant' });

export function sortDistrictNames(
  names: readonly string[], locale: string,
  readingKeys: Readonly<Record<string, string>> = {},
): string[] {
  return [...names].sort((a, b) => {
    if (locale === 'ja') {
      const left = readingKeys[a], right = readingKeys[b];
      // Future unregistered readings remain visible, after verified readings.
      if (Boolean(left) !== Boolean(right)) return left ? -1 : 1;
      if (left && right) {
        const compared = japanese.compare(left, right);
        if (compared) return compared;
      }
    }
    // Same/missing readings use the unchanged Korean identifier as a tie-break.
    return korean.compare(a, b) || (a < b ? -1 : a > b ? 1 : 0);
  });
}

export function sortedDistrictChoices(province: string, locale = 'ko'): string[] {
  const names = districtChoices[province as keyof typeof districtChoices] ?? [];
  return sortDistrictNames(names, locale, readings[province]);
}
