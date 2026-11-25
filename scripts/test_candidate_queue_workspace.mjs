// Isolated browser regression. Routes are fulfilled in memory, including Auth and RPC.
import assert from "node:assert/strict";
import path from "node:path";

import { mkdir, mkdtemp, writeFile, readFile } from "node:fs/promises";
import { createRequire, registerHooks } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("../", import.meta.url));
const testCache = path.join(root, ".next", "cache");
await mkdir(testCache,{recursive:true});
const tmp = await mkdtemp(path.join(testCache, "candidate-queue-test-"));
const webpackLib = require("next/dist/compiled/webpack/webpack");

const loader = path.join(tmp, "tsx.cjs");
await writeFile(loader, `const ts=require(${JSON.stringify(require.resolve("typescript"))});module.exports=function(src){return ts.transpileModule(src,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText}`);
await writeFile(path.join(tmp, "index.js"), 'import React from "react";import{createRoot}from"react-dom/client";import Workspace from "@/app/components/admin/ReviewWorkspace";createRoot(document.getElementById("root")).render(React.createElement(Workspace));');
await new Promise((resolve, reject) => webpackLib.webpack({
  mode: "development", entry: path.join(tmp, "index.js"), devtool: false,
  plugins:[new webpackLib.webpack.DefinePlugin({"process.env":JSON.stringify({NODE_ENV:"development"})})],
  output: { path: tmp, filename: "bundle.js" },
  resolve: { alias: { "@": root }, extensions: [".tsx", ".ts", ".js", ".mjs", ".json"], modules: [path.join(root, "node_modules"), "node_modules"] },
  module: { rules: [{ test: /\.tsx?$/, use: loader }, { test: /\.css$/, type: "asset/source" }] },
}, (error, stats) => error || stats.hasErrors() ? reject(error || Error(stats.toString({ all:false, errors:true }))) : resolve()));
const bundle = await readFile(path.join(tmp, "bundle.js"));
registerHooks({ resolve(s, c, next) {
  try { return next(s, c); } catch (e) { if (s.startsWith(".") && !path.extname(s)) return next(s+".ts",c); throw e; }
} });
const { reviewDetail, listReviews } = await import("../app/lib/review/handlers.ts");
const { DatabaseReviewStore } = await import("../app/lib/review/database-store.ts");
const { focusCandidates } = await import("./fixtures/candidate-review-focus.ts");
const { candidateQueuePage } = await import("../app/lib/review/candidate-queue-page.ts");

for(const count of [0,1,24,25,26,50,51,99,100,501]) {
  const ids = Array.from({length:count}, (_,i)=>i);
  for(const offset of [0,25,50,75,500,525]) {
    const page = await candidateQueuePage(start=>Promise.resolve(ids.slice(start,start+25)),offset);
    const expected = Math.min(offset, Math.max(0, Math.ceil(count/25)-1)*25);
    assert.deepEqual(page,{offset:expected,items:ids.slice(expected,expected+25),total:count,hasMore:expected+25<count});
  }
}
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser = await chromium.launch({ headless:true, ...(process.env.TEST_BROWSER_PATH ? { executablePath:process.env.TEST_BROWSER_PATH } : {}) });
try {
  const page = await browser.newPage({serviceWorkers:"block"});
  page.setDefaultTimeout(6000);
  const errors = [];
  page.on("pageerror",e=>{errors.push(String(e));console.error(e.message);});
  const templates = focusCandidates().slice(0,2);
  let rows = [], writes = 0, reads = 0, nextFailure = "", loseReply = false, authReads = 0;
  let holdList = false, releaseList, heldList;
  function seed(count) {
    rows = Array.from({length:count}, (_,i)=>{
      const row=structuredClone(templates[i%2]);
      row.id="20000000-0000-4000-8000-"+String(i+1).padStart(12,"0");
      row.content.titleKo="후보 "+(i+1); row.version="1".padStart(64,"0"); delete row.filterInfo;
      return row;
    });
  }
  const store = new DatabaseReviewStore({async rpc(name,args){
    if(name==="admin_review_list") {
      const pending=args.p_kind==="facts"?[]:rows.filter(r=>r.status==="pending");
      return {data:pending.slice(args.p_offset,args.p_offset+args.p_limit).map(r=>({id:r.id,title:r.content.titleKo,sourceName:r.source.name,status:r.status,reasons:[]})),error:null};
    }
    if(name==="admin_myseoul_candidate_notice_input") return {data:null,error:{message:"synthetic unavailable"}};
    const row=rows.find(r=>r.id===args.p_id);
    assert.ok(row);
    if(name==="admin_review_detail") { reads++; return {data:structuredClone(row),error:null}; }
    writes++;
    if(nextFailure){ const message=nextFailure;nextFailure="";return {data:null,error:{message}}; }
    assert.equal(row.version,args.p_version); assert.equal(row.revision,args.p_revision);
    assert.equal(row.status,"pending"); assert.equal(args.p_actor,"fixture-operator");
    if(name==="admin_review_publish"){row.status="published";row.publishedAt="2026-11-23T04:00:00Z";row.publishedId=row.id;}
    else if(name==="admin_review_reject") row.status="rejected";
    else {assert.match(name,/^admin_review_save_candidate(_image)?$/);row.content=args.p_content;}
    row.version=(BigInt(row.version)+1n).toString().padStart(64,"0");
    return {data:structuredClone(row),error:null};
  }});
  const deps={authorize:async()=>{authReads++;return {userId:"fixture-operator"};},store:()=>store};
  const origin="http://candidate-queue.invalid";
  await page.route("**/*",async route=>{
    const req=route.request(),u=new URL(req.url());
    if(u.origin!==origin) {await route.abort();return;}
    if(u.pathname==="/"){await route.fulfill({contentType:"text/html",body:'<html><body><div id="root"></div><script src="/bundle.js"></script></body></html>'});return;}
    if(u.pathname==="/bundle.js"){await route.fulfill({contentType:"text/javascript; charset=utf-8",body:bundle});return;}
    if(u.pathname==="/api/admin/suitability" && req.method()==="GET"){await route.fulfill({json:{report:null}});return;}
    if(u.pathname!=="/api/admin/review" && !/^\/api\/admin\/review\/candidates\/[\da-f-]+$/.test(u.pathname)){await route.fulfill({status:404,json:{code:"not_found"}});return;}
    const request=new Request(req.url(),{method:req.method(),headers:{Origin:origin,"Content-Type":"application/json"},...(req.method()==="POST"?{body:req.postData()}:{})});
    const response=u.pathname==="/api/admin/review"?await listReviews(request,deps):await reviewDetail(request,"candidates",u.pathname.split("/").at(-1),deps);
    if(req.method()==="POST" && loseReply){loseReply=false;await route.abort();return;}
    if(holdList && u.searchParams.get("kind")==="candidates" && u.searchParams.get("offset")==="0"){
      holdList=false;let resume;heldList=new Promise(r=>resume=r);releaseList=resume;await heldList;
    }
    await route.fulfill({status:response.status,contentType:"application/json",body:await response.text()}).catch(()=>{});
  });
  const btn=n=>page.getByRole("button",{name:n,exact:true});
  const aside=page.getByRole("complementary",{name:"검토 목록"});
  const heading=page.locator('section[aria-label="선택한 항목 검토"] header h2');
  const selected=()=>aside.locator('button[aria-current="true"]');
  const waitCount=n=>aside.getByText("남은 "+n+"건",{exact:true}).waitFor();
  const start=async n=>{seed(n);await page.goto(origin);await btn("AI 결과 후보 검토").click();await waitCount(n);};
  const choose=async title=>{await aside.getByText(title,{exact:true}).click();await heading.filter({hasText:title}).waitFor();};
  const save=async()=>{await btn("수정 저장").click();};
  const publish=async(double=false)=>{await btn("승인하고 게시").click();const confirm=btn("확인하고 게시");if(double)await confirm.evaluate(el=>{el.click();el.click();});else await confirm.click();};
  const reject=async()=>{await page.locator("#review-note").fill("합성 반려 사유");await btn("사유를 남기고 반려").click();await btn("확인하고 처리").click();};
  await start(2);await choose("후보 1");
  await page.locator("#titleKo").fill("수정한 후보");
  await btn("원문 편집").first().click();await btn("원문 편집").last().click();
  const ko=page.getByLabel("한국어 상세 원문",{exact:true}),ja=page.getByLabel("일본어 상세 원문",{exact:true});
  await ko.fill("바뀐 한국어 본문");await ja.fill("更新した日本語本文");
  nextFailure="review_invalid_input";await save();await page.getByRole("alert").waitFor();
  assert.equal(await ko.inputValue(),"바뀐 한국어 본문");assert.equal(await ja.inputValue(),"更新した日本語本文");
  nextFailure="review_conflict";await save();await page.getByRole("alert").waitFor();
  assert.equal(await ko.inputValue(),"바뀐 한국어 본문");assert.equal(await ja.inputValue(),"更新した日本語本文");await waitCount(2);
  await save();await aside.getByText("수정한 후보",{exact:true}).waitFor();await waitCount(2);
  assert.match(await selected().innerText(),/수정한 후보/);
  assert.equal(rows[0].content.contentKo,"바뀐 한국어 본문");assert.equal(rows[0].content.contentJa,"更新した日本語本文");
  const before=writes;await publish(true);await waitCount(1);assert.equal(writes,before+1);assert.equal(await selected().count(),0);
  assert.equal(await aside.getByText("수정한 후보").count(),0);await btn("다음 후보 검토").click();await heading.filter({hasText:"후보 2"}).waitFor();
  loseReply=true;const beforeReject=writes, beforeRead=reads;await reject();await waitCount(0);assert.equal(writes,beforeReject+1);assert.ok(reads>beforeRead);
  await aside.getByText(/현재 검토할 항목이 없습니다/).waitFor();assert.equal(await selected().count(),0);assert.equal(await btn("다음 후보 검토").count(),0);
  console.log("PASS mixed sources: failed save/conflict retained KO+JA drafts; save kept 2 and selection; double publish 2→1; explicit next; lost reject response reconciled by GET 1→0.");
  await start(26);await choose("후보 1");
  await page.locator("#titleJa").fill("保存後の見出し");
  const scrollBefore=await aside.evaluate(el=>{el.style.height="80px";el.style.overflowY="auto";el.scrollTop=40;return el.scrollTop;});
  assert.ok(scrollBefore>0);
  loseReply=true;const beforeSave=writes;
  await save();await page.getByText(/최신 조회로 확인한 결과: 비공개 저장본 일치/).waitFor();
  assert.equal(writes,beforeSave+1);assert.equal(await aside.evaluate(el=>el.scrollTop),scrollBefore);await waitCount(26);
  assert.match(await selected().innerText(),/후보 1/);assert.equal(await page.locator("#titleJa").inputValue(),"保存後の見出し");
  console.log("PASS lost private-save response: verified stored Japanese title, selected candidate, list scroll offset and total unchanged.");
  await btn("다음 목록").click();await choose("후보 26");await waitCount(26);holdList=true;
  await publish();await waitCount(25);await btn("다음 후보 검토").click();await heading.waitFor();
  const second=writes;await publish();await waitCount(24);assert.equal(writes,second+1);assert.equal(typeof releaseList,"function");
  releaseList();await page.waitForTimeout(100);await waitCount(24);assert.equal(await aside.locator("li").count(),24);assert.equal(await selected().count(),0);
  console.log("PASS server totals/paging: 1 visible of 26 → 25 on previous page → 24; late 25-row response did not restore removed candidate.");
  await start(1);await choose("후보 1");loseReply=true;nextFailure="review_conflict";
  const originalWrites=writes;await publish();await page.getByText(/최신 조회로 처리 결과를 확인하지 못했습니다/).waitFor();await waitCount(1);
  await btn("처리 결과 다시 확인").click();assert.equal(writes,originalWrites+1);assert.equal(await selected().count(),1);
  assert.ok(authReads>0);assert.deepEqual(errors,[]);
  console.log("PASS unconfirmed result retained row/selection and count; repeated state check was read-only. Pagination matrix: 60 cases.");
  if(process.env.CLASSIFICATION_BROWSER_TEST==="1") {
    // Captured only from test_initial_classification_queue.py's network-none synthetic DB.
    const f=JSON.parse(await readFile(path.join(testCache,"classification-queue-fixture.json"),"utf8"));
    const tab=await browser.newPage({serviceWorkers:"block"});
    tab.setDefaultTimeout(7000);
    let saved=false, saves=0, navigations=0;
    await tab.route("**/*",async route=>{
      const req=route.request(),url=new URL(req.url());
      const reply=json=>route.fulfill({json:{mode:"database",...json}});
      if(url.origin!=="http://fixture.invalid")return route.abort();
      if(url.pathname==="/"){navigations++;return route.fulfill({contentType:"text/html",body:'<meta charset=utf-8><div id="root"></div><script src="/app.js"></script>'});}
      if(url.pathname==="/app.js")return route.fulfill({contentType:"text/javascript",body:bundle});
      if(url.pathname==="/api/admin/review") {
        const items=saved?[]:[{id:f.native.id,sourceName:"myseoul_program",title:f.job.title,status:"open",reasons:["category_unresolved"]}];
        return reply({items,total:items.length,hasMore:false,offset:0});
      }
      if(url.pathname==="/api/admin/myseoul-review/"+f.native.id)return reply({item:saved?f.nativeSaved:f.native});
      if(url.pathname==="/api/admin/review-classification/"+f.native.id) {
        if(req.method()==="POST"){
          const input=req.postDataJSON();
          assert.deepEqual(input.filters,f.saved.filters);assert.deepEqual(input.facts,f.saved.facts);
          assert.equal(input.version,f.classification.version);saved=true;saves++;
        }
        return reply({item:saved?f.saved:f.classification});
      }
      if(url.pathname==="/api/admin/ai-queue")return reply({items:saved?[f.job]:[],waitingTotal:Number(saved),
        checkedAt:new Date().toISOString(),offset:0,held:[],observed:[],hasMore:false});
      return route.abort();
    });
    await tab.goto("http://fixture.invalid/");
    const sidebar=tab.locator("aside");
    await sidebar.getByText("남은 1건",{exact:true}).waitFor();
    await sidebar.getByRole("button",{name:new RegExp(f.job.title.replace(/[()]/g,"."))}).click();
    await tab.locator("#classification-category").selectOption("program");
    for(const [field,value] of [["delivery","onsite"],["topic","culture_experience"],["audience","other"],["location","specific"]]){
      const selector=tab.locator("#classification-filter-"+field+" select").first();
      if(await selector.count())await selector.selectOption(value);
    }
    await tab.locator("#classification-filter-location select").nth(1).selectOption("11");
    await tab.getByRole("button",{name:"분류·필수값 저장·재판정"}).click();
    await sidebar.getByText("남은 0건",{exact:true}).waitFor();
    assert.equal(await sidebar.locator("li").count(),0);
    await tab.getByRole("button",{name:"AI 작업 대기",exact:true}).click();
    const ai=tab.getByRole("region",{name:"AI 작업 대기",exact:true});
    await ai.getByText("실행 가능한 AI 작업 · 남은 1건").waitFor();
    assert.equal(await ai.getByRole("heading",{name:f.job.title,exact:true}).count(),1);
    assert.equal(navigations,1);assert.equal(saves,1);
    await tab.close();
    console.log("PASS initial classification in the same tab: facts 1→0, executable AI 0→1, one save, no reload.");
  }
} finally {await browser.close();}
