import type { Period, ProgramFacts } from "./program-contract";
import { periodLabels, programDateInput } from "./program-ui";

export type PeriodMap = Record<string, Period>;
const dayOf = (p: Period) => p?.value ? programDateInput(p).slice(0,10) : "";
export function dateOrderValid(periods: PeriodMap) {
  return ["RCPT","SVCOPN"].every(role => {
    const a = periods[role+"BGNDT"], b = periods[role+"ENDDT"];
    if (a?.status !== "ok" || b?.status !== "ok" || !a.value || !b.value) return false;
    return a.precision === "day" || b.precision === "day" ? dayOf(a) <= dayOf(b) : Date.parse(a.value) <= Date.parse(b.value);
  });
}

function koreanDate(year:string, month:string, day:string) {
  const iso = [year,month.padStart(2,"0"),day.padStart(2,"0")].join("-");
  const date = new Date(iso+"T00:00:00Z");
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0,10) === iso ? iso : null;
}

export function compareProgramPeriods(facts:ProgramFacts, sourceBody:string, reasons:string[]) {
  const periods = facts.periods as PeriodMap;
  const evidence = (facts.period_evidence as string[]).filter(value => value !== "및 요일" && value.trim());
  const lines = sourceBody.split(/\r?\n/);
  const quotes = lines.filter(line => evidence.some(value=>line.includes(value)) ||
    (reasons.some(r=>r==="date_weekday_conflict" || r==="invalid_body_date") && /20\d\d\s*[.년/-].*\([월화수목금토일]/.test(line)));
  const roles = new Set<string>();
  for (const line of quotes) {
    const prefix = lines[lines.indexOf(line)-1] ?? "";
    const labeled = /^(?:\s*[-*·]?\s*)(?:접수|신청|모집|운영|진행)\s*기간\s*[:：]?\s*$/.test(prefix) ? prefix + " " + line : line;
    if (/(접수|신청|모집)\s*기간/.test(labeled)) roles.add("RCPT");
    if (/(운영|진행)\s*기간/.test(labeled)) roles.add("SVCOPN");
  }
  let keys = Object.keys(periodLabels).filter(k => !roles.size || roles.has(k.startsWith("RCPT")?"RCPT":"SVCOPN"));
  // Suggest the first/last session day only for a fully recognized operation
  // schedule. A session clock conveys no registration or operating cutoff.
  const value = evidence.length === 1 && quotes.length === 1 && roles.size === 1 && roles.has("SVCOPN") ? evidence[0] : "";
  // Accept a weekly range or an explicitly exhaustive list of selectable sessions.
  const range = /^(\d{4})년\s*(\d+)월\s*(\d+)일\(([월화수목금토일])\)\s*[~～]\s*(\d+)월\s*(\d+)일\(([월화수목금토일])\),\s*매주\s*([월화수목금토일])요일(?:\s*(?:클래스당\s*)?총\s*\d+회)?$/.exec(value);
  const choices = /^(\d{4})년\s*(\d+)월\s*(\d+)일\s*\d{1,2}:\d\d\s*[-~]\s*\d{1,2}:\d\d\s*\/\s*(\d{4})년\s*(\d+)월\s*(\d+)일\s*\d{1,2}:\d\d\s*[-~]\s*\d{1,2}:\d\d\s*\(해당 일자 중 택 1\)$/.exec(value);
  const days = range ? [koreanDate(range[1],range[2],range[3]),koreanDate(range[1],range[5],range[6])] :
    choices ? [koreanDate(choices[1],choices[2],choices[3]),koreanDate(choices[4],choices[5],choices[6])] : [];
  const suggested:PeriodMap={};
  const weekday = (day:string) => "일월화수목금토"[new Date(day+"T00:00:00Z").getUTCDay()];
  const validWeekdays = !range || (days[0] && days[1] && weekday(days[0])===range[4] &&
    weekday(days[1])===range[7] && range[7]===range[8] && range[4]===range[8]);
  if (validWeekdays && reasons.length===1 && reasons[0]==="body_period_needs_confirmation" && days[0] && days[1] && days[0]<=days[1]) {
    for (const [i,key] of ["SVCOPNBGNDT","SVCOPNENDDT"].entries()) {
      const day = days[i]!;
      if (dayOf(periods[key]) !== day) suggested[key]={raw:day,value:day,status:"ok",precision:"day"};
    }
    if (Object.keys(suggested).length) keys=Object.keys(suggested);
  } else if (reasons.some(r=>r==="period_missing_or_unparsed" || r==="period_order_conflict")) {
    keys=Object.keys(periodLabels);
  }
  return {quotes,keys,suggested};
}
