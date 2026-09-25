import { formatCurationPeriod } from "@/app/lib/applicationDeadlineDisplay";
import type { UserCategory } from "@/app/lib/userCategories";

export default function CurationPeriodText({
  category,
  deadlineKind,
  deadlineOn,
  eventStartOn,
  eventEndOn,
  todayKst,
  locale,
}: {
  category: UserCategory | null;
  deadlineKind: string | null;
  deadlineOn: string | null;
  eventStartOn: string | null;
  eventEndOn: string | null;
  todayKst: string;
  locale: string;
}) {
  const label = formatCurationPeriod({
    category,
    deadlineKind,
    deadlineOn,
    eventStartOn,
    eventEndOn,
    todayKst,
    locale,
  });
  if (!label) return null;
  return <p className="mt-1 text-xs font-semibold tabular-nums text-ink">{label}</p>;
}
