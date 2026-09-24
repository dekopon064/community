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
