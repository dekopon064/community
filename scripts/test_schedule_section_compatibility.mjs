// Pure synthetic body/candidate projection; no DB, provider or credentials.
import assert from "node:assert/strict";
import { registerHooks } from "node:module";
registerHooks({ resolve(s, c, next) {
  try { return next(s, c); }
  catch (error) { if (s.startsWith(".") && !/\.[a-z]+$/i.test(s)) return next(`${s}.ts`, c); throw error; }
} });
const { mySeoulCandidateNotices } = await import("../app/lib/review/myseoul-candidate-notices.ts");
const id = "00000000-0000-4000-8000-000000000001";
const raw = { candidateId: id, source: "myseoul_program", schema: "myseoul-program-facts-v1-local",
  profile: "myseoul-program-v1-local", factsVersion: 1, revision: "a".repeat(64), facts: {
    periods: { application: [{ status: "ok", raw: "합성 신청 기간", endpoints: [
      {value:"2099-10-01T10:00:00+09:00",precision:"minute"},
      {value:"2099-10-02T18:00:00+09:00",precision:"minute"},
    ] }] }, session_evidence: [], meeting_evidence: [],
  } };
const ko = "[한 줄 요약]\n합성\n[일정 안내]\n신청기간: 2099-10-01 10:00 ~ 2099-10-02 18:00\n[주요 내용]\n합성 설명";
const ja = "[要約]\n合成\n[日程案内]\n申請期間: 2099年10月1日10時00分～2099年10月2日18時00分\n[主な内容]\n合成本文";
let checks = 0;
for (const kh of ["일정 안내", "기간·상태"]) for (const jh of ["日程案内", "期間・状況"]) {
  const content = { contentKo: ko.replace("일정 안내", kh), contentJa: ja.replace("日程案内", jh) };
  const before = JSON.stringify(content);
  assert.deepEqual(mySeoulCandidateNotices(raw, id, 1, content), []); checks++;
  assert.equal(JSON.stringify(content), before); checks++;
  const bad = {...content,contentKo:content.contentKo.replace("18:00", "17:00")};
  const notices = mySeoulCandidateNotices(raw, id, 1, bad);
  assert.ok(notices.some(n => n.section === "일정 안내" && n.kind === "difference")); checks++;
  assert.ok(notices.every(n => !n.section.includes("기간·상태"))); checks++;
  assert.match(notices[0].actual, /17:00/); checks++;
  assert.deepEqual(mySeoulCandidateNotices(raw, id, 1, {
    contentKo:content.contentKo.replaceAll("\n","\r\n"),contentJa:content.contentJa,
  }), []); checks++;
}
for (const body of [ko.replace("[일정 안내]", "[대상]"), ko+"\n[기간·상태]\n중복 일정", "본문에서 [일정 안내] 언급\n[주요 내용]\n설명"]) {
  const notices = mySeoulCandidateNotices(raw,id,1,{contentKo:body,contentJa:ja});
  assert.ok(notices.some(n => n.section === "일정 안내" && n.kind === "unverified")); checks++;
}
console.log(JSON.stringify({checks,mode:"synthetic",scope:"legacy/new schedule candidate comparison"}));
