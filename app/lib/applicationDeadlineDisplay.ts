import type { UserCategory } from "@/app/lib/userCategories";

export type ApplicationDeadlineKind = "fixed" | "none" | "closed";

export interface PeriodPresentation {
  listLabel: string;
  detailLabel: string;
  tone: "accent" | "quiet";
  detailDate?: {
    label?: string;
    startOn: string;
    startText: string;
    endOn?: string;
    endText?: string;
  };
}

const DAY_MS = 86_400_000;

export function todayKst(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
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

function localDate(isoDate: string, locale: string): string {
  const [year, month, day] = isoDate.split("-");
  return locale === "ja"
    ? `${year}年${Number(month)}月${Number(day)}日`
    : `${year}.${month}.${day}`;
}

export function getApplicationDeadlinePresentation(input: {
  kind: string | null | undefined;
  on: string | null | undefined;
  todayKst: string;
  locale: string;
}): PeriodPresentation | null {
  const { kind, on, locale } = input;
  const isJa = locale === "ja";
  if ((kind === "none" || kind === "closed") && on != null) return null;
  if (kind === "closed") {
    const label = isJa ? "受付終了" : "접수 종료";
    return { listLabel: label, detailLabel: label, tone: "accent" };
  }
  if (kind === "none") {
    const label = isJa ? "随時募集" : "상시 모집";
    return { listLabel: label, detailLabel: label, tone: "quiet" };
  }
  if (kind !== "fixed" || !on) return null;

  const today = utcDay(input.todayKst);
  const deadline = utcDay(on);
  if (today === null || deadline === null) return null;

  const days = Math.round((deadline - today) / DAY_MS);
  const detailDate = {
    label: isJa ? "申込締切日" : "접수 마감일",
    startOn: on,
    startText: localDate(on, locale),
  };
  if (days < 0) {
    const label = isJa ? "受付終了" : "접수 종료";
    return { listLabel: label, detailLabel: label, tone: "accent", detailDate };
  }
  if (days === 0) {
    const label = isJa ? "本日申込締切" : "오늘 접수 마감";
    return { listLabel: label, detailLabel: label, tone: "accent", detailDate };
  }
  if (days <= 30) {
    return {
      listLabel: isJa ? `申込締切まであと${days}日` : `접수 마감 D-${days}`,
      detailLabel: isJa ? `申込締切まであと${days}日` : `접수 마감까지 D-${days}`,
      tone: days <= 7 ? "accent" : "quiet",
      detailDate,
    };
  }
  return {
    listLabel: isJa ? `申込締切 ${localDate(on, locale)}` : `접수 마감 ${localDate(on, locale)}`,
    detailLabel: isJa ? "申込締切" : "접수 마감",
    tone: "quiet",
    detailDate,
  };
}

export function formatApplicationDeadline(input: Parameters<typeof getApplicationDeadlinePresentation>[0]): string | null {
  return getApplicationDeadlinePresentation(input)?.listLabel ?? null;
}

export function getCurationPeriodPresentation(input: {
  category: UserCategory | null;
  deadlineKind: string | null;
  deadlineOn: string | null;
  eventStartOn: string | null;
  eventEndOn: string | null;
  todayKst: string;
  locale: string;
}): PeriodPresentation | null {
  if (input.category === "policy" || input.category === "program") {
    return getApplicationDeadlinePresentation({
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

  const startOn = input.eventStartOn as string;
  const endOn = input.eventEndOn as string;
  const startText = localDate(startOn, input.locale);
  const endText = localDate(endOn, input.locale);
  const range = startOn === endOn
    ? startText
    : `${startText}${input.locale === "ja" ? "～" : "–"}${endText}`;
  return {
    listLabel: `${input.locale === "ja" ? "開催期間" : "행사 일정"} ${range}`,
    detailLabel: input.locale === "ja" ? "開催期間" : "행사 일정",
    tone: "accent",
    detailDate: {
      startOn,
      startText,
      ...(startOn === endOn ? {} : { endOn, endText }),
    },
  };
}

export function formatCurationPeriod(input: Parameters<typeof getCurationPeriodPresentation>[0]): string | null {
  return getCurationPeriodPresentation(input)?.listLabel ?? null;
}
