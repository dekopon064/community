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
await test('actual route localizes published rows, fills four sections, bounds one color read and leaks no private payload', async () => {
  const culture = app('culture', { end: endpoint('2026-10-25') });
  const learn = row('learn'); learn.contentFilters.topic = known('daily_safety');
  const events = row('event', 'event');
  const closed = app('closed', { sourceStatus: 'closed' }, { created_at: '2026-10-24T00:00:00Z' });
  const incomplete = { ...raw(row('incomplete')), content_ja: ' ' };
  const data = [culture, learn, events, closed].map(raw).concat(incomplete);
  for (const locale of ['ko', 'ja']) {
    const result = await route(data, locale, now);
    assert.deepEqual(idList(result.props.items), ['culture', 'event', 'learn']);
    assert.deepEqual(Object.fromEntries(Object.entries(result.props.sections).map(([key, rows]) => [key, idList(rows)])), { deadline: ['culture'], experiences: ['culture'], learning: ['learn'], events: ['event'] });
    assert.equal(result.props.sections.deadline[0].period, locale === 'ko' ? '접수 마감 D-1' : '申込締切まであと1日');
    assert(!JSON.stringify(result.props).includes('PRIVATE_'));
    assert(queries.some(x => x[0] === 'eq' && x[1] === 'is_published' && x[2] === true));
    assert.equal(queries.filter(x => x[0] === 'from').length, 1);
    assert.equal(rpcCalls.filter(x=>x.name==='public_home_featured_pins').length,1); assert.equal(rpcCalls.filter(x=>x.name==='public_home_card_colors')[0].args.p_ids.length,3);
    assert(result.props.items.every(x => x.tone === 'purple' && x.toneManual));
    const html = renderToStaticMarkup(result);
    for (const label of [locale === 'ko' ? '이번 주 신청 마감' : '今週、申込締切の情報', 'culture', 'learn', 'event']) assert(html.includes(label));
    assert(html.includes('href="/feedback"')); assert(html.includes('topic=daily_safety')); assert(html.includes('data-tone="purple"'));
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
    const selection = select(rows.map(x => localizeCuration(x, locale)).filter(Boolean), time);
    assert.deepEqual(idList(result.props.items), idList(selection.featured));
    for (const key of Object.keys(selection.sections)) assert.deepEqual(idList(result.props.sections[key]), idList(selection.sections[key]));
    outputs.push(result.props);
  }
  assert.deepEqual(idList(outputs[0].items), idList(outputs[1].items));
  const brief = props => ({ featured: props.items.map(x => x.title), sections: Object.fromEntries(Object.entries(props.sections).map(([k, rows]) => [k, rows.map(x => x.title)])) });
  console.log(JSON.stringify({ snapshotAsOf: snapshot.asOf, publicCount: snapshot.count, actualSelection: brief(outputs[0]), colorRPC: 'fake saved palette projection; no image fetch or reanalysis' }));
});
console.log(JSON.stringify({ passed, operationalReadsInTest: 0, externalNetwork: 0, realAI: 0, writes: 0 }));
