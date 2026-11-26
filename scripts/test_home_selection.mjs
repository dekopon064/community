import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { registerHooks, syncBuiltinESMExports } from 'node:module';
import { pathToFileURL } from 'node:url';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import ts from 'typescript';
import { renderToStaticMarkup } from 'react-dom/server';

// Tests import the real route -> public localization -> selection -> components.
// Every external transport is forbidden; only the in-memory public query/RPC is used.
const deny = () => { throw Error('external_network_forbidden'); };
globalThis.fetch = http.request = http.get = https.request = https.get = net.Socket.prototype.connect = deny;
syncBuiltinESMExports();
const root = path.resolve('.'), moduleUrl = source => `data:text/javascript,${encodeURIComponent(source)}`;
const queries = [], rpcCalls = [];
globalThis.homeTest = { rows: [], queries, rpcCalls, locale: 'ko' };
const link = moduleUrl(`import React from 'react';export function Link({children,feedback,href,...p}){return React.createElement('a',{href,...p},children)}export default Link;`);
const mocks = {
  'next/navigation': moduleUrl(`export function useParams(){return {locale:globalThis.homeTest.locale}};export function usePathname(){return '/ko'};export function useSearchParams(){return new URLSearchParams()}`),
  'next-intl/server': moduleUrl(`export function setRequestLocale(){};export async function getTranslations(namespace){const t=key=>{let v=globalThis.homeTest.messages[namespace];for(const k of key.split('.'))v=v[k];return v};t.raw=t;return t}`),
  'next-intl': moduleUrl(`export function useTranslations(namespace){return (key,args={})=>{let v=globalThis.homeTest.messages[namespace];for(const k of key.split('.'))v=v[k];return typeof v==='string'?v.replace(/\\{(\\w+)\\}/g,(_,k)=>String(args[k])):key}};export function useLocale(){return globalThis.homeTest.locale}`),
  'next/image': moduleUrl(`import React from 'react';export default function Image({src,alt,unoptimized,...p}){return React.createElement('img',{src,alt,...p})}`),
  '@/i18n/navigation': link,
  '@/i18n/routing': moduleUrl(`export const routing={locales:['ko','ja']}`),
  '@/app/lib/supabase': moduleUrl(`const query={select(...a){globalThis.homeTest.queries.push(['select',...a]);return this},eq(...a){globalThis.homeTest.queries.push(['eq',...a]);return this},order(...a){globalThis.homeTest.queries.push(['order',...a]);return this},then(done){return Promise.resolve({data:globalThis.homeTest.rows,error:null,count:globalThis.homeTest.rows.length}).then(done)}};export const supabase={from(name){if(name!=='curations')throw Error('unexpected_table');globalThis.homeTest.queries.push(['from',name]);return query},async rpc(name,args){globalThis.homeTest.rpcCalls.push({name,args});if(name==='public_home_featured_pins'){if(globalThis.homeTest.pinFailure)throw Error('synthetic_read_failure');return {data:globalThis.homeTest.pins??[],error:null}}if(name!=='public_home_card_colors')throw Error('write_or_analysis_forbidden');if(args.p_ids.length>6)throw Error('color_bound');return {data:args.p_ids.map(id=>({id,ready:true,tone:'purple',manual:true})),error:null}}}`),
};
registerHooks({
  resolve(specifier, context, next) {
    if (mocks[specifier]) return { url: mocks[specifier], shortCircuit: true };
    if (/PublicNavigationLink$/.test(specifier)) return { url: link, shortCircuit: true };
    if (specifier.endsWith('.module.css')) return { url: moduleUrl('export default new Proxy({}, {get:(_,k)=>String(k)})'), shortCircuit: true };
    const file = specifier.startsWith('@/') ? path.join(root, specifier.slice(2))
      : specifier.startsWith('.') && context.parentURL?.startsWith('file:') ? new URL(specifier, context.parentURL) : null;
    if (file) {
      const value = typeof file === 'string' ? file : decodeURIComponent(file.pathname).replace(/^\/(\w:)/, '$1');
      for (const suffix of ['', '.ts', '.tsx']) if (fs.existsSync(value + suffix) && fs.statSync(value + suffix).isFile()) return { url: pathToFileURL(value + suffix).href, shortCircuit: true };
    }
    return next(specifier, context.parentURL?.startsWith('data:') ? { ...context, parentURL: import.meta.url } : context);
  },
  load(url, context, next) {
    if (/\.tsx?$/.test(url)) return { format: 'module', source: ts.transpileModule(fs.readFileSync(new URL(url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText, shortCircuit: true };
    return next(url, context);
  },
});
const { selectHomeContent: select, homeWeek, homeLimits } = await import('../app/lib/homeSelection.ts');
const { isSeoulCulture, weeklyOutings } = await import('../app/lib/homeEditions.ts');
const { emptyContentFilters } = await import('../app/lib/contentFilters.ts');
const { localizeCuration } = await import('../app/lib/curations.ts');
const { default: Home } = await import('../app/[locale]/page.tsx');
const now = Date.parse('2026-10-24T12:00:00+09:00');
const known = value => ({ status: 'known', value }), endpoint = (value, precision = 'day') => ({ value, precision });
const idList = rows => rows.map(row => row.id);
let passed = 0;
async function test(name, run) { await run(); passed++; console.log('PASS', name); }
function row(id, category = 'program', patch = {}) {
  const metadata = emptyContentFilters(category);
  if (category === 'program' || category === 'event') metadata.location = known({scope:'specific', venues:[{province:'11',district:null,facility:'',address:''}]});
  if (category === 'program') Object.assign(metadata, { topic: known('culture_experience'), application: known({ deadlineKind: 'fixed', start: endpoint('2026-10-01'), end: endpoint('2026-11-01'), sourceStatus: 'open' }) });
  if (category === 'event') Object.assign(metadata, { topic: known('culture_arts'), schedule: known({ kind: 'continuous', recurrence: null, occurrences: [{ start: endpoint('2026-10-25'), end: endpoint('2026-10-25') }] }) });
  return { id, slug: id, title: id, summary: '合成 요약', content: 'PRIVATE_BODY', category: '', userCategory: category,
    source: 'PRIVATE_SOURCE', source_item_id: 'PRIVATE_ID', source_url: null, source_image_url: null,
    created_at: '2026-10-20T00:00:00Z', updated_at: '', application_deadline_kind: null, application_deadline_on: null,
    event_start_on: null, event_end_on: null, contentFilters: metadata, ...patch };
}
function app(id, value, patch = {}) {
  const item = row(id, 'program', patch); item.contentFilters.application = known({ ...item.contentFilters.application.value, ...value }); return item;
}
function event(id, pairs, patch = {}) {
  const item = row(id, 'event', patch);
  item.contentFilters.schedule = known({ kind: pairs.length === 1 ? 'continuous' : 'occurrences', recurrence: null,
    occurrences: pairs.map(([start, end, precision = 'day']) => ({ start: endpoint(start, precision), end: endpoint(end, precision) })) });
  return item;
}
await test('closed newest program never crowds out open older items', () => {
  const closed = app('closed', { sourceStatus: 'closed' }, { created_at: '2026-10-24T00:00:00Z' });
  assert.deepEqual(idList(select([closed, row('open')], now).featured), ['open']);
});
await test('expired dates, future starts and unknown source status remain excluded', () => {
  const items = [app('expired', { end: endpoint('2026-10-23') }), app('future', { start: endpoint('2026-10-25') }),
    app('unknown', { sourceStatus: 'unknown' }), app('before', { sourceStatus: 'not_started', start: endpoint('2026-10-25') })];
  assert.deepEqual(select(items, now).featured, []);
  assert.equal(select([app('opened', { sourceStatus: 'not_started', start: endpoint('2026-10-24') })], now).featured.length, 1);
});
await test('explicit rolling open differs from a missing deadline or legacy unknown', () => {
  assert.deepEqual(idList(select([app('rolling', { deadlineKind: 'none', end: null }),
    row('legacy-none', 'program', { contentFilters: null, application_deadline_kind: 'none' }),
    row('legacy-fixed', 'program', { contentFilters: null, application_deadline_kind: 'fixed', application_deadline_on: '2026-11-01' })], now).featured), ['rolling']);
  assert.equal(select([app('rolling-closed', { deadlineKind: 'none', end: null, sourceStatus: 'closed' })], now).featured.length, 0);
});
await test('representatives preserve actual 0/1/2 counts, cap at six and never fill with closed rows', () => {
  assert.equal(homeLimits.featured, 6);
  for (const n of [0, 1, 2, 4, 6, 9]) {
    const items = Array.from({ length: n }, (_, i) => row(String(i)));
    assert.equal(select(items, now).featured.length, Math.min(n, 6));
  }
});
await test('latest publication then stable ID orders both languages identically', () => {
  const a = row('a'), b = row('b'), c = row('c', 'program', { created_at: '2026-10-21T00:00:00Z' });
  assert.deepEqual(idList(select([b, a, c], now).featured), ['c', 'a', 'b']);
  assert.deepEqual(idList(select([{ ...b, title: 'ア' }, { ...c, title: 'ウ' }, { ...a, title: 'イ' }], now).featured), ['c', 'a', 'b']);
});
await test('selection is immutable, unique by public ID/slug, with intentional cross-section repetition', () => {
  const a = row('a'), duplicateLink = row('b', 'program', { slug: 'a' }), before = JSON.stringify([a, duplicateLink]);
  const result = select(Object.freeze([Object.freeze(a), Object.freeze(a), Object.freeze(duplicateLink)]), now);
  assert.equal(result.featured.length, 1); assert.equal(result.sections.experiences[0].id, result.featured[0].id);
  assert.equal(JSON.stringify([a, duplicateLink]), before);
});
await test('living selects two latest public guides, not updates, deadlines or program pins', () => {
  const old = row('old-guide', 'living', {contentFilters:null,created_at:'2026-10-01T00:00:00Z',updated_at:'2027-01-01T00:00:00Z'});
  const a = row('a-guide', 'living', {contentFilters:null,created_at:'2026-10-23T00:00:00Z'});
  const b = row('b-guide', 'living', {contentFilters:null,created_at:'2026-10-23T00:00:00Z',application_deadline_kind:'closed'});
  const inputs = Object.freeze([old,b,a,row('program'),{...a}]);
  const before=JSON.stringify(inputs);
  const result=select(inputs,now,[{id:old.id,position:1}]);
  assert.equal(homeLimits.living,2);
  assert.deepEqual(idList(result.sections.living),['a-guide','b-guide']);
  assert.deepEqual(idList(result.featured),['program']);
  assert.equal(JSON.stringify(inputs),before);
  assert.deepEqual(idList(select(inputs.map(x=>({...x,title:'日本語 '+x.title})),now).sections.living),['a-guide','b-guide']);
});
await test('living preserves zero or one guide and never fills a missing guide with another category', () => {
  assert.deepEqual(select([row('program')],now).sections.living,[]);
  const guide=row('only-guide','living',{contentFilters:null});
  assert.deepEqual(idList(select([row('program'),guide],now).sections.living),['only-guide']);
});
await test('KST Monday-Sunday week respects UTC, year and next-week boundaries', () => {
  const week = homeWeek(Date.parse('2026-10-25T14:59:59.999Z'));
  assert.equal(new Date(week.start).toISOString(), '2026-10-18T15:00:00.000Z');
  assert.equal(new Date(week.end).toISOString(), '2026-10-25T15:00:00.000Z');
  assert.equal(homeWeek(Date.parse('2026-10-25T15:00:00Z')).start, week.end);
  assert.equal(new Date(homeWeek(Date.parse('2027-01-01T00:00:00+09:00')).start).toISOString(), '2026-12-27T15:00:00.000Z');
  assert.throws(() => select([], NaN));
});
await test('deadline section uses this KST week and earliest exact remaining cutoff, not event time', () => {
  const sunday = app('sunday', { end: endpoint('2026-10-25') });
  const soon = app('soon', { end: endpoint('2026-10-24T13:00:00+09:00', 'minute') });
  const nextWeek = app('next-week', { end: endpoint('2026-10-26T00:00:00+09:00', 'second') });
  const expired = app('expired', { end: endpoint('2026-10-24T11:00:00+09:00', 'minute') });
  assert.deepEqual(idList(select([nextWeek, sunday, expired, soon, row('event', 'event')], now).sections.deadline), ['soon']);
  assert.deepEqual(idList(select([sunday, nextWeek], now).sections.deadline), ['sunday']);
  assert.deepEqual(select([nextWeek], now).sections.deadline, []);
  assert.equal(select([sunday], Date.parse('2026-10-25T23:59:59.999+09:00')).sections.deadline.length, 1);
  assert.equal(select([sunday], Date.parse('2026-10-26T00:00:00+09:00')).featured.length, 0);
});
await test('day and precise application endpoints retain the shared closure semantics', () => {
  const minute = app('minute', { end: endpoint('2026-10-24T12:00:00+09:00', 'minute') });
  assert.equal(select([minute], now).featured.length, 1);
  assert.equal(select([minute], now + 1).featured.length, 0);
});
await test('experience and all three approved learning topics use stored metadata, never title keywords', () => {
  const items = ['culture_experience', 'language_learning', 'employment_career', 'daily_safety', 'community_exchange', 'other'].map((topic, i) => {
    const item = row(String(i)); item.contentFilters.topic = known(topic); return item;
  });
  assert.deepEqual(idList(select(items, now).sections.experiences), ['0']);
  assert.deepEqual(idList(select(items, now).sections.learning), ['1', '2']);
  assert.deepEqual(idList(select([items[3]], now).sections.learning), ['3']);
  const unknown = row('keyword', 'program', { title: '한국어 컴퓨터 문화 체험 축제' }); unknown.contentFilters.topic = { status: 'unknown', value: null };
  assert.deepEqual(select([unknown], now).sections.experiences, []); assert.deepEqual(select([unknown], now).sections.learning, []);
});
await test('events use occurrence dates, ongoing first then nearest upcoming, independent of application deadlines', () => {
  const ended = event('ended', [['2026-10-23', '2026-10-23']]);
  const next = event('next', [['2026-10-25', '2026-10-25']]);
  const later = event('later', [['2026-11-14', '2026-11-14']]);
  const active = event('active', [['2026-10-24T11:00:00+09:00', '2026-10-24T13:00:00+09:00', 'minute']], { application_deadline_kind: 'closed' });
  const unknown = row('unknown-event', 'event', { contentFilters: null, event_start_on: null });
  assert.deepEqual(idList(select([ended, next, later, active, unknown], now).sections.events), ['active']);
  assert.deepEqual(idList(select([later, next], now).sections.events), ['next']);
  assert(!idList(select([ended, active], now).featured).includes('ended'));
});
await test('multi-session events retain next actual occurrence and finished sessions do not imply the entire event ended', () => {
  const multi = event('multi', [['2026-10-20', '2026-10-20'], ['2026-10-25', '2026-10-25']]);
  assert.deepEqual(idList(select([multi], now).sections.events), ['multi']);
  assert.equal(select([multi], Date.parse('2026-10-26T00:00:00+09:00')).featured.length, 0);
});
await test('missing/malformed metadata is not a guessed topic or an open state; only valid legacy event dates can fall back', () => {
  assert.deepEqual(select([row('bad', 'program', { contentFilters: { schema: 'bad' } })], now).featured, []);
  assert.deepEqual(idList(select([row('legacy', 'event', { contentFilters: null, event_start_on: '2026-10-25', event_end_on: '2026-10-26' })], now).featured), ['legacy']);
  assert.deepEqual(select([row('backwards', 'event', { contentFilters: null, event_start_on: '2026-10-26', event_end_on: '2026-10-25' })], now).featured, []);
});

const raw = item => ({ ...item, user_category: item.userCategory, content_filters: item.contentFilters,
  title_ko: '한국어 ' + item.title, summary_ko: '한국어 ' + item.summary, content_ko: item.content,
  title_ja: '日本語 ' + item.title, summary_ja: '日本語 ' + item.summary, content_ja: item.content });
async function route(rows, locale, time) {
  queries.length = 0; rpcCalls.length = 0;
  Object.assign(globalThis.homeTest, { rows, locale, messages: JSON.parse(fs.readFileSync(path.join(root, 'messages', locale + '.json'), 'utf8')) });
  const Clock = Date;
  globalThis.Date = class extends Clock {
    constructor(...args) { super(...(args.length ? args : [time])); }
    static now() { return time; }
  };
  try {
    const outer = await Home({ params: Promise.resolve({ locale }) });
    return await outer.props.children.type(outer.props.children.props);
  } finally { globalThis.Date = Clock; }
}
await test('actual route localizes public sections, bounds one color read and leaks no private payload', async () => {
  const culture = app('culture', { end: endpoint('2026-10-25') });
  const learn = row('learn'); learn.contentFilters.topic = known('daily_safety');
  const events = row('event', 'event');
  const closed = app('closed', { sourceStatus: 'closed' }, { created_at: '2026-10-24T00:00:00Z' });
  const incomplete = { ...raw(row('incomplete')), content_ja: ' ' };
  const data = [culture, learn, events, closed].map(raw).concat(incomplete);
  for (const locale of ['ko', 'ja']) {
    const result = await route(data, locale, now);
    assert.deepEqual(idList(result.props.items), ['culture', 'event']);
    assert.deepEqual(Object.fromEntries(Object.entries(result.props.sections).map(([key, rows]) => [key, idList(rows)])), { living: [], learning: ['learn'] });
    assert.equal(result.props.items[0].period, locale === 'ko' ? '접수 마감 D-1' : '申込締切まであと1日');
    assert(!JSON.stringify(result.props).includes('PRIVATE_'));
    assert(queries.some(x => x[0] === 'eq' && x[1] === 'is_published' && x[2] === true));
    assert.equal(queries.filter(x => x[0] === 'from').length, 1);
    assert.equal(rpcCalls.filter(x=>x.name==='public_home_featured_pins').length,1); assert.equal(rpcCalls.filter(x=>x.name==='public_home_card_colors')[0].args.p_ids.length,2);
    assert(result.props.items.every(x => x.tone === 'purple' && x.toneManual));
    const html = renderToStaticMarkup(result);
    for (const label of [locale === 'ko' ? '생활 안내' : '暮らしのガイド', 'culture', 'learn', 'event']) assert(html.includes(label));
    assert(!html.includes('home-deadline-title'));
    assert(html.includes('href="/feedback"')); assert(html.includes('topic=daily_safety')); assert(html.includes('data-tone="purple"'));
  }
});
await test('ko/ja route updates latest living guides through the existing public fetch and bilingual gate', async () => {
  const guide=(id,date,patch={})=>raw(row(id,'living',{contentFilters:null,created_at:date,...patch}));
  const old=guide('guide-old','2026-10-01T00:00:00Z',{updated_at:'2027-01-01T00:00:00Z'});
  const newer=guide('guide-new','2026-10-23T00:00:00Z');
  const newest=guide('guide-newest','2026-10-24T00:00:00Z');
  const incomplete={...guide('guide-incomplete','2026-10-25T00:00:00Z'),summary_ja:' '};
  for(const locale of ['ko','ja']) {
    for(const [data,expected] of [[[],[]],[[old],['guide-old']],[[old,newer,incomplete],['guide-new','guide-old']],[[old,newest,newer,incomplete],['guide-newest','guide-new']]]) {
      const result=await route(data,locale,now);
      assert.deepEqual(idList(result.props.sections.living),expected);
      assert.equal(result.props.items.length,0);
      assert(result.props.sections.living.every(x=>x.period===null));
      assert.equal(queries.filter(x=>x[0]==='from').length,1);
      assert(queries.some(x=>x[0]==='eq'&&x[1]==='is_published'&&x[2]===true));
      assert.equal(rpcCalls.filter(x=>x.name==='public_home_card_colors').length,0);
      const html=renderToStaticMarkup(result);
      assert.equal((html.match(/class="contentCard livingCard/g)||[]).length,expected.length);
      assert(html.includes('href="/info/category/living"'));
      assert(html.includes(locale==='ko'?'생활 더 보기':'暮らしのガイド一覧'));
      assert(!html.includes('guide-incomplete')&&!html.includes('PRIVATE_')&&!html.includes('최신 게시순'));
      if(!expected.length)assert(html.includes(locale==='ko'?'아직 등록된 생활 안내가 없어요.':'暮らしのガイドはまだありません。'));
    }
  }
});
await test('actual route preserves empty/one/two/six carousel states and no writes or analysis', async () => {
  for (const locale of ['ko', 'ja']) for (const count of [0, 1, 2, 6, 9]) {
    const result = await route(Array.from({ length: count }, (_, i) => raw(row(String(i)))), locale, now);
    assert.equal(result.props.items.length, Math.min(count, 6));
    assert.equal(rpcCalls.filter(x=>x.name==='public_home_card_colors').length,count?1:0); assert.equal(rpcCalls.filter(x=>x.name==='public_home_featured_pins').length,1);
    const html = renderToStaticMarkup(result);
    assert.equal((html.match(/data-dot=/g) || []).length, count > 1 ? Math.min(count, 6) : 0);
    assert.equal((html.match(/aria-haspopup="dialog"/g) || []).length, count > 1 ? 1 : 0);
    assert(!html.includes('PRIVATE_'));
  }
});

await test('weekly uses public sessions, not applications; KST week boundaries and separate sessions', () => {
  const thursday = Date.parse('2026-11-26T09:00:00+09:00');
  const exhibition = event('exhibition', [['2026-11-24','2026-12-06']]);
  const tour = event('tour', [['2026-11-21','2026-11-21'],['2026-11-28','2026-11-28']]);
  const docent = event('docent', [['2026-12-03','2026-12-03']]);
  const missing = row('unknown', 'event', {contentFilters:null});
  const stale = [row('application'), missing, docent];
  const week = (rows,time=thursday) => weeklyOutings(rows,time,'ja').items;
  assert.deepEqual(week(stale),[]);
  assert.deepEqual(week([...stale,exhibition]).map(x=>x.date),['24–29']);
  assert.deepEqual(week([...stale,tour,exhibition]).map(x=>x.slug),['exhibition','tour']);
  assert.equal(week([tour],Date.parse('2026-11-29T00:00:00+09:00')).length,0);
  assert.equal(week([docent],Date.parse('2026-11-29T23:59:59+09:00')).length,0);
  assert.equal(week([docent],Date.parse('2026-11-30T00:00:00+09:00')).length,1);
});
await test('published programs join the weekly events only while a confirmed session can be attended', async () => {
  const time=Date.parse('2026-11-26T09:00:00+09:00');
  const entry=(date)=>({officialBooking:true,start:endpoint(date+'T11:00:00+09:00','minute'),end:endpoint(date+'T13:00:00+09:00','minute')});
  const program=app('session',{start:endpoint('2026-11-23'),end:endpoint('2026-11-29')});
  const booked = entry('2026-11-28');
  program.programOuting={sessions:[{...booked,officialBooking:false}]};
  const rowsAt=(rows,t=time)=>weeklyOutings(rows,t,'ko').items;
  const eventOnly=event('event',[['2026-11-27','2026-11-27']]);
  for(const locale of ['ko','ja']){
    const run=async(items)=>(await route(items.map(item=>({...raw(item),program_outing:item.programOuting})),locale,time)).props.weekly.items;
    assert.deepEqual((await run([eventOnly])).map(x=>x.slug),['event']);
    const both=await run([eventOnly,program]);assert.deepEqual(both.map(x=>x.slug),['event','session']);
    assert.equal(both[1].summary,'');
    for(const officialBooking of [true,undefined,null,'false']) {
      const restricted={...program,programOuting:{sessions:[{...booked,officialBooking}]}};
      assert.deepEqual((await run([restricted,eventOnly])).map(x=>x.slug),['event']);
      assert.equal(isSeoulCulture(restricted),true);
    }
    assert.equal(both[0].summary,(await run([eventOnly]))[0].summary);
  }
  assert.deepEqual(rowsAt([row('deadline'),{...program,programOuting:{sessions:[entry('2026-12-03')]}}]),[]);
  assert.deepEqual(rowsAt([program],Date.parse('2026-11-28T13:01:00+09:00')),[]);
  for(const appPatch of [{sourceStatus:'closed'},{end:endpoint('2026-11-25')},{start:null}]){
    assert.deepEqual(rowsAt([app('closed',appPatch,{programOuting:{sessions:[booked]}})]),[]);
  }
  assert.deepEqual(rowsAt([program,program,{...program,id:'alias'},eventOnly]).map(x=>x.slug),['event','session']);
});
await test('walk-in exhibition uses its open days, independent of booked commentary and its deadline', () => {
  const time=Date.parse('2026-11-26T09:00:00+09:00'), end=Date.parse('2026-11-29T23:59:59+09:00');
  const viewing={subject:'exhibition',from:'2026-11-24',through:'2026-12-06',weekdays:[0,2,3,4,5,6],exceptions:['2026-11-26','2026-11-27'],reservationNotRequired:true};
  const guide={officialBooking:true,start:endpoint('2026-12-03'),end:endpoint('2026-12-03')};
  const show=(value,t,locale='ko')=>weeklyOutings([row('lake','program',{programOuting:{viewing:value,sessions:[guide,{...guide,start:endpoint('2026-12-05'),end:endpoint('2026-12-05')}]},application_deadline_kind:'closed'})],t,locale).items;
  for(const locale of ['ko','ja']){
    const [visit]=show(viewing,time,locale);assert.equal(visit.date,'28–29');assert.equal(visit.summary,locale==='ja'?'展示の一般観覧':'전시 일반 관람');
    assert.doesNotMatch(visit.summary,/작가|解説|잔여석/);
  }
  for(const [locale,titles,label] of [
    ['ko',['작가 해설 사전예약','공예 체험 예약','미술 수업 신청'],'전시 일반 관람'],
    ['ja',['作家による解説の予約','工芸体験の予約','美術講座の申込'],'展示の一般観覧']
  ]){
    for(const title of [...titles,label,"〈Lake〉 "+label]){
      const early={...guide,start:endpoint('2026-11-26'),end:endpoint('2026-11-26')};
      const mixed=row('mixed','program',{title,programOuting:{viewing,sessions:[early,guide]}});
      const [result]=weeklyOutings([mixed,mixed],time,locale).items;
      assert.deepEqual([result.date,result.title,result.summary],['28–29',titles.includes(title)?label:title,titles.includes(title)?(locale==='ko'?'글 제목 · ':'記事名：')+title:'']);
    }
  }
  const custom={...viewing,subject:'other',labelKo:'Garden 공개 관람',labelJa:'Gardenの一般見学'};
  assert.equal(show(custom,time,'ja')[0].summary,'Gardenの一般見学');
  assert.equal(show(viewing,end)[0].date,'29');
  assert.equal(show(viewing,end+1000)[0].date,'1–6');
  assert.deepEqual(show({...viewing,exceptions:[...viewing.exceptions,'2026-11-28','2026-11-29']},time),[]);
  assert.deepEqual(show({...viewing,reservationNotRequired:false},time),[]);
  assert.deepEqual(show(null,time),[]);
});
await test('viewing cards show only remaining open dates and retain the original linked article', () => {
  const at = date => Date.parse(date + 'T12:00:00+09:00');
  for (const locale of ['ko','ja']) {
    const ja = locale === 'ja';
    const activity = ja ? '展示の一般観覧' : '전시 일반 관람';
    const work = ja ? '〈流れる湖のように〉' : '〈흐르는 호수처럼〉';
    const booking = {start:endpoint('2026-12-03'),end:endpoint('2026-12-03'),officialBooking:true};
    const card = (title, today, overrides={}) => {
      const viewing = {subject:'exhibition',from:'2026-11-24',through:'2026-12-02',
        weekdays:[0,1,2,3,4,5,6],exceptions:[],reservationNotRequired:true,...overrides};
      return weeklyOutings([row('gallery','program',{title,programOuting:{viewing,sessions:[booking]}})],at(today),locale).items[0];
    };
    const clear = card(work,'2026-11-26');
    assert.deepEqual([clear.title,clear.summary,clear.date,clear.details],[work,activity,'26–29','']);
    const named = work + ' ' + activity;
    assert.deepEqual([card(named,'2026-11-26').title,card(named,'2026-11-26').summary],[named,'']);
    const mixed = ja ? '作家の解説と工芸体験の予約' : '작가 해설 및 공예 체험 예약';
    const split = card(mixed,'2026-11-26',{exceptions:['2026-11-27']});
    assert.deepEqual([split.slug,split.title,split.summary,split.details],
      ['gallery',activity,(ja?'記事名：':'글 제목 · ')+mixed,ja?'26日、28〜29日':'26일, 28–29일']);
    assert.equal(card(mixed,'2026-11-26',{weekdays:[4,6,0]}).details,split.details);
    const single=card(work,'2026-11-26',{weekdays:[6]});
    assert.deepEqual([single.date,single.dayLabel],['28',ja?'土曜日':'토요일']);
    const crossMonth=card(work,'2026-11-30');
    assert.equal(crossMonth.details,ja?'11月30日〜12月2日':'11월 30일–12월 2일');
    assert.equal(card(work,'2026-11-30',{exceptions:['2026-12-01']}).details,ja?'11月30日、12月2日':'11월 30일, 12월 2일');
    assert.equal(card(work,'2026-11-29').date,'29');
  }
});
await test('the preserved docent article titles lead with verified general viewing even without session data', async () => {
  const viewing = {subject:'exhibition', reservationNotRequired:true, from:'2026-11-24', through:'2026-12-06',
    weekdays:[0,2,3,4,5,6], exceptions:[]};
  const article = {...raw(row('seoul-8a74492370eb51fff86f81e2c0282418')), title_ko:'2026 더 임팩트 청년예술인 공모전시 [흐르는 호수처럼] 미술전시해설 도슨트 프로그램', title_ja:'2026 ザ・インパクト 若手芸術家公募展［流れる湖のように］美術展解説ドーセントプログラム', program_outing:{viewing}};
  const now = Date.parse('2026-11-26T18:00:00+09:00');
  const cards = [];
  for (const locale of ['ko','ja']) {
    const home = await route([article],locale,now);
    const {items} = home.props.weekly;
    assert.equal(items.length,1);
    const {slug,title,summary,date} = items[0];
    assert.equal(slug,article.slug);
    assert.equal(date,'26–29');
    cards.push([title,summary]);
    const workTitle = locale === 'ko' ? '〈흐르는 호수처럼〉' : '〈流れる湖のように〉';
    const simple = await route([{...article,['title_'+locale]:workTitle}],locale,now);
    assert.equal(simple.props.weekly.items[0].title,workTitle);
    const noViewing = await route([{...article,program_outing:{}}],locale,now);
    assert.equal(noViewing.props.weekly.items.length,0);
  }
  assert.deepEqual(cards,[
    ['전시 일반 관람','글 제목 · ' + article.title_ko],
    ['展示の一般観覧','記事名：' + article.title_ja]
  ]);
});
await test('settlement links follow stable public slugs and omit missing translations', async () => {
  const slugs = ['living-458e3b16-fa16-4d00-a6e9-b0beb143d41b','living-d24cd543-e5d6-4de9-a26c-09a0f9b1ec6b','living-1b47f436-f08f-4584-948a-d08fccb2a088'];
  const guides = slugs.map(slug=>raw(row(slug,'living',{contentFilters:null})));
  const ja = await route([...guides].reverse(),'ja',now);
  assert.deepEqual(ja.props.settlement.map(x=>x.slug),slugs);
  assert.deepEqual(ja.props.settlement.map(x=>x.label),['空港からの移動','スマホの通信','外国人登録']);
  const partial = await route([guides[0],{...guides[1],content_ja:''}],'ja',now);
  assert.deepEqual(partial.props.settlement.map(x=>x.slug),[slugs[0]]);
  const empty = await route([],'ja',now);
  assert.equal(empty.props.settlement.length,0);
  assert.equal((renderToStaticMarkup(empty).match(/href="\/info\/category\/living"/g)||[]).length,2);
  assert.equal((await route(guides,'ko',now)).props.settlement.length,0);
});
await test('Seoul cultural selection admits confirmed foreigner programs and excludes other regions', async () => {
  const seoul = row('seoul');seoul.contentFilters.foreignerProgram=known('foreigner');
  const other = row('other');other.contentFilters.location.value.venues[0].province='41';
  for (const locale of ['ko','ja']) {
    const {props} = await route([raw(other),raw(seoul)],locale,now);
    assert.deepEqual(idList(props.items),['seoul']);
  }
});
const snapshotArg = process.argv.indexOf('--snapshot');
await test('pins lead the same six-item selection, preserve lower sections and skip expired/missing pins',()=>{
 const rows=Array.from({length:9},(_,i)=>row(String(i)));const original=JSON.stringify(rows),automatic=select(rows,now);
 const pins=[{id:'8',position:2},{id:'7',position:1}];const chosen=select(rows,now,pins);
 assert.deepEqual(idList(chosen.featured),['7','8','0','1','2','3']);assert.deepEqual(chosen.sections,automatic.sections);assert.equal(JSON.stringify(rows),original);
 assert.deepEqual(idList(select(rows,now,[{id:'missing',position:1}]).featured),idList(automatic.featured));
 const closed=app('closed',{sourceStatus:'closed'});assert(!idList(select([...rows,closed],now,[{id:'closed',position:1}]).featured).includes('closed'));
 for(const invalid of [[...pins,{id:'6',position:1}],[pins[0],pins[0]],[{id:'7',position:3}]])assert.deepEqual(idList(select(rows,now,invalid).featured),idList(automatic.featured));
 assert.equal(select([],now,pins).featured.length,0);assert.equal(select([row('7')],now,pins).featured.length,1);
});
await test('optional legacy foreigner metadata never changes existing home eligibility or pin priority',()=>{
 const legacy=row('legacy-open');delete legacy.contentFilters.foreignerProgram;
 assert.deepEqual(idList(select([row('auto'),legacy],now,[{id:legacy.id,position:1}]).featured),['legacy-open','auto']);
 legacy.contentFilters.application.value.sourceStatus='closed';assert.deepEqual(idList(select([legacy],now,[{id:legacy.id,position:1}]).featured),[]);
 legacy.contentFilters.application.value.sourceStatus='unknown';assert.deepEqual(select([legacy],now).featured,[]);
});
await test('actual ko/ja page reads public pins once, orders both languages identically, falls back safely',async()=>{
 const ids=Array.from({length:8},(_,i)=>'30000000-0000-4000-8000-'+String(i+1).padStart(12,'0'));
 const data=ids.map(x=>raw(row(x)));globalThis.homeTest.pins=[{id:ids[7],position:1},{id:ids[6],position:2}];
 for(const locale of ['ko','ja']){const result=await route(data,locale,now);assert.deepEqual(idList(result.props.items),[ids[7],ids[6],...ids.slice(0,4)]);assert.equal(rpcCalls.filter(x=>x.name==='public_home_featured_pins').length,1);assert(!JSON.stringify(result.props).includes('stateVersion'));}
 globalThis.homeTest.pinFailure=true;assert.deepEqual(idList((await route(data,'ko',now)).props.items),ids.slice(0,6));globalThis.homeTest.pinFailure=false;
 const {readHomePins}=await import('../app/lib/home-featured/public-read.ts');
 for(const bad of [[{id:ids[0],position:1,actor:'PRIVATE'}],[{id:'bad',position:1}],Array(3).fill({id:ids[0],position:1}),[{id:ids[0],position:1},{id:ids[0],position:2}]])assert.deepEqual(await readHomePins({rpc:async()=>({data:bad,error:null})}),[]);
 assert.deepEqual(await readHomePins({rpc:async()=>({data:null,error:{message:'PRIVATE'}})}),[]);globalThis.homeTest.pins=[];
});
if (snapshotArg >= 0) await test('preserved actual public projection flows through the same route in both languages, with body text omitted', async () => {
  const snapshot = JSON.parse(fs.readFileSync(process.argv[snapshotArg + 1], 'utf8'));
  assert.equal(snapshot.rows.length, snapshot.count);
  // Body completeness was checked by the read-only projection. Text placeholders
  // are explicitly synthetic; no actual body is obtained, inferred or displayed.
  const rows = snapshot.rows.map(item => ({ ...item, content_ko: item.complete_bilingual ? '본문 전문 조회 제외 · 합성 자리표시자' : '', content_ja: item.complete_bilingual ? '本文取得なし・合成プレースホルダー' : '' }));
  const time = Date.parse(snapshot.asOf);
  const outputs = [];
  for (const locale of ['ko', 'ja']) {
    const result = await route(rows, locale, time);
    const selection = select(rows.map(x => localizeCuration(x, locale)).filter(Boolean), time, [], isSeoulCulture);
    assert.deepEqual(idList(result.props.items), idList(selection.featured));
    for (const key of Object.keys(result.props.sections)) assert.deepEqual(idList(result.props.sections[key]), idList(selection.sections[key]));
    outputs.push(result.props);
  }
  assert.deepEqual(idList(outputs[0].items), idList(outputs[1].items));
  const brief = props => ({ featured: props.items.map(x => x.title), sections: Object.fromEntries(Object.entries(props.sections).map(([k, rows]) => [k, rows.map(x => x.title)])) });
  console.log(JSON.stringify({ snapshotAsOf: snapshot.asOf, publicCount: snapshot.count, actualSelection: brief(outputs[0]), colorRPC: 'fake saved palette projection; no image fetch or reanalysis' }));
});
console.log(JSON.stringify({ passed, operationalReadsInTest: 0, externalNetwork: 0, realAI: 0, writes: 0 }));
