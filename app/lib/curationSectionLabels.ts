export const CURATION_SECTION_LABELS = {
  ko: ["한 줄 요약", "대상", "일정 안내", "주요 내용", "신청 방법"],
  ja: ["要約", "対象", "日程案内", "主な内容", "申請方法"],
} as const;

export type BodyLocale = keyof typeof CURATION_SECTION_LABELS;

const scheduleAliases = {
  ko: ["일정 안내", "기간·상태"],
  ja: ["日程案内", "期間・状況"],
} as const;

export function curationHeadingAliases(heading: string): readonly string[] {
  for (const aliases of Object.values(scheduleAliases)) {
    if (aliases.some((alias) => alias === heading)) return aliases;
  }
  return [heading];
}
