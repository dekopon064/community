// Loopback RPC transport/adapter + migration contract checks. NO SQL execution.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { registerHooks } from "node:module";
import { readFile } from "node:fs/promises";
registerHooks({ resolve(specifier, context, nextResolve) {
  if (specifier === "server-only") return { url: "data:text/javascript,export{}", shortCircuit: true };
  try { return nextResolve(specifier, context); }
  catch (error) { if (specifier.startsWith(".") && !/\.[a-z]+$/i.test(specifier)) return nextResolve(`${specifier}.ts`, context); throw error; }
} });
const { DatabaseReviewStore } = await import("../app/lib/review/database-store.ts");
const { databaseReviewConfig } = await import("../app/lib/review/database-config.ts");
const { getReviewStore } = await import("../app/lib/review/server.ts");
const { reviewDetail, listReviews } = await import("../app/lib/review/handlers.ts");
const { AdminAccessError } = await import("../app/lib/auth/admin-policy.ts");
const { LocalReviewStore } = await import("../app/lib/review/local-fixture.ts");
const { aiStatusText, reasonText } = await import("../app/lib/review/presentation.ts");
const { databaseItem } = await import("../app/lib/review/database-dto.ts");
assert.match(aiStatusText.claimed, /진행 중/); assert.match(aiStatusText.completed, /완료/); assert.match(aiStatusText.failed, /실패/);
assert.match(reasonText("policy_lifecycle_uncertain").help, /선택/);
const id = "20000000-0000-4000-8000-000000000001";
const factId = "10000000-0000-4000-8000-000000000001";
const actor = "00000000-0000-4000-8000-000000000001";
const fixture = new LocalReviewStore();
const candidate = { ...await fixture.get("candidates", id), version: "c".repeat(64), raw_payload: "DO_NOT_ECHO_SECRET" };
const facts = { ...await fixture.get("facts", factId), version: "d".repeat(64), editableFields: ["scope", "regions", "evidence"], excludeAllowed: false };
assert.throws(() => databaseItem({ ...facts, editableFields: ["constructor"] }, "facts", factId), (e) => e.code === "unavailable");
const key = ["local-test", Buffer.from(JSON.stringify({ role: "service_role" })).toString("base64url"), "local-test-only"].join(".");
const mode = { MACHIMOA_REVIEW_MODE: "database", NEXT_PUBLIC_SUPABASE_URL: "http://127.0.0.1", SUPABASE_SERVICE_ROLE_KEY: key };
assert.ok(databaseReviewConfig(mode));
for (const values of [{ MACHIMOA_REVIEW_MODE: "local-fixture" }, { SUPABASE_SERVICE_ROLE_KEY: undefined }, { SUPABASE_SERVICE_ROLE_KEY: "sb_publishable_not_secret" }, { NEXT_PUBLIC_SUPABASE_ANON_KEY: key }, { NEXT_PUBLIC_SUPABASE_URL: "http://not-loopback.invalid" }, { NEXT_PUBLIC_SUPABASE_URL: "https://user:pass@host.invalid" }]) assert.equal(databaseReviewConfig({ ...mode, ...values }), null);
assert.ok(databaseReviewConfig({ ...mode, SUPABASE_SERVICE_ROLE_KEY: "sb_secret_local-test-only-fake" }));

const requests = []; let failure = null; let malformed = false;
const server = createServer(async (req, res) => {
  const chunks = []; for await (const chunk of req) chunks.push(chunk);
  if (process.argv.includes("--serve") && !req.url.startsWith("/rest/v1/rpc/admin_review_")) {
    // Browser smoke test only: forward exclusively to the existing loopback fake Auth.
    const result = await fetch(`http://127.0.0.1:54329${req.url}`, { redirect: "manual", method: req.method,
      headers: { "Content-Type": req.headers["content-type"] ?? "application/json", Authorization: req.headers.authorization ?? "" },
      ...(req.method === "GET" ? {} : { body: Buffer.concat(chunks) }) });
    res.writeHead(result.status, Object.fromEntries(result.headers)); res.end(Buffer.from(await result.arrayBuffer())); return;
  }
  const args = JSON.parse(Buffer.concat(chunks).toString());
  requests.push({ path: req.url, headers: req.headers, args });
  res.setHeader("Content-Type", "application/json");
  if (failure) { res.writeHead(409); res.end(JSON.stringify(failure)); return; }
  if (malformed) { res.end(JSON.stringify({ raw_payload: "DO_NOT_ECHO_SECRET" })); return; }
  const name = req.url.split("/").at(-1);
  res.end(JSON.stringify(name === "admin_review_list" ? [args.p_kind === "facts" ? { id: factId, title: facts.source.title, sourceName: facts.source.name, status: "open", reasons: facts.reasons } : { id, title: candidate.content.titleKo, sourceName: candidate.source.name, status: "pending", reasons: [], raw_payload: "DO_NOT_ECHO_SECRET" }] : args.p_kind === "facts" || name === "admin_review_save_facts" || name === "admin_review_exclude" ? facts : candidate));
});
await new Promise((resolve) => server.listen(process.argv.includes("--serve") ? 54330 : 0, "127.0.0.1", resolve));
const url = `http://127.0.0.1:${server.address().port}`;
if (process.argv.includes("--serve")) {
  console.log(`Loopback RPC response double (NO DB/SQL): ${url}. Requires fake Auth --serve on 54329.`);
  await new Promise(() => {});
}
const names = ["MACHIMOA_REVIEW_MODE", "NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"];
const saved = Object.fromEntries(names.map((name) => [name, process.env[name]]));
Object.assign(process.env, { MACHIMOA_REVIEW_MODE: "database", NEXT_PUBLIC_SUPABASE_URL: url, SUPABASE_SERVICE_ROLE_KEY: key });
const fetchOriginal = globalThis.fetch; const fetchOptions = [];
globalThis.fetch = (input, options) => { fetchOptions.push(options); return fetchOriginal(input, options); };
try {
  const store = getReviewStore(); assert.equal(store.mode, "database");
  const list = await store.list("candidates", 25); assert.equal(list.length, 1); assert.equal("raw_payload" in list[0], false);
  assert.deepEqual(requests.at(-1).args, { p_kind: "candidates", p_offset: 25, p_limit: 25 });
  const item = await store.get("candidates", id); assert.equal("raw_payload" in item, false); assert.deepEqual(item.content, candidate.content);
  const factItem = await store.get("facts", factId); assert.deepEqual(factItem.editableFields, facts.editableFields); assert.equal(factItem.excludeAllowed, false);
  const pre = { revision: item.revision, version: item.version };
  await assert.rejects(store.execute("facts", id, { ...pre, action: "publish" }, actor), (e) => e.code === "invalid_input");
  for (const command of [
    { ...pre, action: "save_candidate", content: item.content }, { ...pre, action: "publish" }, { ...pre, action: "reject", note: "local reason" },
  ]) {
    await store.execute("candidates", id, command, actor);
    assert.equal(requests.at(-1).args.p_actor, actor);
    assert.equal(requests.at(-1).args.p_revision, pre.revision); assert.equal(requests.at(-1).args.p_version, pre.version);
    if (command.action === "publish") assert.deepEqual(Object.keys(requests.at(-1).args).sort(), ["p_actor", "p_id", "p_revision", "p_version"]);
  }
  await store.execute("facts", factId, { revision: facts.revision, version: facts.version, action: "save_facts", facts: facts.facts }, actor);
  assert.deepEqual(requests.at(-1).args.p_facts, facts.facts);
  await store.execute("facts", factId, { revision: facts.revision, version: facts.version, action: "exclude", note: "local reason" }, actor);
  assert.equal(requests.at(-1).args.p_note, "local reason");
  for (const request of requests) { assert.equal(request.headers.authorization, `Bearer ${key}`); assert.equal(request.headers.apikey, key); assert.equal(request.headers.cookie, undefined); }
  assert.ok(fetchOptions.every((options) => options.cache === "no-store" && options.signal));
  for (const [message, code] of [["review_conflict", "conflict"], ["review_already_processed", "already_processed"], ["review_not_found", "not_found"], ["review_invalid_input", "invalid_input"], ["review_publish_failed", "publish_failed"], ["DO_NOT_ECHO_SECRET", "unavailable"]]) {
    failure = { code: "PT409", message, details: "DO_NOT_ECHO_SECRET" };
    await assert.rejects(store.get("candidates", id), (e) => e.code === code && !JSON.stringify(e).includes("DO_NOT_ECHO_SECRET"));
  }
  failure = null; malformed = true;
  await assert.rejects(store.get("candidates", id), (e) => e.code === "unavailable"); malformed = false;
  const deps = { authorize: async () => ({ userId: actor }), store: () => store };
  const origin = "http://localhost:3100";
  const request = new Request(`${origin}/api/admin/review/candidates/${id}`, { method: "POST", headers: { Origin: origin, "Content-Type": "application/json", "x-user-id": "FORGED" }, body: JSON.stringify({ ...pre, action: "publish" }) });
  let response = await reviewDetail(request, "candidates", id, deps);
  assert.equal(response.status, 200); assert.match(response.headers.get("cache-control"), /private.*no-store/); assert.equal((await response.json()).mode, "database"); assert.equal(requests.at(-1).args.p_actor, actor);
  response = await listReviews(new Request(`${origin}/api/admin/review?kind=candidates&offset=-1`), deps); assert.equal(response.status, 422);
  const count = requests.length;
  for (const [status, expected] of [["signed_out", 401], ["forbidden", 403], ["auth_unavailable", 503]]) {
    response = await reviewDetail(new Request(`${origin}/api/admin/review/candidates/${id}`), "candidates", id, { ...deps, authorize: async () => { throw new AdminAccessError(status); } }); assert.equal(response.status, expected);
  }
  assert.equal(requests.length, count, "Denied requests never reach database adapter");
  delete process.env.SUPABASE_SERVICE_ROLE_KEY;
  assert.throws(getReviewStore, (e) => e.code === "not_connected", "No silent fixture fallback");
  await assert.rejects(new DatabaseReviewStore({ rpc: async () => { throw new Error("DO_NOT_ECHO_SECRET"); } }).get("candidates", id), (e) => e.code === "unavailable");
} finally {
  globalThis.fetch = fetchOriginal;
  for (const name of names) { if (saved[name] === undefined) delete process.env[name]; else process.env[name] = saved[name]; }
  await new Promise((resolve) => server.close(resolve));
}

const sql = await readFile(new URL("../supabase/migrations/20260930000000_admin_review_rpc.sql", import.meta.url), "utf8");
const down = await readFile(new URL("../supabase/rollback/20260930000000_admin_review_rpc_down.sql", import.meta.url), "utf8");
assert.equal((sql.match(/create function public\.admin_review_/g) ?? []).length, 7);
assert.equal((sql.match(/security definer set search_path = ''/g) ?? []).length, 12);
assert.match(sql, /revoke all on function %s from public, anon, authenticated, service_role/);
assert.match(sql, /grant execute on function %s to service_role/);
assert.doesNotMatch(sql, /grant[^;]+to (anon|authenticated)|update machimoa_review\.source_items|create or replace function/i);
assert.match(sql, /publish_curation_candidate\(p_id,p_actor::text,null,false\)/);
assert.match(sql, /resolve_source_item_gate_facts/); assert.match(sql, /resolve_source_item_user_category/); assert.match(sql, /resolve_source_item_application_deadline/);
assert.match(sql, /for update/); assert.match(sql, /sha256/); assert.match(sql, /same/i); assert.match(sql, /review_already_processed/);
assert.match(sql, /can_confirm_type := missing_type/); assert.match(sql, /'content_review'=any\(stages\) and reasons \?\| array\['policy_lifecycle_uncertain'/);
assert.match(down, /if exists\(select 1 from machimoa_review.admin_review_events\)/);
assert.doesNotMatch(down, /cascade|delete from|update /i);
console.log("PASS: database adapter/loopback SDK transport, guard/no-store/actor/errors/config and static migration contracts. SQL NOT executed.");
