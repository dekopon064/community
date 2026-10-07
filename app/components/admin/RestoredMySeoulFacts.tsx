import type { MySeoulFacts } from "../../lib/review/myseoul-contract";
import { myseoulChoices, myseoulLabels } from "../../lib/review/myseoul-ui";
import type { MySeoulPeriods } from "../../lib/review/myseoul-ui";

// A bounded current-facts summary for restore confirmation. Source text and
// observed extraction remain separate; this never constructs a save payload.
export function RestoredMySeoulFacts({ facts }: { facts: MySeoulFacts }) {
  const periods = facts.periods as MySeoulPeriods;
  return <dl className="mt-3 grid gap-3 sm:grid-cols-2" aria-label="복원 후 확인할 현재 사실">
    {(["public_category", "target", "delivery_mode", "venue", "residence"] as const).map(key => <div key={key}>
      <dt className="font-semibold">{myseoulLabels[key]}</dt>
      <dd className="whitespace-pre-wrap break-words text-info-body">{myseoulChoices[key]?.[String(facts[key])] || String(facts[key] || "미표기")}</dd>
    </div>)}
    {(["application", "operation"] as const).map(axis => <div key={axis}>
      <dt className="font-semibold">{axis === "application" ? "신청 기간" : "운영 일정"}</dt>
      <dd className="whitespace-pre-wrap break-words text-info-body">{periods[axis].map(period => period.endpoints.length ? period.endpoints.map(e => e.value.slice(0, e.precision === "day" ? 10 : 16).replace("T", " ")).join(" ~ ") + (period.endpoints[1]?.precision === "day" ? " · 종료일 당일 포함" : "") : period.raw || "확인 필요").join("\n") || "미표기"}</dd>
    </div>)}
  </dl>;
}
