import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { parseCurationBodySections } from "../app/lib/curationBodySections.ts";

// These shapes match the published Korean inline-label and Japanese
// separate-label formats; the text is only a local display fixture.
const korean = `[한 줄 요약] 집수리 실습 프로그램
[대상] 서울시 생활권 청년 1인 가구
[기간·상태] 접수기간: 2026년 10월 1일까지
[주요 내용] 전동 드라이버와 콘센트 교체 실습
[신청 방법] 구글폼([신청 링크](https://forms.gle/example))으로 신청.`;
const ko = parseCurationBodySections(korean, "ko");
assert.deepEqual(ko?.sections.map((section) => section.heading), [
  "한 줄 요약", "대상", "기간·상태", "주요 내용", "신청 방법",
]);
assert.equal(ko?.sections[2].body, "접수기간: 2026년 10월 1일까지");
assert.equal(
  ko?.sections[4].body,
  "구글폼([신청 링크](https://forms.gle/example))으로 신청.",
);

const linkHtml = renderToStaticMarkup(createElement(ReactMarkdown, {
  remarkPlugins: [[remarkGfm, { singleTilde: false }]],
}, ko.sections[4].body));
assert.match(linkHtml, /href="https:\/\/forms\.gle\/example"/);
assert.match(linkHtml, /으로 신청\./);

const japanese = `[要約]
住まい修理の実習です。
[対象]
ソウル市生活圏の青年一人暮らし世帯
[主な内容]
電動ドライバーを使います。

- 実習があります。
[申請方法]
[申請リンク](https://forms.gle/example)から申請します。`;
const ja = parseCurationBodySections(japanese, "ja");
assert.deepEqual(ja?.sections.map((section) => section.heading), [
  "要約", "対象", "主な内容", "申請方法",
]);
assert.match(ja.sections[2].body, /- 実習があります。/);
assert.match(ja.sections[3].body, /\[申請リンク\]\(https:\/\/forms\.gle\/example\)/);

const oldForm = `[한 줄 요약]\n기존 요약\n\n[주요 내용]\n본문`;
assert.deepEqual(
  parseCurationBodySections(oldForm, "ko")?.sections.map((section) => section.heading),
  ["한 줄 요약", "주요 내용"],
);

for (const unstructured of [
  "일반 문단과 [대상] 문구가 이어지는 글",
  "[대상]만 있는 단락",
  "[대상](https://example.com) 링크와 [주요 내용] 문구",
  "[한 줄 요약] 요약\n[한 줄 요약] 중복\n[주요 내용] 본문",
  "[한 줄 요약] 요약\n[주요 내용] 본문\n```text\n[대상] 코드\n```",
  "[한 줄 요약] 요약\n[주요 내용]   ",
]) {
  assert.equal(parseCurationBodySections(unstructured, "ko"), null);
}

assert.equal(parseCurationBodySections(korean, "ja"), null);
assert.equal(parseCurationBodySections(japanese, "ko"), null);
assert.equal(parseCurationBodySections("[한 줄 요약] 요약\r\n[주요 내용] 내용", "ko")?.sections.length, 2);

const unknownHeading = parseCurationBodySections(
  "[한 줄 요약] 요약\n[주요 내용] 본문\n[기타] 원문 유지",
  "ko",
);
assert.match(unknownHeading?.sections[1].body ?? "", /\[기타\] 원문 유지/);

console.log("curation body sections: ok");
