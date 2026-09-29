import { getCurationPeriodPresentation } from "@/app/lib/applicationDeadlineDisplay";
import type { UserCategory } from "@/app/lib/userCategories";

export default function CurationPeriodText({
  category,
  deadlineKind,
  deadlineOn,
  eventStartOn,
  eventEndOn,
  todayKst,
  locale,
  detail = false,
}: {
  category: UserCategory | null;
  deadlineKind: string | null;
  deadlineOn: string | null;
  eventStartOn: string | null;
  eventEndOn: string | null;
  todayKst: string;
  locale: string;
  detail?: boolean;
}) {
  const period = getCurationPeriodPresentation({
    category,
    deadlineKind,
    deadlineOn,
    eventStartOn,
    eventEndOn,
    todayKst,
    locale,
  });
  if (!period) return null;

  const statusColor = period.tone === "accent" ? "text-info-status" : "text-info-muted";
  if (!detail) {
    return (
      <span className={`font-semibold tabular-nums ${statusColor}`}>
        {category === "event" && period.detailDate ? (
          <>
            <span className="event-period-label">{period.detailLabel}</span>{" "}
            <span className="event-period-date">
              <time dateTime={period.detailDate.startOn} className="whitespace-nowrap">
                {period.detailDate.startText}
              </time>
              {period.detailDate.endOn && period.detailDate.endText && (
                <>
                  <wbr />
                  <span className="whitespace-nowrap">
                    {locale === "ja" ? "～" : "–"}
                    <time dateTime={period.detailDate.endOn}>{period.detailDate.endText}</time>
                  </span>
                </>
              )}
            </span>
          </>
        ) : period.listLabel}
      </span>
    );
  }

  return (
    <div className="mt-7 border-t border-info-rule pt-5 md:mt-9 md:pt-6">
      <p className={`text-base font-bold leading-7 tabular-nums md:text-lg ${statusColor} ${category === "event" ? "event-period-label" : ""}`}>
        {period.detailLabel}
      </p>
      {period.detailDate && (
        <p className="mt-1.5 break-words text-sm leading-6 text-info-body md:text-base md:leading-7">
          {period.detailDate.label && (
            <span className="mr-2 text-info-muted">{period.detailDate.label}</span>
          )}
          <time dateTime={period.detailDate.startOn} className={`font-semibold tabular-nums text-ink ${category === "event" ? "event-period-date" : ""}`}>
            {period.detailDate.startText}
          </time>
          {period.detailDate.endOn && period.detailDate.endText && (
            <>
              <span aria-hidden="true" className={category === "event" ? "event-period-date" : undefined}>{locale === "ja" ? "～" : "–"}</span>
              <time dateTime={period.detailDate.endOn} className={`font-semibold tabular-nums text-ink ${category === "event" ? "event-period-date" : ""}`}>
                {period.detailDate.endText}
              </time>
            </>
          )}
        </p>
      )}
    </div>
  );
}
