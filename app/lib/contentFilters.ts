// Shared public values only. Source excerpts, actors and edit history stay private.
export const contentFilterSchema = "content-filters-v1" as const;
export const programTopics = {
  language_learning: "언어·학습", culture_experience: "문화·취미·체험",
  employment_career: "취업·직무", daily_safety: "생활·안전",
  community_exchange: "교류·지역활동", other: "기타",
} as const;
export const eventTopics = { festival_exchange: "축제·교류", culture_arts: "문화·예술", lecture_commemoration: "강연·기념행사", other: "기타" } as const;
export const provinceLabels = { "11": "서울", "41": "경기", "28": "인천" } as const;
// Service selection vocabulary; do not infer a district from a capital-area flag.
export const districtChoices: Record<keyof typeof provinceLabels, readonly string[]> = {
  "11": ["종로구","중구","용산구","성동구","광진구","동대문구","중랑구","성북구","강북구","도봉구","노원구","은평구","서대문구","마포구","양천구","강서구","구로구","금천구","영등포구","동작구","관악구","서초구","강남구","송파구","강동구"],
  "41": ["수원시","성남시","의정부시","안양시","부천시","광명시","평택시","동두천시","안산시","고양시","과천시","구리시","남양주시","오산시","시흥시","군포시","의왕시","하남시","용인시","파주시","이천시","안성시","김포시","화성시","광주시","양주시","포천시","여주시","연천군","가평군","양평군"],
  "28": ["제물포구","영종구","미추홀구","연수구","남동구","부평구","계양구","서구","검단구","강화군","옹진군"],
};
export type FilterCategory = "program" | "event" | "youth_space";
export type FilterField<T> = { status: "known"; value: T } | { status: "unknown" | "not_applicable"; value: null };
export type FilterEndpoint = { value: string; precision: "day" | "minute" | "second" };
export type FilterLocation = { scope: "specific" | "nationwide"; venues: { province: keyof typeof provinceLabels; district: string | null; facility: string; address: string }[] };
export type FilterApplication = { deadlineKind: "fixed" | "none"; start: FilterEndpoint | null; end: FilterEndpoint | null; sourceStatus: "not_started" | "open" | "closed" | "unknown" };
export type FilterOccurrence = { start: FilterEndpoint; end: FilterEndpoint };
export type FilterRecurrence = { from: string; through: string; weekdays: number[]; startTime: string | null; endTime: string | null; precision: "day" | "minute" | "second"; exceptions: string[] };
export type FilterSchedule = { kind: "continuous" | "occurrences"; occurrences: FilterOccurrence[]; recurrence: FilterRecurrence | null };
export type ContentFilters = {
  schema: typeof contentFilterSchema; category: FilterCategory;
  topic: FilterField<string>; location: FilterField<FilterLocation>;
  delivery: FilterField<"online" | "onsite" | "mixed">;
  audience: FilterField<"children" | "other">;
  spaceKind: FilterField<"introduction" | "news">;
  application: FilterField<FilterApplication>; schedule: FilterField<FilterSchedule>;
};
export type FilterKey = Exclude<keyof ContentFilters, "schema" | "category">;
export const filterKeys: FilterKey[] = ["topic", "location", "delivery", "audience", "spaceKind", "application", "schedule"];
export const filterLabels: Record<FilterKey, string> = { topic: "대표 분야", location: "실제 개최·이용 지역", delivery: "진행 방식", audience: "어린이 프로그램 구분", spaceKind: "공간 소개·관련 소식", application: "신청 기간·마감", schedule: "실제 개최 일정" };

function object(v: unknown): Record<string, unknown> {
  if (!v || typeof v !== "object" || Array.isArray(v)) throw Error("invalid_content_filters");
  return v as Record<string, unknown>;
}
function exact(o: Record<string, unknown>, keys: string[]) {
  if (Object.keys(o).length !== keys.length || keys.some(k => !Object.hasOwn(o,k))) throw Error("invalid_content_filters");
}
function text(v: unknown, max = 500) {
  if (typeof v !== "string" || v.length > max || /[\u0000-\u0008\u000b\u000c\u000e-\u001f<>]/u.test(v)) throw Error("invalid_content_filters");
  return v;
}
function choice<T extends string>(v: unknown, options: readonly T[]): T {
  if (!options.includes(v as T)) throw Error("invalid_content_filters");
  return v as T;
}
export function filterDay(v: unknown) {
  const s = text(v,10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s) || s < "1900-01-01" || s > "2199-12-31" || new Date(s+"T00:00:00Z").toISOString().slice(0,10) !== s) throw Error("invalid_content_filters");
  return s;
}
export function filterEndpoint(v: unknown): FilterEndpoint {
  const o = object(v); exact(o,["value","precision"]);
  const precision = choice(o.precision,["day","minute","second"] as const), value = text(o.value,25);
  filterDay(value.slice(0,10));
  if (precision === "day" ? value.length !== 10 : !/^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d:[0-5]\d\+09:00$/.test(value) || (precision === "minute" && value.slice(17,19) !== "00")) throw Error("invalid_content_filters");
  return {value,precision};
}
function endpointRank(e: FilterEndpoint, end: boolean) {
  return e.precision === "day" ? e.value + (end ? "T23:59:59+09:00" : "T00:00:00+09:00") : e.value;
}
function occurrence(v: unknown): FilterOccurrence {
  const o = object(v); exact(o,["start","end"]);
  const start = filterEndpoint(o.start), end = filterEndpoint(o.end);
  if (endpointRank(start,false) > endpointRank(end,true)) throw Error("invalid_content_filters");
  return {start,end};
}
export function expandFilterRecurrence(v: unknown): { recurrence: FilterRecurrence; occurrences: FilterOccurrence[] } {
  const o = object(v); exact(o,["from","through","weekdays","startTime","endTime","precision","exceptions"]);
  const from = filterDay(o.from), through = filterDay(o.through), precision = choice(o.precision,["day","minute","second"] as const);
  const span = (Date.parse(through)-Date.parse(from))/86400000;
  if (span < 0 || span > 730 || !Array.isArray(o.weekdays) || o.weekdays.length < 1 || o.weekdays.length > 7 || new Set(o.weekdays).size !== o.weekdays.length || o.weekdays.some(d=>!Number.isInteger(d)||d<0||d>6) || !Array.isArray(o.exceptions) || o.exceptions.length > 200) throw Error("invalid_content_filters");
  const weekdays = [...o.weekdays] as number[], exceptions = o.exceptions.map(filterDay);
  if (new Set(exceptions).size !== exceptions.length || exceptions.some(d=>d<from||d>through||!weekdays.includes(new Date(d+"T00:00:00Z").getUTCDay()))) throw Error("invalid_content_filters");
  const startTime = o.startTime === null ? null : text(o.startTime,8), endTime = o.endTime === null ? null : text(o.endTime,8);
  const pattern = precision === "minute" ? /^([01]\d|2[0-3]):[0-5]\d$/ : /^([01]\d|2[0-3]):[0-5]\d:[0-5]\d$/;
  if (precision === "day" ? startTime !== null || endTime !== null : !startTime || !endTime || !pattern.test(startTime) || !pattern.test(endTime) || startTime > endTime) throw Error("invalid_content_filters");
  const occurrences: FilterOccurrence[] = [];
  for (let i=0;i<=span;i++) {
    const d = new Date(Date.parse(from)+i*86400000), day = d.toISOString().slice(0,10);
    if (!weekdays.includes(d.getUTCDay()) || exceptions.includes(day)) continue;
    const val=(t:string|null)=>precision === "day" ? day : `${day}T${t}${precision === "minute" ? ":00" : ""}+09:00`;
    occurrences.push({start:{value:val(startTime),precision},end:{value:val(endTime),precision}});
  }
  if (!occurrences.length || occurrences.length > 200) throw Error("invalid_content_filters");
  return {recurrence:{from,through,weekdays,startTime,endTime,precision,exceptions},occurrences};
}
export function parseContentFilters(v: unknown): ContentFilters {
  const o=object(v); exact(o,["schema","category",...filterKeys]);
  if (o.schema !== contentFilterSchema) throw Error("invalid_content_filters");
  const category=choice(o.category,["program","event","youth_space"] as const);
  const result: Record<string,unknown>={schema:contentFilterSchema,category};
  for (const key of filterKeys) {
    const f=object(o[key]); exact(f,["status","value"]);
    const status=choice(f.status,["known","unknown","not_applicable"] as const);
    if (status !== "known") { if (f.value !== null) throw Error("invalid_content_filters"); result[key]={status,value:null};continue; }
    let value: unknown;
    if (key === "topic") value=choice(f.value,Object.keys(category === "program" ? programTopics : eventTopics));
    else if (key === "delivery") value=choice(f.value,["online","onsite","mixed"] as const);
    else if (key === "audience") value=choice(f.value,["children","other"] as const);
    else if (key === "spaceKind") value=choice(f.value,["introduction","news"] as const);
    else if (key === "location") {
      const x=object(f.value);exact(x,["scope","venues"]);const scope=choice(x.scope,["specific","nationwide"] as const);
      if (!Array.isArray(x.venues) || x.venues.length > 20 || (scope === "specific" ? !x.venues.length : x.venues.length !== 0)) throw Error("invalid_content_filters");
      const venues=x.venues.map(raw=>{const p=object(raw);exact(p,["province","district","facility","address"]);const province=choice(p.province,Object.keys(provinceLabels) as (keyof typeof provinceLabels)[]);
        const district=p.district === null ? null : choice(p.district,districtChoices[province]);return {province,district,facility:text(p.facility,200),address:text(p.address,500)};});
      if (new Set(venues.map(p=>JSON.stringify(p))).size !== venues.length) throw Error("invalid_content_filters");
      value={scope,venues};
    } else if (key === "application") {
      const x=object(f.value);exact(x,["deadlineKind","start","end","sourceStatus"]);
      const deadlineKind=choice(x.deadlineKind,["fixed","none"] as const),start=x.start === null ? null : filterEndpoint(x.start),end=x.end === null ? null : filterEndpoint(x.end),sourceStatus=choice(x.sourceStatus,["not_started","open","closed","unknown"] as const);
      if ((deadlineKind === "fixed" ? !end : end !== null) || (start && end && endpointRank(start,false)>endpointRank(end,true))) throw Error("invalid_content_filters");
      value={deadlineKind,start,end,sourceStatus};
    } else {
      const x=object(f.value);exact(x,["kind","occurrences","recurrence"]);const kind=choice(x.kind,["continuous","occurrences"] as const);
      if (!Array.isArray(x.occurrences) || x.occurrences.length < 1 || x.occurrences.length > 200 || (kind === "continuous" && (x.occurrences.length !== 1 || x.recurrence !== null))) throw Error("invalid_content_filters");
      const occurrences=x.occurrences.map(occurrence);let recurrence:FilterRecurrence|null=null;
      if (x.recurrence !== null) {const expanded=expandFilterRecurrence(x.recurrence);recurrence=expanded.recurrence;if (JSON.stringify(expanded.occurrences)!==JSON.stringify(occurrences)) throw Error("invalid_content_filters");}
      for(let i=1;i<occurrences.length;i++) if(endpointRank(occurrences[i-1].end,true)>=endpointRank(occurrences[i].start,false)) throw Error("invalid_content_filters");
      value={kind,occurrences,recurrence};
    }
    result[key]={status,value};
  }
  const d=result as unknown as ContentFilters;
  const required:FilterKey[]=category === "program" ? ["topic","delivery","audience","application"] : category === "event" ? ["topic","schedule"] : ["spaceKind"];
  const irrelevant:FilterKey[]=category === "program" ? ["spaceKind","schedule"] : category === "event" ? ["delivery","audience","spaceKind","application"] : ["topic","delivery","audience","application","schedule"];
  if(required.some(k=>d[k].status === "not_applicable") || irrelevant.some(k=>d[k].status !== "not_applicable")) throw Error("invalid_content_filters");
  const locationRequired=category === "event" || (category === "program" && !(d.delivery.status === "known" && d.delivery.value === "online")) || (category === "youth_space" && d.spaceKind.status === "known" && d.spaceKind.value === "introduction");
  if(locationRequired && d.location.status === "not_applicable") throw Error("invalid_content_filters");
  if(category === "program" && d.delivery.status === "known" && d.delivery.value === "online" && d.location.status !== "not_applicable") throw Error("invalid_content_filters");
  if(category === "youth_space" && d.spaceKind.status === "known" && d.spaceKind.value === "news" && d.location.status !== "not_applicable") throw Error("invalid_content_filters");
  return d;
}
export function emptyContentFilters(category: FilterCategory): ContentFilters {
  const unknown={status:"unknown",value:null} as const,na={status:"not_applicable",value:null} as const;
  return {schema:contentFilterSchema,category,topic:category === "youth_space"?na:unknown,location:unknown,delivery:category === "program"?unknown:na,audience:category === "program"?unknown:na,spaceKind:category === "youth_space"?unknown:na,application:category === "program"?unknown:na,schedule:category === "event"?unknown:na};
}
// Stored legacy snapshots remain readable; completion and writes use this guard.
export function programApplicationComplete(d:ContentFilters):boolean {
  return d.category !== 'program' || (d.application.status === 'known'
    && d.application.value.deadlineKind === 'fixed'
    && d.application.value.start !== null && d.application.value.end !== null);
}
export function missingContentFilters(d:ContentFilters):FilterKey[] {
  const keys=filterKeys.filter(k=>d[k].status === "unknown");
  if(d.location.status === "known" && d.location.value.venues.some(v=>!v.district)) keys.push("location");
  if(!programApplicationComplete(d)) keys.push("application");
  return [...new Set(keys)];
}
