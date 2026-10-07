import type { CandidateContent, CandidateNotice } from "./contracts";

type RecordValue = Record<string, unknown>;
const record = (v: unknown): RecordValue | null => v !== null && typeof v === "object" && !Array.isArray(v) ? v as RecordValue : null;
const text = (v: unknown): string => typeof v === "string" ? v : "";
const texts = (v: unknown): string[] => Array.isArray(v) ? v.filter((s): s is string => typeof s === "string").slice(0, 200) : [];
// Only short relevant excerpts leave the server. HTML/phone/email are not notices.
function excerpt(v: string, limit = 280): string {
  return v.replace(/<[^>]*>/g, "").replace(/\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b/g, "[연락처 생략]")
    .replace(/(?:\+82[- ]?)?0\d{1,2}[- )]?\d{3,4}[- ]?\d{4}/g, "[연락처 생략]")
    .replace(/https?:\/\/\S+/g, "[링크]").slice(0, limit);
}
function normalized(v: string): string {
  let previousEnd = -1, meridiem = "";
  const original = v.normalize("NFKC").replace(/^([ \t]*(?:[-*·•] )?)\d+\.\s+(?=[^\d\s])/gm, "$1");
  return original.replace(/(오전|오후|午前|午後)?\s*(\d{1,2})(?::([0-5]\d)|[시時](?!간|間|작)(?:\s*([0-5]?\d)[분分])?)/g,
    (match, mark: string | undefined, hour: string, colon: string, written: string, offset: number) => {
      const inherited = !mark && Number(hour) <= 12 && /^[ ~〜～–—-]*(?:부터|から)?\s*$/.test(original.slice(previousEnd, offset)) ? meridiem : "";
      mark = mark || inherited;
      previousEnd = offset + match.length; meridiem = mark || "";
      const h = Number(hour);
      if (h > 23 || (mark && (h < 1 || h > 12))) return match;
      return `${String(mark ? h % 12 + (/오후|午後/.test(mark) ? 12 : 0) : h).padStart(2, "0")}:${String(Number(colon || written || 0)).padStart(2, "0")}`;
    });
}
function tokens(v: string): Set<string> {
  const n = normalized(v), out = new Set<string>();
  for (const m of n.matchAll(/(\d{4})-(\d{2})-(\d{2})|(\d{1,2})[월月]\s*(\d{1,2})[일日]/g)) {
    out.add(`date:${Number(m[2] || m[4])}-${Number(m[3] || m[5])}`);
    if (m[1]) out.add(`year:${m[1]}`);
  }
  for (const m of n.matchAll(/(\d{4})[년年]/g)) out.add(`year:${m[1]}`);
  for (const m of n.matchAll(/(\d{1,2})[월月]\s*((?:\d{1,2}\s*[일日]?\s*[,·、・]\s*)+\d{1,2}\s*[일日])/g)) {
    for (const d of m[2].matchAll(/\d+/g)) out.add(`date:${Number(m[1])}-${Number(d[0])}`);
  }
  for (const m of n.matchAll(/([월화수목금토일])요일|([月火水木金土日])曜日|[（(]([월화수목금토일月火水木金土日])[）)]/g)) {
    const day = m[1] || m[2] || m[3]; out.add(`weekday:${Math.max("월화수목금토일".indexOf(day), "月火水木金土日".indexOf(day))}`);
  }
  for (const m of n.matchAll(/(\d{2}:[0-5]\d)/g)) out.add(`clock:${m[1]}`);
  for (const m of n.matchAll(/(\d{2}:[0-5]\d)\s*[~〜～–—-]\s*(\d{2}:[0-5]\d)/g)) out.add(`pair:${m[1]}~${m[2]}`);
  for (const m of n.matchAll(/(\d+)\s*[회回]/g)) out.add(`count:${m[1]}`);
  if (/매주|毎週/.test(n)) out.add("weekly");
  return out;
}
const covers = (wanted: Set<string>, actual: Set<string>) => [...wanted].every(v => actual.has(v));
const quantityTokens = (v: string) => new Set([...v.matchAll(/(?<![.\d])\d+(?:\.\d+)?(?:[~〜～-]\d+(?:\.\d+)?)?(?:원|세|명|회)(?:이상|이하|미만|초과)?/g)].map(m => m[0]));
function rows(v: string): string[] {
  return v.normalize("NFKC").split(/[\n;；]/).flatMap(line => {
    const parts = line.split(/(?<!\d)\/|\/(?!\d)|\s+\/\s+|(?<=:\d{2})\/(?=\d+[A-Z])/).map(s => s.trim()).filter(Boolean), result: string[] = [];
    for (let i = 0; i < parts.length; i++) {
      let row = parts[i]; const a = tokens(row), next = parts[i + 1];
      if (next && [...a].some(t => /^(date:|weekday:|weekly)/.test(t)) && ![...a].some(t => t.startsWith("clock:")) &&
          /^(?:(?:오전|오후|午前|午後)\s*)?\d{1,2}(?::|[시時])/.test(next) && [...tokens(next)].some(t => t.startsWith("pair:")) &&
          ![...tokens(next)].some(t => /^(date:|weekday:)/.test(t))) row += " / " + parts[++i];
      result.push(row);
    }
    return result;
  });
}
function section(content: string, header: string): string {
  const at = content.indexOf(header);
  if (at < 0) return "";
  return content.slice(at + header.length).split(/\n\s*\[[^\]\n]+\]/)[0].trim();
}
const unknown = (item: string): CandidateNotice => ({ kind: "unverified", language: "both", section: "전체", item, expected: "생성 당시 입력", result: "대조 자료를 읽지 못해 판단할 수 없습니다. 후보 내용은 그대로 표시합니다." });
// Display-only excerpts from the SAVED candidate; never new generation evidence.
function candidatePassage(content: CandidateContent, language: CandidateNotice["language"], label: string): string {
  const passage = (lang: "ko" | "ja") => {
    const body = lang === "ko" ? content.contentKo : content.contentJa;
    const headers = lang === "ko" ? ["대상", "기간·상태", "주요 내용", "신청 방법"] : ["対象", "期間・状況", "主な内容", "申請方法"];
    const labels = ["대상", "기간·상태", "주요 내용", "신청 방법"];
    const pieces = headers.flatMap((header, i) => label.includes(labels[i]) ? [section(body, `[${header}]`)] : []).filter(Boolean);
    return excerpt(pieces.length ? pieces.join("\n") : label === "전체" ? body : "해당 섹션 표지를 찾지 못했습니다. 아래 후보 본문에서 확인해 주세요.", 900);
  };
  return language === "both" ? `한국어: ${passage("ko")}\n일본어: ${passage("ja")}` : passage(language);
}
export function unavailableMySeoulNotices(): CandidateNotice[] { return [unknown("내용 대조")]; }

/** Read-time advisory, not a generation audit record or a new publication gate.
 * Bounded spellings/aliases only. Missing matches are NOT proof of a semantic
 * omission. Unsupported paraphrases/labels are explicitly unverified.
 */
export function mySeoulCandidateNotices(raw: unknown, id: string, inputFactsVersion: number, content: CandidateContent): CandidateNotice[] {
  const o = record(raw), f = record(o?.facts);
  if (!o || !f || o.candidateId !== id || o.source !== "myseoul_program" || o.schema !== "myseoul-program-facts-v1-local" ||
      o.profile !== "myseoul-program-v1-local" || o.factsVersion !== inputFactsVersion || !/^[a-f0-9]{64}$/.test(text(o.revision))) return unavailableMySeoulNotices();
  const notices: CandidateNotice[] = [];
  const add = (language: CandidateNotice["language"], section: string, item: string, expected: string, result: string, kind: CandidateNotice["kind"] = "unverified") => {
    if (notices.length < 48) notices.push({ language, section, item, expected: excerpt(expected), result: excerpt(result), kind,
      actual: candidatePassage(content, language, section) });
  };
  const requirements: [string, string][] = [["참여 대상", text(f.target)], ["거주 조건", text(f.residence)], ["자격 조건", text(f.qualification_note)], ["개최 장소", text(f.venue)],
    ...["conditions", "age", "companion", "language"].flatMap(k => texts(f[k]).map(v => [({ conditions: "참여 조건", age: "연령", companion: "동반 조건", language: "진행 언어" } as Record<string, string>)[k], v] as [string, string])),
    ...((Array.isArray(f.fees) ? f.fees : []).flatMap(v => texts(record(v)?.evidence).map(e => ["비용", e] as [string, string])))];
  const periodGroups = record(f.periods);
  const operation = Array.isArray(periodGroups?.operation) && periodGroups.operation.length === 1 ? record(periodGroups.operation[0]) : null;
  const endpoints = Array.isArray(operation?.endpoints) ? operation.endpoints.map(record) : [];
  // Only a single explicitly dated minute timetable; never infer course links.
  const confirmed = operation?.status === "ok" && endpoints.length === 2 && endpoints.every(e => e?.precision === "minute") &&
    text(endpoints[0]?.value).slice(0, 10) === text(endpoints[1]?.value).slice(0, 10)
    ? { day: tokens(text(endpoints[0]?.value)), pair: `${text(endpoints[0]?.value).slice(11, 16)}~${text(endpoints[1]?.value).slice(11, 16)}` } : null;
  for (const language of ["ko", "ja"] as const) {
    const body = language === "ko" ? content.contentKo : content.contentJa;
    const period = section(body, language === "ko" ? "[기간·상태]" : "[期間・状況]");
    const participant = section(body, language === "ko" ? "[대상]" : "[対象]") + "\n" + section(body, language === "ko" ? "[주요 내용]" : "[主な内容]");
    const unit = (s: string) => s.replace(/ウォン|KRW/g, "원").replace(/[歳才]/g, "세").replace(/[名人]/g, "명").replace(/回/g, "회").replace(/以上/g, "이상").replace(/以下/g, "이하").replace(/未満/g, "미만").replace(/超/g, "초과").replace(/[,\s]/g, "");
    for (const [item, expected] of requirements) {
      if (!expected.trim()) continue;
      const quantities = [...quantityTokens(unit(normalized(expected)))];
      const actual = unit(normalized(/연령|대상|조건/.test(item) ? participant : body));
      const missing = quantities.filter(v => !quantityTokens(actual).has(v));
      if (missing.length) add(language, item === "비용" ? "전체" : "대상·주요 내용", item, expected, `명시된 숫자·단위 ${missing.join(", ")}를 관련 섹션에서 찾지 못했습니다. 다른 표현인지는 판단하지 못했습니다.`, "possible_missing");
      else if (!quantities.length && (language === "ja" || !body.replace(/\s/g, "").includes(expected.replace(/\s/g, "")))) {
        // A substring mismatch cannot be labelled as a confirmed semantic error.
        add(language, item === "개최 장소" ? "기간·상태·주요 내용" : item === "비용" ? "주요 내용" : "대상·주요 내용", item, expected, "같은 뜻으로 표현됐는지 아래 후보 문장과 비교해 주세요.");
      }
    }
    for (const key of ["application", "operation"]) {
      const periods = Array.isArray(periodGroups?.[key]) ? periodGroups[key] as unknown[] : [];
      for (const p of periods) {
        const value = record(p), endpoints = Array.isArray(value?.endpoints) ? value.endpoints as unknown[] : [];
        const expected = endpoints.map(v => { const e = record(v); return text(e?.value).slice(0, e?.precision === "day" ? 10 : 16).replace("T", " "); }).filter(Boolean).join(" ~ ");
        if (!expected || value?.status !== "ok") { add(language, "기간·상태", key === "application" ? "신청기간" : "운영기간", text(value?.raw), "구조화 일정의 범위를 판단하지 못했습니다."); continue; }
        if (!rows(period).some(row => covers(tokens(expected), tokens(row)))) {
          const clocks = [...tokens(period)].filter(v => v.startsWith("clock:")).map(v => v.slice(6));
          const wanted = tokens(expected), parsed = tokens(period);
          const knownDate = [...wanted].filter(t => t.startsWith("date:")).some(t => parsed.has(t));
          const differentClock = knownDate && [...wanted].filter(t => t.startsWith("clock:")).some(t => !parsed.has(t)) && clocks.length > 0;
          add(language, "기간·상태", key === "application" ? "신청기간" : "운영기간", expected, clocks.length ? `연결된 날짜·시각을 찾지 못했습니다. 이 섹션의 시각: ${clocks.join(", ")}` : "연결된 날짜·시각을 찾지 못했습니다. 표현 해석에는 한계가 있습니다.", differentClock ? "difference" : "unverified");
        }
      }
    }
    for (const [item, evidence] of [["회차·반별 일정", texts(f.session_evidence)], ["집결 안내", texts(f.meeting_evidence)]] as const) {
      for (const expected of evidence) {
        const wanted = tokens(expected), pairs = [...wanted].filter(v => v.startsWith("pair:"));
        const dates = [...wanted].filter(v => v.startsWith("date:"));
        if (item === "회차·반별 일정" && confirmed && pairs.length === 1 && dates.length === 1 && confirmed.day.has(dates[0]) &&
            !/매주|매월|회차|\d+\s*회|반|과정|집결/.test(expected) &&
            (!/[:：]/.test(expected.replace(/\d{1,2}:\d{2}/g, "")) || /^(?:일시|교육일시|운영일시|행사일시)\s*[:：]/.test(expected))) {
          // Preserved source evidence is not a SECOND confirmed timetable.
          // Without observed provenance we do not claim that a human cancelled
          // a session; only report an explicitly different clock reappearing.
          if (pairs[0] !== `pair:${confirmed.pair}` && tokens(body).has(pairs[0])) {
            add(language, "전체", "현재 일정과 보존 안내의 시각", confirmed.pair, `확정 운영 일정과 다른 보존 안내의 시각 ${pairs[0].slice(5)}이 결과에도 있습니다.`, "difference");
          }
          continue;
        }
        const label = /^(.*?)(?<!\d)[:：]/.exec(expected)?.[1] || "";
        const aliases = [...label.matchAll(/\b(?:ITQ|DIAT|TOPIK(?:\s*II)?|[0-6][AB])\b/g)].map(m => m[0]);
        const known = label.includes("기초반") ? ["기초반", "コンピュータ基礎", "パソコン基礎", "基礎クラス"] : label.includes("생활디지털") ? ["생활디지털", "生活デジタル", "デジタル活用"] : label.includes("발음반") ? ["발음반", "発音"] : [];
        const unsupportedLabel = language === "ja" && label.includes("반") && !aliases.length && !known.length;
        if (!wanted.size || pairs.length > 1 || unsupportedLabel) { add(language, "기간·상태", item, expected, "이 표현 또는 반 이름의 연결을 자동으로 판단하지 못했습니다."); continue; }
        const found = rows(period).some(row => covers(wanted, tokens(row)) && aliases.every(a => row.includes(a)) && (!known.length || known.some(a => row.includes(a))) &&
          (item !== "집결 안내" || /집결|集合/.test(row)) && (pairs.length === 0 || [...tokens(row)].filter(v => v.startsWith("pair:")).length === 1));
        if (!found) add(language, "기간·상태", item, expected, "같은 일정 묶음의 날짜·요일·시간·횟수 또는 집결 역할을 확인하지 못했습니다. 누락인지 다른 표현인지는 판단하지 못했습니다.");
      }
    }
    const methods = section(body, language === "ko" ? "[신청 방법]" : "[申請方法]");
    for (const link of texts(f.application_links)) if (!methods.includes(link)) add(language, "신청 방법", "신청 링크", "생성 입력의 신청 링크", "관련 섹션에서 같은 링크를 찾지 못했습니다.", "possible_missing");
    for (const method of texts(f.application_methods)) if (language === "ja" || !methods.includes(method)) add(language, "신청 방법", "신청 방법", method, "신청 방법의 문장 의미가 같은지는 자동으로 판단하지 못했습니다.");
    if (language === "ja" && /[가-힣]|[円￥¥]/.test(body)) add(language, "전체", "일본어 표기", "일본어·원화 안내", "한글 또는 엔화 표기가 있습니다.", "difference");
  }
  // Cross-language typed quantities are compared within corresponding sections,
  // never satisfied by a date/fee digit in an unrelated section.
  const units = (s: string) => normalized(s).replace(/[名人]/g, "명").replace(/[歳才]/g, "세").replace(/ウォン/g, "원").replace(/回/g, "회").replace(/[,\s]/g, "");
  for (const [ko, ja, label] of [["[대상]", "[対象]", "대상"], ["[주요 내용]", "[主な内容]", "주요 내용"]]) {
    const a = units(section(content.contentKo, ko)), b = units(section(content.contentJa, ja));
    const missing = [...quantityTokens(a)].filter(v => !quantityTokens(b).has(v));
    if (missing.length) add("both", label, "한일 숫자·단위 대조", missing.join(", "), "한국어와 같은 숫자·단위를 일본어의 대응 섹션에서 찾지 못했습니다.", "possible_missing");
  }
  if (notices.length === 48) notices.push({ kind: "unverified", language: "both", section: "전체", item: "대조 범위", expected: "생성 당시 입력", result: "안내가 많아 일부 상세 대조를 표시하지 못했습니다. 자동 검사 결과는 정확성을 보장하지 않습니다." });
  return notices;
}
