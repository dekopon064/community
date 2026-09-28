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
        {period.listLabel}
      </span>
    );
  }

  return (
    <div className="mt-7 border-t border-info-rule pt-5 md:mt-9 md:pt-6">
      <p className={`text-base font-bold leading-7 tabular-nums md:text-lg ${statusColor}`}>
        {period.detailLabel}
      </p>
      {period.detailDate && (
        <p className="mt-1.5 break-words text-sm leading-6 text-info-body md:text-base md:leading-7">
          {period.detailDate.label && (
            <span className="mr-2 text-info-muted">{period.detailDate.label}</span>
          )}
          <time dateTime={period.detailDate.startOn} className="font-semibold tabular-nums text-ink">
            {period.detailDate.startText}
          </time>
          {period.detailDate.endOn && period.detailDate.endText && (
            <>
              <span aria-hidden="true">{locale === "ja" ? "～" : "–"}</span>
              <time dateTime={period.detailDate.endOn} className="font-semibold tabular-nums text-ink">
                {period.detailDate.endText}
              </time>
            </>
          )}
        </p>
      )}
    </div>
  );
}
