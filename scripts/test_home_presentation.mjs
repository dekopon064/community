import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { registerHooks } from 'node:module';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

globalThis.fetch = () => { throw Error('external_network_forbidden'); };
const root = path.resolve('.'), url = value => `data:text/javascript,${encodeURIComponent(value)}`;
const link = url(`import React from 'react'; export function Link({children,feedback,href,...props}){return React.createElement('a',{href,...props},children)} export default Link;`);
const mock = {
  'next-intl': url(`export function useTranslations(){return key=>key}`),
  'next/image': url(`import React from 'react';export default function Image({src,alt,unoptimized,...props}){return React.createElement('img',{src,alt,...props})}`),
};
registerHooks({
  resolve(specifier, context, next) {
    if (mock[specifier]) return { url: mock[specifier], shortCircuit: true };
    if (specifier === '@/i18n/navigation' || /PublicNavigationLink$/.test(specifier)) return { url: link, shortCircuit: true };
    if (specifier.endsWith('.module.css')) return { url: url('export default new Proxy({}, {get:(_,key)=>String(key)})'), shortCircuit: true };
    let file = specifier.startsWith('@/') ? path.join(root, specifier.slice(2)) : specifier.startsWith('.') && context.parentURL?.startsWith('file:') ? new URL(specifier, context.parentURL) : null;
    if (file) { file = typeof file === 'string' ? file : decodeURIComponent(file.pathname).replace(/^\/(\w:)/, '$1');
      for (const suffix of ['', '.ts', '.tsx']) if (fs.existsSync(file + suffix) && fs.statSync(file + suffix).isFile()) return { url: pathToFileURL(file + suffix).href, shortCircuit: true };
    }
    return next(specifier, context.parentURL?.startsWith('data:') ? { ...context, parentURL: pathToFileURL(path.join(root, 'scripts/mock.mjs')).href } : context);
  },
  load(file, context, next) {
    if (/\.tsx?$/.test(file)) return { format: 'module', source: ts.transpileModule(fs.readFileSync(new URL(file), 'utf8'), { compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText, shortCircuit: true };
    return next(file, context);
  },
});
const { homeItems, homeFinderHref, homeDistricts } = await import('../app/lib/homePresentation.ts');
const { homeCardPalette, homeCardColors } = await import('../app/lib/homeCardPalette.ts');
const { default: HomeExperience } = await import('../app/components/HomeExperience.tsx');
const { default: HomeContentCard } = await import('../app/components/HomeContentCard.tsx');
const { default: HomeFeaturedCarousel } = await import('../app/components/HomeFeaturedCarousel.tsx');
// Explicit operator choices override the image-less fallback; automatic tones do not.
for(const locale of ['ko','ja']) {
  const manual={id:'manual',slug:'manual',title:'합성 手動',summary:'합성',categoryLabel:'프로그램',period:null,imageUrl:null,tone:'red',toneManual:true};
  const html=renderToStaticMarkup(React.createElement(HomeContentCard,{item:manual,locale,featured:true}));
  assert(html.includes('data-tone="red"'));assert(html.includes('#F6E4EC'));assert(!html.includes('PRIVATE'));
}
const row = id => ({ id, slug: id, title: '긴 제목 · 日本語のタイトル', summary: '현재 공개된 요약', userCategory: 'program',
  source_image_url: null, application_deadline_kind: 'none', application_deadline_on: null, event_start_on: null, event_end_on: null,
  content: 'private body must not cross', source_item_id: 'private source identity', contentFilters: { private: true } });
let passed = 0;
function check(name, run) { run(); passed++; console.log(`PASS ${name}`); }
check('display projection preserves selected order, immutable input and minimal fields', () => {
  const rows = Object.freeze(['newest','second','third'].map(id => Object.freeze(row(id))));
  const items = homeItems(rows, 'ko', '2026-10-23', k => k);
  assert.deepEqual(items.map(x => x.id), ['newest','second','third']);
  assert(!JSON.stringify(items).includes('private')); assert.equal(items[0].period, '상시 모집');
  assert.equal(items[0].tone, undefined);
});
check('unknown dates stay unknown and closed content is not reclassified', () => {
  assert.equal(homeItems([{...row('a'), application_deadline_kind: null}], 'ko', '2026-10-23', k=>k)[0].period, null);
  assert.equal(homeItems([{...row('a'), application_deadline_kind: 'closed'}], 'ja', '2026-10-23', k=>k)[0].period, '受付終了');
});
check('finder keeps canonical list topic/province/district keys and blocks invented values', () => {
  const href = homeFinderHref('program', 'culture_experience', '11:강동구');
  const q = new URL(href, 'http://localhost').searchParams;
  assert.equal(q.get('topic'), 'culture_experience'); assert.equal(q.get('region'), '11'); assert.equal(q.get('district'), '11:강동구');
  assert.equal(homeFinderHref('event', 'language_learning', '99:가짜'), '/info/category/event');
  assert.equal(homeFinderHref('event', 'culture_arts', '28'), '/info/category/event?topic=culture_arts&region=28');
  assert.equal(new Set(homeDistricts('11','ja')).size, 25); assert.equal(homeDistricts('11','ko')[0], '강남구');
});
for (const locale of ['ko','ja']) for (const count of [0,1,2,4]) check(`${locale} ${count} cards: controls, unique peeks, overview and local destinations`, () => {
  const items = Array.from({length:count}, (_,i) => ({...homeItems([row('item-'+i)], locale, '2026-10-23', k=>k)[0], summary: '<script>unsafe</script>'}));
  const html = renderToStaticMarkup(React.createElement(HomeExperience,{ locale, items, headline:['한국 생활','더 가까이'], intro:'소개', topicLabels:{culture_experience:'문화',language_learning:'언어',employment_career:'취업'} }));
  assert.equal((html.match(/data-home-slide=/g)||[]).length, count ? 1 : 0);
  assert.equal((html.match(/data-home-measure=/g)||[]).length, count);
  assert.equal((html.match(/data-dot=/g)||[]).length, count > 1 ? count : 0);
  assert.equal((html.match(/class="peek /g)||[]).length, count > 2 ? 2 : count === 2 ? 1 : 0);
  assert.equal((html.match(/aria-haspopup="dialog"/g)||[]).length, count > 1 ? 1 : 0);
  assert(!html.includes('<script>unsafe</script>')); assert(!html.includes('http'));
  assert(html.includes('href="/feedback"')); assert(html.includes('role="tablist"'));
  if(count) assert(html.includes('data-image="false"')); else assert(html.includes(locale === 'ko' ? '지금은 소개할 정보가 없어요' : 'いま紹介できる情報はありません'));
});
check('the page retains one public fetch, structured selection and explicit section inputs', () => {
  const page = fs.readFileSync(path.join(root,'app/[locale]/page.tsx'),'utf8');
  assert.equal((page.match(/fetchLocalizedCurations\(locale\)/g)||[]).length,1);
  assert(page.includes('force-dynamic')); assert(page.includes('selectHomeContent(rows, now, pins)'));
  assert(page.includes('sections={sections}')); assert(!page.includes('SKETCH_DATA'));
});
const approved = {
  default: {main:'#E8E8F3',peek:'#F0F0F7'}, orange: {main:'#FFF0E5',peek:'#FFF5EF'},
  yellow: {main:'#FBF3D9',peek:'#FDF8E8'}, green: {main:'#E1EFEC',peek:'#ECF6F2'},
  blue: {main:'#E5E8F8',peek:'#EFF1FC'}, purple: {main:'#EEE5F6',peek:'#F5EFFA'},
  red: {main:'#F6E4EC',peek:'#FBEEF3'},
};
check('only the seven approved palette families are available and immutable', () => {
  assert.deepEqual(homeCardPalette, approved);
  assert(Object.isFrozen(homeCardPalette));
  for(const colors of Object.values(homeCardPalette)) assert(Object.isFrozen(colors));
});
check('unassigned, invalid, inherited and former sketch tones use default; no image overrides any tone', () => {
  for(const tone of [undefined,null,'','peach','sage','mint','neutral','__proto__','constructor','toString','#FFF0E5',{},7]) {
    assert.equal(homeCardColors(tone,true).tone,'default');
  }
  for(const tone of Object.keys(approved)) assert.equal(homeCardColors(tone,false).tone,'default');
});
for(const locale of ['ko','ja']) for(const [tone,colors] of Object.entries(approved)) check(`${locale} ${tone}: shared main/peek family with no visible review controls`, () => {
  const item={...homeItems([row(tone)],locale,'2026-10-23',k=>k)[0],imageUrl:'https://images.seoul.go.kr/poster.jpg',tone};
  const html=renderToStaticMarkup(React.createElement(HomeFeaturedCarousel,{locale,items:[item,{...item,id:'other',slug:'other'}]}));
  const elements=[...html.matchAll(/<(a|button)\b[^>]*data-tone="([^"]*)"[^>]*>/g)].map(m=>m[0]);
  assert.equal(elements.length,4); // two inert measurements, one active card, one unique peek
  for(const element of elements) {
    assert(element.includes(`data-tone="${tone}"`));
    assert(element.includes(`--home-card-main:${colors.main}`));
    assert(element.includes(`--home-card-peek:${colors.peek}`));
  }
  assert(!/palette-choice|palette-review|B2|P10|<select|<canvas/.test(html));
});
check('no image and rejected image URL use default even with a supplied color; list cards stay unchanged', () => {
  for(const imageUrl of [null,'javascript:alert(1)','http://localhost/poster.jpg']) {
    const item={...homeItems([row('fallback')],'ko','2026-10-23',k=>k)[0],imageUrl,tone:'red'};
    const featured=renderToStaticMarkup(React.createElement(HomeFeaturedCarousel,{locale:'ko',items:[item,{...item,id:'other'}]}));
    assert.equal((featured.match(/data-tone="default"/g)||[]).length,4);
    assert(!featured.includes('data-tone="red"'));
    const list=renderToStaticMarkup(React.createElement(HomeContentCard,{item,locale:'ko'}));
    assert(!list.includes('data-tone=')&&!list.includes('--home-card-'));
  }
});
check('approved pale surfaces retain readable navy text and distinct focus in both themes', () => {
  const luminance=hex=>{
    const c=hex.slice(1).match(/../g).map(x=>parseInt(x,16)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);
    return c[0]*.2126+c[1]*.7152+c[2]*.0722;
  };
  const contrast=(a,b)=>{const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
  for(const colors of Object.values(approved)) for(const surface of Object.values(colors)) {
    for(const text of ['#102f5c','#3d5871','#52677c','#984419']) assert(contrast(text,surface)>=4.5,`${text} on ${surface}`);
    assert(contrast('#1e5e9d',surface)>=3);
  }
  const css=fs.readFileSync(path.join(root,'app/components/HomeExperience.module.css'),'utf8');
  assert(css.includes('background: var(--home-card-main,#E8E8F3)'));
  assert(css.includes('background: var(--home-card-peek,#F0F0F7)'));
  assert(!/data-tone=(peach|sage|mint)/.test(css));
});
console.log(`${passed} home presentation checks passed; real DB/AI/network calls: 0`);
