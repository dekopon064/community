import { formatApplicationDeadline } from "@/app/lib/applicationDeadlineDisplay";

export default function ApplicationDeadlineText({
  kind,
  on,
  todayKst,
  locale,
}: {
  kind: string | null | undefined;
  on: string | null | undefined;
  todayKst: string;
  locale: string;
}) {
  const label = formatApplicationDeadline({ kind, on, todayKst, locale });
  if (!label) return null;

  return (
    <p className="mt-1 text-xs font-semibold tracking-[-0.01em] text-ink">{label}</p>
  );
}
