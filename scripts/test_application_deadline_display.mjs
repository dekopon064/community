import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  formatApplicationDeadline,
  todayKst,
} from "../app/lib/applicationDeadlineDisplay.ts";

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
assert.equal(label("fixed", "2026-09-24", "ko"), "D-Day");
assert.equal(label("fixed", "2026-09-24", "ja"), "D-Day");
assert.equal(label("fixed", "2026-09-25", "ko"), "D-1");
assert.equal(label("fixed", "2026-09-25", "ja"), "D-1");
assert.equal(label("fixed", "2026-10-24", "ko"), "D-30");
assert.equal(label("fixed", "2026-10-25", "ko"), "마감 2026.10.25");
assert.equal(label("fixed", "2026-10-25", "ja"), "申込締切 2026年10月25日");
assert.equal(
  label("fixed", "2026-01-05", "ja", "2025-12-01"),
  "申込締切 2026年1月5日",
);
assert.equal(label(null, null, "ko"), null);
assert.equal(label(null, "2026-09-24", "ja"), null);
assert.equal(label("fixed", null, "ko"), null);

const beforeMidnight = todayKst(new Date("2026-09-23T14:59:59.000Z"));
const atMidnight = todayKst(new Date("2026-09-23T15:00:00.000Z"));
assert.equal(beforeMidnight, "2026-09-23");
assert.equal(atMidnight, "2026-09-24");
assert.equal(label("fixed", "2026-09-24", "ko", beforeMidnight), "D-1");
assert.equal(label("fixed", "2026-09-24", "ko", atMidnight), "D-Day");

const root = dirname(fileURLToPath(import.meta.url));
const pages = [
  "app/[locale]/page.tsx",
  "app/[locale]/info/page.tsx",
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
assert.match(entry, /ApplicationDeadlineText/);
assert.match(detail, /ApplicationDeadlineText/);
assert.match(card, /ApplicationDeadlineText/);
assert.match(card, /formatApplicationDeadline|ApplicationDeadlineText/);

const explorer = readFileSync(
  join(root, "../app/components/CurationExplorer.tsx"),
  "utf8",
);
assert.match(explorer, /todayKst: string/);
assert.match(explorer, /todayKst=\{todayKst\}/);

const packageJson = readFileSync(join(root, "../package.json"), "utf8");
assert.doesNotMatch(packageJson, /date-fns|dayjs|luxon/);

console.log("ok");
