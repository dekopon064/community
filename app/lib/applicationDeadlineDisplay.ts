import type { UserCategory } from "@/app/lib/userCategories";

export type ApplicationDeadlineKind = "fixed" | "none" | "closed";

const DAY_MS = 86_400_000;

export function todayKst(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

export function formatApplicationDeadline(input: {
  kind: string | null | undefined;
  on: string | null | undefined;
  todayKst: string;
  locale: string;
}): string | null {
  const kind = input.kind ?? null;
  if (kind === "closed") return closedLabel(input.locale);
  if (kind === "none") return noneLabel(input.locale);
  if (kind !== "fixed") return null;

  const today = utcDay(input.todayKst);
  const deadline = utcDay(input.on);
  if (today === null || deadline === null) return null;

  const days = Math.round((deadline - today) / DAY_MS);
  if (days < 0) return closedLabel(input.locale);
  if (days === 0) return "D-Day";
  if (days <= 30) return `D-${days}`;
  return farLabel(input.locale, input.on as string);
}

function closedLabel(locale: string): string {
  return locale === "ja" ? "受付終了" : "접수 종료";
}

function noneLabel(locale: string): string {
  return locale === "ja" ? "随時募集" : "상시 모집";
}

function farLabel(locale: string, isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) return locale === "ja" ? "受付終了" : "접수 종료";
  const [, year, month, day] = match;
  if (locale === "ja") {
    return `申込締切 ${year}年${Number(month)}月${Number(day)}日`;
  }
  return `마감 ${year}.${month}.${day}`;
}

function utcDay(value: string | null | undefined): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? "");
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() !== month - 1 ||
    parsed.getUTCDate() !== day
  ) {
    return null;
  }
  return parsed.getTime();
}

export function formatCurationPeriod(input: {
  category: UserCategory | null;
  deadlineKind: string | null;
  deadlineOn: string | null;
  eventStartOn: string | null;
  eventEndOn: string | null;
  todayKst: string;
  locale: string;
}): string | null {
  if (input.category === "policy" || input.category === "program") {
    return formatApplicationDeadline({
      kind: input.deadlineKind,
      on: input.deadlineOn,
      todayKst: input.todayKst,
      locale: input.locale,
    });
  }
  if (input.category !== "event") return null;

  const start = utcDay(input.eventStartOn);
  const end = utcDay(input.eventEndOn);
  if (start === null || end === null || start > end) return null;

  const [startYear, startMonth, startDay] = (input.eventStartOn as string).split("-");
  const [endYear, endMonth, endDay] = (input.eventEndOn as string).split("-");
  if (input.locale === "ja") {
    const from = `${startYear}年${Number(startMonth)}月${Number(startDay)}日`;
    const to = `${endYear}年${Number(endMonth)}月${Number(endDay)}日`;
    return `開催 ${from}${from === to ? "" : `～${to}`}`;
  }
  const from = `${startYear}.${startMonth}.${startDay}`;
  const to = `${endYear}.${endMonth}.${endDay}`;
  return `행사 ${from}${from === to ? "" : `–${to}`}`;
}
