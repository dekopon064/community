// The production mapper, query, filter and React components; no real services.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import { syncBuiltinESMExports } from 'node:module';
const deny=()=>{throw Error('external_network_forbidden');};
globalThis.fetch=http.get=http.request=https.get=https.request=net.Socket.prototype.connect=deny;
syncBuiltinESMExports();
// Reuse the established TS/React/CSS/fake-Supabase loader and filter regressions.
await import('./test_public_content_filters.mjs');
const f=await import('../app/lib/publicContentFilters.ts');
const {emptyContentFilters}=await import('../app/lib/contentFilters.ts');
const {localizeCuration}=await import('../app/lib/curations.ts');
const {default:List}=await import('../app/components/PublicCurationList.tsx');
const React=await import('react');
const {renderToStaticMarkup}=await import('react-dom/server');
let checks=0;
const test=(name,run)=>{run();checks++;console.log('PASS search '+name);};
const row={id:'public-1',slug:'public-1',category:'program',user_category:'program',title_ko:'목공 배우기',title_ja:'木工を学ぶ',summary_ko:'함께 만드는 의자',summary_ja:'一緒に作る椅子',content_ko:'## 신청 방법\n**전화 예약** 후 방문합니다.\n| 시간 | 안내 |\n| 10:00 | 초보자 가능 |',content_ja:'## 申込方法\n**電話予約**の後に訪問します。\n| 時間 | 案内 |\n| 10:00 | 初心者歓迎 |',created_at:'2026-11-01T00:00:00Z',updated_at:'2026-11-01T00:00:00Z'};
const ko=f.publicCurationItem(localizeCuration(row,'ko')),ja=f.publicCurationItem(localizeCuration(row,'ja'));
const q=(value,category)=>f.readExplorationQuery(new URLSearchParams(value),category);
test('title, summary and body-only terms find the same published item',()=>{for(const term of ['목공','의자','전화 예약','초보자','10:00'])assert(f.matchesPublicSearch(ko,term));assert(!f.matchesPublicSearch(ko,'없는단어'));});
test('locale selects its own body and never the other locale or source payload',()=>{assert(f.matchesPublicSearch(ja,'電話予約'));assert(!f.matchesPublicSearch(ja,'전화 예약'));assert(!f.matchesPublicSearch(ko,'電話予約'));const out=f.publicCurationItem({...localizeCuration(row,'ko'),raw_payload:{body:'숨긴원문'},note:'운영자비공개메모'});assert(!f.matchesPublicSearch(out,'숨긴원문'));assert(!f.matchesPublicSearch(out,'운영자비공개메모'));});
test('multiple words are AND across title, summary and body, not a phrase requirement',()=>{assert(f.matchesPublicSearch(ko,'목공 의자 초보자'));assert(!f.matchesPublicSearch(ko,'목공 중급자'));});
test('case, full-width characters, Korean composition and whitespace normalize',()=>{const item=f.publicCurationItem({...localizeCuration(row,'ko'),content:'ＡＩ Workshop\n예약 가능'});assert(f.matchesPublicSearch(item,'ai\tworkshop'));assert(f.matchesPublicSearch(item,'예약'.normalize('NFD')));assert.equal(f.normalizePublicSearch('  ＡＩ\n 예약  '),'AI 예약');});
test('Markdown labels, emphasis, entities, tables and code remain searchable',()=>{const item=f.publicCurationItem({...localizeCuration(row,'ko'),content:'목**공** [온라인 접수](https://example.invalid/private-target)\n&amp; &#xAC00; &#45208;\n[수업 안내][ref]\n[ref]: https://example.invalid/secret-ref\n`console.log`\n| 수 | 일본어 |'});for(const term of ['목공','온라인 접수','&','가 나','수업 안내','console.log','수 일본어'])assert(f.matchesPublicSearch(item,term),term);for(const term of ['private-target','secret-ref'])assert(!f.matchesPublicSearch(item,term),term);});
test('comments, HTML attributes and non-rendered scripts do not create matches',()=>{const item=f.publicCurationItem({...localizeCuration(row,'ko'),content:'<!-- 숨김 --> <span data-note="내부값">안내</span><script>실행금지</script>'});assert(f.matchesPublicSearch(item,'안내'));for(const term of ['숨김','내부값','실행금지'])assert(!f.matchesPublicSearch(item,term));});
test('literal special characters do not become regex or HTML execution',()=>{const item=f.publicCurationItem({...localizeCuration(row,'ko'),content:'C++ (입문) 1.5'});assert(f.matchesPublicSearch(item,'C++'));assert(f.matchesPublicSearch(item,'1.5'));assert(!f.matchesPublicSearch(item,'.*'));assert(!f.matchesPublicSearch(item,'<img onerror=alert(1)>'));});
test('query bounds, duplicate q, empty and control input are deterministic',()=>{assert.equal(q('q=first&q=second').search,'first');assert.equal(q('q='+encodeURIComponent('x'.repeat(300))).search.length,200);assert.equal(q('q=%20%0A%20').search,'');assert(f.matchesPublicSearch(ko,''));});
test('URL round trips preserve filters, sorting and campaign values but clear stale page',()=>{const current=new URLSearchParams('topic=language_learning&region=11&sort=latest&utm_source=test&page=4');const next=f.writeExplorationQuery(current,{...q(current.toString(),'program'),search:'전화 예약'},'program');assert.equal(next.get('q'),'전화 예약');assert.equal(next.get('topic'),'language_learning');assert.equal(next.get('region'),'11');assert.equal(next.get('sort'),'latest');assert.equal(next.get('utm_source'),'test');assert(!next.has('page'));assert.equal(q(next.toString(),'program').search,'전화 예약');});
test('search-only clear preserves filters; full reset clears both',()=>{const current=new URLSearchParams('q=목공&topic=language_learning&region=11');const cleared=f.writeExplorationQuery(current,{...q(current.toString(),'program'),search:''},'program');assert(!cleared.has('q'));assert.equal(cleared.get('region'),'11');const reset=f.writeExplorationQuery(current,q('','program'),'program');for(const k of ['q','region','topic'])assert(!reset.has(k));});
test('search combines with confirmed filters and preserves existing order',()=>{const known=value=>({status:'known',value});const data={...emptyContentFilters('program'),topic:known('culture_experience'),location:known({scope:'specific',venues:[{province:'11',district:'강동구',facility:'합성 장소',address:'합성 주소'}]})};const item={...ko,contentFilters:data};assert.equal(f.exploreCurations([item],'program',q('q=전화&region=11&district=11:강동구&topic=culture_experience','program'),Date.now()).length,1);assert.equal(f.exploreCurations([item],'program',q('q=전화&region=41','program'),Date.now()).length,0);assert.equal(f.exploreCurations([ko],'program',q('q=전화&region=11','program'),Date.now()).length,0);const rows=[item,{...item,id:'new',created_at:'2026-11-02T00:00:00Z'},{...item,id:'no',searchText:'다른 본문'}];assert.deepEqual(f.exploreCurations(rows,'program',q('q=전화&sort=latest','program'),Date.now()).map(i=>i.id),['new','public-1']);});
test('policy, living and all-information URLs also carry search',()=>{for(const category of [undefined,'policy','living']){const parsed=q('q=의자',category);assert.equal(parsed.search,'의자');assert.equal(f.writeExplorationQuery(new URLSearchParams(),parsed,category).get('q'),'의자');}});
test('search projection does not mutate original public content or facts',()=>{const before=JSON.stringify(row);f.publicCurationItem(localizeCuration(row,'ko'));assert.equal(JSON.stringify(row),before);assert.equal(ko.content,undefined);assert.equal(ko.raw_payload,undefined);});
for(const locale of ['ko','ja']){
  globalThis.testLocale=locale;globalThis.testMessages=JSON.parse(fs.readFileSync(`messages/${locale}.json`,'utf8'));
  test(locale+' actual list renders body search, applied query, result and translated clear action',()=>{globalThis.testParams='q='+encodeURIComponent(locale==='ko'?'초보자':'初心者');const html=renderToStaticMarkup(React.createElement(List,{items:[locale==='ko'?ko:ja],todayKst:'2026-11-02',nowIso:'2026-11-02T00:00:00Z'}));assert(html.includes('role="search"'));assert(html.includes(globalThis.testMessages.PublicSearch.label));assert(html.includes(globalThis.testMessages.PublicSearch.clear));assert(html.includes(locale==='ko'?row.title_ko:row.title_ja));});
  test(locale+' actual empty list offers reset and escapes arbitrary search text',()=>{globalThis.testParams='q='+encodeURIComponent('<script>alert(1)</script>');const html=renderToStaticMarkup(React.createElement(List,{items:[ko],todayKst:'2026-11-02',nowIso:'2026-11-02T00:00:00Z'}));assert(html.includes(globalThis.testMessages.Info.searchEmptyTitle));assert(html.includes(globalThis.testMessages.PublicSearch.resetAll));assert(!html.includes('<script>'));});
}
console.log(JSON.stringify({search_checks:checks,real_network:0,operational_db:0,ai_calls:0}));
