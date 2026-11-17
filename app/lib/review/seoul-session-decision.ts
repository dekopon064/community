import type { Period, ProgramFacts } from './program-contract';

const weekdays = '일월화수목금토';
function weekday(year: number, month: number, day: number) {
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day)
    return weekdays[date.getUTCDay()];
}

// An abbreviated end date inherits its year only within this explicit range.
export function rangeConflict(description: string) {
  const pattern = /(?:운영\s*(?:일시|기간))\s*[:：]\s*(20\d\d)\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*\(([월화수목금토일])\)\s*[-~～]\s*((?:(20\d\d)\.\s*)?(\d{1,2})\.\s*(\d{1,2})\.?\s*(\(([월화수목금토일])\)))/;
  const matches = description.split(/\r?\n/).map(line => ({ line, m: pattern.exec(line) })).filter(row => row.m);
  if (matches.length !== 1) return null;
  const { line, m } = matches[0];
  if (!m || weekday(+m[1], +m[2], +m[3]) !== m[4]) return null;
  const year = Number(m[6] ?? m[1]), actual = m[10], expected = weekday(year, +m[7], +m[8]);
  if (!expected || actual === expected) return null;
  const end = line.indexOf(m[0]) + m[0].length;
  const iso = (y: number, m: number, d: number) => [String(y), String(m).padStart(2,'0'), String(d).padStart(2,'0')].join('-');
  return { line, start: iso(+m[1],+m[2],+m[3]), end: iso(year,+m[7],+m[8]), date: year+'년 '+Number(m[7])+'월 '+Number(m[8])+'일', actual, expected,
    corrected: line.slice(0, end - m[9].length) + line.slice(end) };
}

export function sessionDecision(facts: ProgramFacts) {
  const text = String(facts.description), conflict = rangeConflict(text);
  if (!conflict || !Array.isArray(facts.conditions)) return null;
  const periods = facts.periods as Record<string, Period>;
  const iso = periods.SVCOPNBGNDT?.value?.slice(0, 10);
  if (!iso || iso < conflict.start || iso > conflict.end || iso !== periods.SVCOPNENDDT?.value?.slice(0, 10)) return null;
  const [year, month, day] = iso.split('-').map(Number);
  const dates = text.split(/\r?\n/).filter(line => /(?:답사|회차|행사|해설)\s*일시/.test(line));
  if (dates.length !== 1) return null;
  const m = /^\s*[-•]?\s*(?:답사|회차|행사|해설)\s*일시(?:는|[:：])\s*(?:(20\d\d)\.\s*)?(\d{1,2})\.\s*(\d{1,2})\.?\s*\(([월화수목금토일])\)\s*((?:[01]?\d|2[0-3])\s*[~～]\s*(?:[01]?\d|2[0-3])시)(?:입니다)?[.。\s]*$/.exec(dates[0]);
  if (!m || (m[1] && +m[1] !== year) || +m[2] !== month || +m[3] !== day || weekday(year, month, day) !== m[4]) return null;
  // Only the duplicate of the exact source line is edited. Other operator
  // conditions or evidence that conflicts must remain available for review.
  if (facts.conditions.some(value => value.trim() !== conflict.line.trim() && rangeConflict(value))) return null;
  const conditions = facts.conditions.map(value => value.trim() === conflict.line.trim() ? conflict.corrected.trim() : value);
  return { conflict, session: dates[0].trim(), patch: {
    description: text.replace(conflict.line, () => conflict.corrected), conditions,
  } };
}

// Display only the ordered lines of a recorded flat matrix. Missing positions
// cannot be reconstructed by counting the surviving cells.
export function recordedWeekTable(description: string) {
  const lines = description.split(/\r?\n/).map(v => v.trim()).filter(Boolean);
  const starts = lines.flatMap((v, i) => /^시간\s*[/·]\s*요일$/.test(v) ? [i] : []);
  if (starts.length !== 1) return null;
  let i = starts[0] + 1;
  const headers = [];
  while (i < lines.length && /^(?:[월화수목금토일](?:요일)?|평일|주말)$/.test(lines[i])) headers.push(lines[i++]);
  if (headers.length < 2) return null;
  const rows = [];
  while (i < lines.length && /^\d{1,2}:[0-5]\d$/.test(lines[i])) {
    const time = lines[i++], cells: string[] = [];
    while (i < lines.length) {
      if (/^(?:제\s*)?\d+\s*회차(?:\s*[（(][^()（）]+[）)])?$/.test(lines[i])) cells.push(lines[i++]);
      else if (cells.length && /^[（(][^()（）]+[）)]$/.test(lines[i])) cells[cells.length - 1] += lines[i++];
      else break;
    }
    rows.push({time, cells});
  }
  return rows.length ? {headers, rows, grouped: headers.join('/') === '평일/주말' && rows.every(r => r.cells.length === 2)} : null;
}
