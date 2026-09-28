import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  formatApplicationDeadline,
  formatCurationPeriod,
  getApplicationDeadlinePresentation,
  getCurationPeriodPresentation,
  todayKst,
} from "../app/lib/applicationDeadlineDisplay.ts";
import { isUserCategory, USER_CATEGORIES } from "../app/lib/userCategories.ts";

const today = "2026-09-24";

function label(kind, on, locale, day = today) {
  return formatApplicationDeadline({ kind, on, todayKst: day, locale });
}

assert.equal(label("closed", null, "ko"), "접수 종료");
assert.equal(label("closed", null, "ja"), "受付終了");
assert.equal(label("none", null, "ko"), "상시 모집");
assert.equal(label("none", null, "ja"), "随時募集");
assert.equal(label("fixed", "2026-09-23", "ko"), "접수 종료");
assert.equal(label("fixed", "2026-09-23", "ja"), "受付終了");
assert.equal(label("fixed", "2026-09-24", "ko"), "오늘 접수 마감");
assert.equal(label("fixed", "2026-09-24", "ja"), "本日申込締切");
assert.equal(label("fixed", "2026-09-25", "ko"), "접수 마감 D-1");
assert.equal(label("fixed", "2026-09-25", "ja"), "申込締切まであと1日");
assert.equal(label("fixed", "2026-10-24", "ko"), "접수 마감 D-30");
assert.equal(label("fixed", "2026-10-25", "ko"), "접수 마감 2026.10.25");
assert.equal(label("fixed", "2026-10-25", "ja"), "申込締切 2026年10月25日");
assert.equal(
  label("fixed", "2026-01-05", "ja", "2025-12-01"),
  "申込締切 2026年1月5日",
);
assert.equal(label(null, null, "ko"), null);
assert.equal(label(null, "2026-09-24", "ja"), null);
assert.equal(label("fixed", null, "ko"), null);
assert.equal(label("fixed", "2026-02-30", "ko"), null);
assert.equal(label("none", "2026-09-24", "ko"), null);

const imminent = getApplicationDeadlinePresentation({
  kind: "fixed", on: "2026-09-26", todayKst: today, locale: "ko",
});
assert.deepEqual(imminent, {
  listLabel: "접수 마감 D-2",
  detailLabel: "접수 마감까지 D-2",
  tone: "accent",
  detailDate: { label: "접수 마감일", startOn: "2026-09-26", startText: "2026.09.26" },
});
assert.equal(getApplicationDeadlinePresentation({
  kind: "fixed", on: "2026-10-25", todayKst: today, locale: "ko",
})?.detailDate?.startText, "2026.10.25");

const beforeMidnight = todayKst(new Date("2026-09-23T14:59:59.000Z"));
const atMidnight = todayKst(new Date("2026-09-23T15:00:00.000Z"));
assert.equal(beforeMidnight, "2026-09-23");
assert.equal(atMidnight, "2026-09-24");
assert.equal(label("fixed", "2026-09-24", "ko", beforeMidnight), "접수 마감 D-1");
assert.equal(label("fixed", "2026-09-24", "ko", atMidnight), "오늘 접수 마감");

const root = dirname(fileURLToPath(import.meta.url));
const pages = [
  "app/[locale]/page.tsx",
  "app/[locale]/info/page.tsx",
  "app/[locale]/info/category/[category]/page.tsx",
  "app/[locale]/info/[id]/page.tsx",
];
for (const name of pages) {
  const source = readFileSync(join(root, "..", name), "utf8");
  assert.match(source, /export const dynamic = "force-dynamic"/, name);
  assert.match(source, /todayKst\(/, name);
}
const home = readFileSync(join(root, "../app/[locale]/page.tsx"), "utf8");
const detail = readFileSync(
  join(root, "../app/[locale]/info/[id]/page.tsx"),
  "utf8",
);
const entry = readFileSync(
  join(root, "../app/components/HomeCurationEntry.tsx"),
  "utf8",
);
const card = readFileSync(
  join(root, "../app/components/CurationCard.tsx"),
  "utf8",
);
assert.match(home, /todayKst=\{today\}/);
assert.match(entry, /CurationCard/);
assert.match(detail, /CurationPeriodText/);
assert.match(card, /CurationPeriodText/);

const explorer = readFileSync(
  join(root, "../app/components/CurationExplorer.tsx"),
  "utf8",
);
assert.match(explorer, /todayKst: string/);
assert.match(explorer, /todayKst=\{todayKst\}/);

const packageJson = readFileSync(join(root, "../package.json"), "utf8");
assert.doesNotMatch(packageJson, /date-fns|dayjs|luxon/);

function period(category, deadlineKind, deadlineOn, eventStartOn, eventEndOn, locale = "ko") {
  return formatCurationPeriod({
    category,
    deadlineKind,
    deadlineOn,
    eventStartOn,
    eventEndOn,
    todayKst: today,
    locale,
  });
}
assert.equal(period("policy", "fixed", "2026-09-25", null, null), "접수 마감 D-1");
assert.equal(period("program", "none", null, null, null, "ja"), "随時募集");
assert.equal(period("event", null, null, "2026-10-03", "2026-10-04"), "행사 일정 2026.10.03–2026.10.04");
assert.equal(period("event", null, null, "2026-10-03", "2026-10-04", "ja"), "開催期間 2026年10月3日～2026年10月4日");
assert.equal(period("event", null, null, "2026-10-03", "2026-10-03"), "행사 일정 2026.10.03");
assert.equal(getCurationPeriodPresentation({
  category: "event", deadlineKind: null, deadlineOn: null,
  eventStartOn: "2026-10-03", eventEndOn: "2026-10-04",
  todayKst: today, locale: "ko",
})?.detailDate?.endOn, "2026-10-04");
assert.equal(period("event", null, null, "2026-10-04", "2026-10-03"), null);
assert.equal(period("youth_space", "fixed", "2026-09-25", null, null), null);
assert.equal(period("living", "closed", null, null, null), null);
assert.equal(period(null, "fixed", "2026-09-25", null, null), null);
assert.deepEqual(USER_CATEGORIES, ["policy", "program", "event", "youth_space", "living"]);
assert.equal(isUserCategory("event"), true);
assert.equal(isUserCategory("other"), false);
assert.equal(isUserCategory(null), false);

const curationsSource = readFileSync(join(root, "../app/lib/curations.ts"), "utf8");
assert.match(curationsSource, /isUserCategory\(row\.user_category\)/);
assert.doesNotMatch(curationsSource, /!isUserCategory\(row\.user_category\)/);
assert.doesNotMatch(curationsSource, /classifyCurationCategory/);
const categoryPage = readFileSync(
  join(root, "../app/[locale]/info/category/[category]/page.tsx"),
  "utf8",
);
assert.match(categoryPage, /if \(!isUserCategory\(category\)\) notFound\(\)/);
const header = readFileSync(join(root, "../app/components/Header.tsx"), "utf8");
assert.match(header, /USER_CATEGORIES\.map/);
assert.match(header, /ITEMS\.slice\(1\)\.map/);
assert.doesNotMatch(header, /id: "info"/);
const bottomNav = readFileSync(join(root, "../app/components/BottomNav.tsx"), "utf8");
assert.doesNotMatch(bottomNav, /id: "info"/);
assert.doesNotMatch(explorer, /showAllAction|\["all"/);
assert.match(detail, /item\.userCategory \? `\/info\/category\/\$\{item\.userCategory\}` : "\/info"/);

console.log("ok");
