import assert from "node:assert/strict";
import { registerHooks } from "node:module";
registerHooks({ resolve(specifier, context, nextResolve) {
  try { return nextResolve(specifier, context); }
  catch (error) { if (specifier.startsWith(".") && !/\.[a-z]+$/i.test(specifier)) return nextResolve(`${specifier}.ts`, context); throw error; }
} });
const { LocalReviewStore, fixtureFacts } = await import("../app/lib/review/local-fixture.ts");
const { listReviews, reviewDetail } = await import("../app/lib/review/handlers.ts");
const { validateFacts, validateContent } = await import("../app/lib/review/validation.ts");
const { ReviewFailure } = await import("../app/lib/review/contracts.ts");
const { AdminAccessError } = await import("../app/lib/auth/admin-policy.ts");
const { localFixtureEnabled } = await import("../app/lib/review/config.ts");
const { sourceLink, reasonText } = await import("../app/lib/review/presentation.ts");
const { mayCacheResponse } = await import("../app/lib/serviceWorkerCachePolicy.ts");

const actor = "00000000-0000-4000-8000-000000000001";
const factsId = "10000000-0000-4000-8000-000000000001";
const eventId = "10000000-0000-4000-8000-000000000002";
const candidateId = "20000000-0000-4000-8000-000000000001";
const origin = "http://localhost:3100";
const admin = async () => ({ userId: actor });
const request = (kind, id, body, headers = {}) => new Request(`${origin}/api/admin/review/${kind}/${id}`, body === undefined ? {} : { method: "POST", headers: { Origin: origin, "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) });
function noStore(response) { assert.match(response.headers.get("Cache-Control"), /private.*no-store/); assert.equal(mayCacheResponse(response), false); }
const pre = (item) => ({ revision: item.revision, version: item.version });
async function mutate(store, kind, id, command) {
  const response = await reviewDetail(request(kind, id, command), kind, id, { authorize: admin, store: () => store }); noStore(response); return { response, data: await response.json() };
}
let storeReads = 0;
for (const [denial, status] of [["signed_out", 401], ["forbidden", 403], ["auth_unavailable", 503], ["configuration_error", 503]]) {
  const deps = { authorize: async () => { throw new AdminAccessError(denial); }, store: () => { storeReads++; throw new Error("DO_NOT_ECHO_SECRET"); } };
  for (const response of [await listReviews(new Request(`${origin}/api/admin/review?kind=facts`), deps), await reviewDetail(request("facts", factsId), "facts", factsId, deps), await reviewDetail(request("candidates", candidateId, { action: "publish" }), "candidates", candidateId, deps)]) {
    assert.equal(response.status, status); noStore(response); assert.equal((await response.json()).code, denial);
  }
}
assert.equal(storeReads, 0, "Every list/detail/mutation authorizes before store selection");
let store = new LocalReviewStore();
const deps = { authorize: admin, store: () => store };
let response = await listReviews(new Request(`${origin}/api/admin/review?kind=facts`), deps);
assert.equal(response.status, 200); noStore(response); assert.equal((await response.json()).items.length, 2);
response = await reviewDetail(request("facts", factsId), "facts", factsId, deps);
assert.equal(response.status, 200); let item = (await response.json()).item;
const originalSource = structuredClone(item.source);
response = await reviewDetail(request("facts", factsId, { ...pre(item), action: "save_facts", facts: fixtureFacts() }, { Origin: "https://attacker.invalid" }), "facts", factsId, deps);
assert.equal(response.status, 403); noStore(response);
let result = await mutate(store, "facts", factsId, { ...pre(item), action: "save_facts", facts: fixtureFacts(), actor: "FORGED_ADMIN" });
assert.equal(result.response.status, 422, "Browser actor override rejected");
result = await mutate(store, "facts", factsId, { ...pre(item), action: "save_facts", facts: { ...fixtureFacts(), scope: "nationwide", evidence: "전국 대상" } });
assert.equal(result.response.status, 200); item = result.data.item;
assert.deepEqual(item.reasons, ["relevance_unconfirmed", "application_deadline_unknown"]); assert.equal(item.aiStatus, "blocked");
assert.equal(item.history[0].actor, actor); assert.ok(item.history[0].at); assert.deepEqual(item.source, originalSource);
const oldPre = pre(item);
result = await mutate(store, "facts", factsId, { ...pre(item), action: "save_facts", facts: { ...item.facts, foreignEligibility: "eligible", deadlineKind: "fixed", deadlineOn: "2026-10-20" } });
assert.equal(result.response.status, 200); item = result.data.item; assert.equal(item.aiStatus, "queued"); assert.equal(item.status, "resolved"); assert.deepEqual(item.reasons, []);
assert.deepEqual(item.source, originalSource); assert.equal(item.revision, "a".repeat(64));
result = await mutate(store, "facts", factsId, { ...oldPre, action: "exclude", note: "stale" }); assert.equal(result.response.status, 409);
result = await mutate(store, "facts", factsId, { ...pre(item), action: "exclude", note: "already resolved" }); assert.equal(result.data.code, "already_processed");

store = new LocalReviewStore(); item = await store.get("facts", factsId);
result = await mutate(store, "facts", factsId, { ...pre(item), action: "exclude", note: "서비스 대상이 아님" });
assert.equal(result.data.item.status, "excluded"); assert.equal(result.data.item.aiStatus, "cancelled"); assert.equal(result.data.item.history[0].note, "서비스 대상이 아님");
store = new LocalReviewStore(); item = await store.get("facts", eventId);
result = await mutate(store, "facts", eventId, { ...pre(item), action: "save_facts", facts: { ...item.facts, eventStart: "2026-10-24", eventEnd: "2026-10-25" } });
assert.equal(result.data.item.aiStatus, "queued");
assert.throws(() => validateFacts({ ...item.facts, eventStart: "2026-10-25", eventEnd: "2026-10-24" }), ReviewFailure);
assert.throws(() => validateFacts({ ...fixtureFacts(), deadlineKind: "fixed", deadlineOn: "2026-02-30" }), ReviewFailure);
assert.throws(() => validateFacts({ ...fixtureFacts(), scope: "specific", regions: [] }), ReviewFailure);
assert.throws(() => validateFacts({ ...fixtureFacts(), regions: ["11"] }), ReviewFailure);
assert.throws(() => validateFacts({ ...fixtureFacts(), evidence: "x".repeat(501) }), ReviewFailure);

store = new LocalReviewStore(); item = await store.get("candidates", candidateId);
assert.throws(() => validateContent({ ...item.content, titleJa: " " }), ReviewFailure);
assert.throws(() => validateContent({ ...item.content, contentKo: "x".repeat(200001) }), ReviewFailure);
result = await mutate(store, "candidates", candidateId, { ...pre(item), action: "save_candidate", content: { ...item.content, titleJa: " 수정한 일본어 제목 " } });
assert.equal(result.response.status, 200); const saved = result.data.item; assert.equal(saved.status, "pending"); assert.equal(saved.content.titleJa, "수정한 일본어 제목");
assert.equal(saved.publishedAt, null); assert.equal(saved.history[0].action, "save_candidate"); assert.deepEqual(saved.source, item.source);
result = await mutate(store, "candidates", candidateId, { ...pre(item), action: "publish" }); assert.equal(result.data.code, "conflict", "Cannot publish an obsolete saved version");
result = await mutate(store, "candidates", candidateId, { ...pre(saved), action: "publish", content: saved.content }); assert.equal(result.response.status, 422, "Publish cannot smuggle unsaved content");
store.blockPublication(candidateId);
result = await mutate(store, "candidates", candidateId, { ...pre(saved), action: "publish" }); assert.equal(result.data.code, "publish_failed");
assert.deepEqual(await store.get("candidates", candidateId), saved, "Failed publish leaves no partial approval/history/publication");
store = new LocalReviewStore(); item = await store.get("candidates", candidateId);
result = await mutate(store, "candidates", candidateId, { ...pre(item), action: "publish" });
assert.equal(result.response.status, 200); assert.equal(result.data.item.status, "published"); assert.equal(result.data.item.history[0].actor, actor);
assert.equal(result.data.item.publishedAt, result.data.item.history[0].at); assert.ok(result.data.item.publishedId);
const historyBefore = result.data.item.history.length;
const simultaneous = await Promise.all([mutate(store, "candidates", candidateId, { ...pre(item), action: "publish" }), mutate(store, "candidates", candidateId, { ...pre(item), action: "publish" })]);
assert.ok(simultaneous.every((r) => r.response.status === 409)); assert.equal((await store.get("candidates", candidateId)).history.length, historyBefore);
store = new LocalReviewStore(); item = await store.get("candidates", candidateId);
const concurrent = await Promise.all([mutate(store, "candidates", candidateId, { ...pre(item), action: "publish" }), mutate(store, "candidates", candidateId, { ...pre(item), action: "publish" })]);
assert.deepEqual(concurrent.map((r) => r.response.status).sort(), [200, 409]); assert.equal((await store.get("candidates", candidateId)).history.length, 1);
store = new LocalReviewStore(); item = await store.get("candidates", candidateId);
result = await mutate(store, "candidates", candidateId, { ...pre(item), action: "reject", note: " 원문との不一致 " });
assert.equal(result.data.item.status, "rejected"); assert.equal(result.data.item.publishedAt, null); assert.equal(result.data.item.history[0].note, "원문との不一致");
store = new LocalReviewStore(); item = await store.get("candidates", candidateId); store.advanceRevision(candidateId);
result = await mutate(store, "candidates", candidateId, { ...pre(item), action: "publish" }); assert.equal(result.data.code, "conflict");

response = await listReviews(new Request(`${origin}/api/admin/review?kind=facts`), { authorize: admin, store: () => { throw new ReviewFailure("not_connected"); } });
assert.equal(response.status, 503); assert.equal((await response.json()).code, "not_connected");
response = await listReviews(new Request(`${origin}/api/admin/review?kind=facts`), { authorize: admin, store: () => { throw new Error("SECRET_TOKEN"); } });
assert.equal(response.status, 503); assert.ok(!(await response.text()).includes("SECRET_TOKEN")); noStore(response);
response = await reviewDetail(new Request(`${origin}/api/admin/review/facts/${factsId}`, { method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body: "x".repeat(2097153) }), "facts", factsId, deps);
assert.equal(response.status, 422); noStore(response);
const config = { NODE_ENV: "development", MACHIMOA_REVIEW_MODE: "local-fixture", NEXT_PUBLIC_SUPABASE_URL: "http://127.0.0.1:54329" };
assert.equal(localFixtureEnabled(config), true);
for (const override of [{ NODE_ENV: "production" }, { NODE_ENV: "test" }, { MACHIMOA_REVIEW_MODE: undefined }, { NEXT_PUBLIC_SUPABASE_URL: "https://production.supabase.co" }, { NEXT_PUBLIC_SUPABASE_URL: "http://localhost.attacker.invalid" }]) assert.equal(localFixtureEnabled({ ...config, ...override }), false);
assert.equal(sourceLink("javascript:alert(1)"), null); assert.equal(sourceLink("https://user:secret@example.invalid"), null);
assert.equal(sourceLink("https://example.invalid/original"), "https://example.invalid/original");
assert.ok(reasonText("UNKNOWN_NEW_REASON").help.includes("임의로"));
console.log("Admin review tests passed: protected reads/mutations, CSRF, validated inputs, revision/version conflicts, server actor/history, private save, atomic fixture publish/rollback/duplicate prevention, exclusion/rejection, no-store and fail-closed local configuration. Test doubles only; no DB/OAuth/AI/Production calls.");
