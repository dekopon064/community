// Actual display components with synthetic content, hook lifecycle and fake HTTP.
// No credentials, database, provider, or external network are used.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {registerHooks} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';
import * as React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';

const root=fileURLToPath(new URL('../',import.meta.url));
const data=source=>'data:text/javascript,'+encodeURIComponent(source);
globalThis.detailReact=React;
globalThis.detailHook=null;
globalThis.detailTranslate=(key,values)=>key+(values?':'+values.count:'');
const hooks=data(`const R=globalThis.detailReact;
 export const useState=(v)=>globalThis.detailHook?globalThis.detailHook.state(v):R.useState(v);
 export const useRef=(v)=>globalThis.detailHook?globalThis.detailHook.ref(v):R.useRef(v);
 export const useEffect=(f,d)=>globalThis.detailHook?globalThis.detailHook.effect(f,d):R.useEffect(f,d);`);
registerHooks({
 resolve(specifier,context,next){
  if(specifier==='react'&&/auth\/(SaveControl|SavedCount)\.tsx$/.test(context.parentURL||''))return {url:hooks,shortCircuit:true};
  const mocks={
   'next-intl':'export const useTranslations=()=>globalThis.detailTranslate;',
   'next-intl/server':'export const getTranslations=async()=>globalThis.detailTranslate; export const setRequestLocale=()=>{};',
   'next/navigation':'export const notFound=()=>{throw Error("not found")};',
   '@/app/lib/curations':'export const fetchLocalizedCurationBySlug=async()=>globalThis.detailItem;',
   '@/app/lib/living/public-gallery':'export const publicLivingGallery=async()=>[];',
   '@/app/components/LivingImageGallery':'export default function Gallery(){return null;}',
   '@/app/lib/sourceImages':'export const sourceImageUrl=()=>null; export const sourceImageDisplayUrl=()=>null;',
   '@/app/components/PublicNavigationLink':'export default function Link(p){return globalThis.detailReact.createElement("a",p)}',
   '@/app/components/ContentComments':'export default function Comments(){return globalThis.detailReact.createElement("div",{"data-comments":true},"synthetic comments")}',
   '@/app/components/CurationTrustPanel':'export default function Trust(){return null}',
  };
  if(mocks[specifier])return {url:data(mocks[specifier]),shortCircuit:true};
  if(specifier==='next/image')return {url:data('export default function Image(){return null}'),shortCircuit:true};
  if(specifier.startsWith('@/'))specifier=pathToFileURL(path.join(root,specifier.slice(2))).href;
  try{return next(specifier,context);}catch(error){
   if(specifier.startsWith('file:')||specifier.startsWith('.'))for(const ext of ['.ts','.tsx'])try{return next(specifier+ext,context);}catch{}
   throw error;
  }
 },
 load(url,context,next){
  if(url.endsWith('.css'))return {format:'module',shortCircuit:true,source:'export default new Proxy({},{get:(_,key)=>String(key)})'};
  if(url.endsWith('.tsx'))return {format:'module',shortCircuit:true,source:ts.transpileModule(readFileSync(fileURLToPath(url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,jsx:ts.JsxEmit.ReactJSX}}).outputText};
  return next(url,context);
 }
});
globalThis.fetch=()=>{throw Error('network forbidden')};
const {default:Markdown}=await import('../app/components/Markdown.tsx');
const {default:Body}=await import('../app/components/CurationBody.tsx');
const {default:Count}=await import('../app/components/auth/SavedCount.tsx');
const {default:Save}=await import('../app/components/auth/SaveControl.tsx');
const {default:Page}=await import('../app/[locale]/info/[id]/page.tsx');
let checks=0;
function check(label,fn){fn();checks++;}
const html=(component,props)=>renderToStaticMarkup(React.createElement(component,props));
const input='first\nsecond\n\nthird';
check('default Markdown remains unchanged',()=>assert.doesNotMatch(html(Markdown,{children:input}),/<br/));
check('detail preserves soft newline',()=>assert.match(html(Markdown,{children:input,preserveLineBreaks:true}),/first<br\/>\nsecond/));
check('blank line remains paragraph',()=>assert.equal((html(Markdown,{children:input,preserveLineBreaks:true}).match(/<p /g)||[]).length,2));
const rich='- item\n  continuation\n- next\n\n1. first\n2. second\n\n**bold\ncontinued** [link\ntext](https://synthetic.invalid/)\n\n| A | B |\n| --- | --- |\n| a | b |\n\n```text\ncode_one\ncode_two\n```\n\n`inline_code`\n\n월~금 09:00~17:00';
const rendered=html(Markdown,{children:rich,preserveLineBreaks:true});
for(const [label,pattern] of [['list',/<li[^>]*>item<br\/>\ncontinuation/],['bold',/<strong[^>]*>bold<br\/>\ncontinued/],['link',/href="https:\/\/synthetic.invalid\/"/],['table',/<table/],['numbered list',/<ol/],['tilde',/월~금 09:00~17:00/]])check(label,()=>assert.match(rendered,pattern));
check('code whitespace untouched',()=>{const code=rendered.match(/<pre[\s\S]*?<\/pre>/)[0];assert.match(code,/code_one\ncode_two/);assert.doesNotMatch(code,/<br/)});
check('explicit break not doubled',()=>assert.equal((html(Markdown,{children:'one  \ntwo',preserveLineBreaks:true}).match(/<br/g)||[]).length,1));
for(const [locale,content] of [['ko','[한 줄 요약]\n요약\n[주요 내용]\n첫 줄\n둘째 줄'],['ja','[要約]\n要約\n[主な内容]\n一行目\n二行目'],['ko','plain\nbody']])check('actual body '+locale,()=>assert.match(html(Body,{content,locale}),/<br/));
check('input bytes untouched',()=>assert.equal(input,'first\nsecond\n\nthird'));

const id='10000000-0000-4000-8000-000000000001';
const listeners=new Map();
globalThis.window=new EventTarget();
window.location={href:'http://127.0.0.1/synthetic',assign:()=>{throw Error('login forbidden')}};
window.history={state:null,replaceState:()=>{}};
const add=window.addEventListener.bind(window),remove=window.removeEventListener.bind(window);
window.addEventListener=(name,fn)=>{if(!listeners.has(name))listeners.set(name,new Set());listeners.get(name).add(fn);add(name,fn)};
window.removeEventListener=(name,fn)=>{listeners.get(name)?.delete(fn);remove(name,fn)};
globalThis.BroadcastChannel=undefined;
function instance(component,props){
 const values=[],deps=[],cleanups=[],pending=[];let slot=0;
 const frame={
  state(v){const i=slot++;if(!(i in values))values[i]=typeof v==='function'?v():v;return [values[i],n=>values[i]=typeof n==='function'?n(values[i]):n]},
  ref(v){return this.state(()=>({current:v}))[0]},
  effect(fn,d){const i=slot++;if(!deps[i]||d.some((v,j)=>!Object.is(v,deps[i][j]))){deps[i]=d;pending.push(()=>{cleanups[i]?.();cleanups[i]=fn()})}}
 };
 return {render(next=props){props=next;slot=0;globalThis.detailHook=frame;try{return component(props)}finally{globalThis.detailHook=null}},effects(){while(pending.length)pending.shift()()},unmount(){cleanups.forEach(fn=>fn?.())}};
}
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve()};
const text=node=>node==null?'':Array.isArray(node)?node.map(text).join(''):typeof node==='object'?text(node.props?.children):String(node);
const find=(node,predicate)=>{if(!node||typeof node!=='object')return null;if(predicate(node))return node;for(const child of [...React.Children.toArray(node.props?.children),node.props?.save]){const match=find(child,predicate);if(match)return match}return null};
let requests=[],countValue=7,countFailure=false,stateSaved=false,writeMode='ok',writeVersion='2';
globalThis.fetch=async(url,options={})=>{
 assert.ok(url.startsWith('/api/saved-count?')||url.startsWith('/api/saved/'),'external request forbidden');
 assert.equal(options.cache,'no-store');requests.push({url,options});
 if(url.startsWith('/api/saved-count'))return {ok:!countFailure,json:async()=>({id,savedCount:countValue})};
 if(url.startsWith('/api/saved/state'))return {ok:true,status:200,json:async()=>({id,saved:stateSaved,version:writeVersion})};
 if(writeMode==='unknown')throw Error('synthetic response unknown');
 if(writeMode==='conflict')return {ok:false,status:409,json:async()=>({id,error:'state_changed',saved:stateSaved,version:writeVersion})};
 stateSaved=!stateSaved;countValue+=stateSaved?1:-1;return {ok:true,status:200,json:async()=>({id,saved:stateSaved,version:writeVersion})};
};
const count=instance(Count,{id,refreshKey:0,listenForChanges:true});count.render();count.effects();await settle();
check('real count read',()=>assert.match(text(count.render()),/count:7/));
const initial=requests.length;
window.dispatchEvent(new CustomEvent('machimoa-saved-count-change',{detail:{id:'different'}}));await settle();
check('unrelated event ignored',()=>assert.equal(requests.length,initial));
const save=instance(Save,{id,slug:'synthetic',locale:'ko',showCount:false});save.render();save.effects();await settle();
check('top count removed',()=>assert.equal(find(save.render(),n=>n.type===Count),null));
let button=find(save.render(),n=>n.type==='button');button.props.onClick();await settle();
check('save refreshes bottom count',()=>assert.match(text(count.render()),/count:8/));
check('latest version sent',()=>assert.equal(JSON.parse(requests.find(r=>r.options.method==='POST').options.body).version,'2'));
button=find(save.render(),n=>n.type==='button');button.props.onClick();await settle();
check('remove refreshes count',()=>assert.match(text(count.render()),/count:7/));
writeMode='conflict';countValue=11;button=find(save.render(),n=>n.type==='button');button.props.onClick();await settle();
check('conflict refreshes server count',()=>assert.match(text(count.render()),/count:11/));
check('conflict not automatically retried',()=>assert.equal(requests.filter(r=>r.options.method==='POST').length,3));
writeMode='unknown';button=find(save.render(),n=>n.type==='button');button.props.onClick();await settle();
check('ambiguous write not repeated',()=>assert.equal(requests.filter(r=>r.options.method==='POST').length,4));
countFailure=true;window.dispatchEvent(new CustomEvent('machimoa-saved-count-change',{detail:{id}}));await settle();
check('count error not zero',()=>{assert.match(text(count.render()),/countUnavailable/);assert.doesNotMatch(text(count.render()),/count:0/)});
countFailure=false;find(count.render(),n=>n.type==='button').props.onClick();count.render();count.effects();await settle();
check('explicit count retry works',()=>assert.match(text(count.render()),/count:11/));
count.unmount();save.unmount();
check('listeners removed',()=>assert.equal(listeners.get('machimoa-saved-count-change').size,0));
const unmounted=requests.length;window.dispatchEvent(new CustomEvent('machimoa-saved-count-change',{detail:{id}}));await settle();
check('unmounted count does not load',()=>assert.equal(requests.length,unmounted));
globalThis.detailItem={id,slug:'synthetic',userCategory:'program',title:'합성 제목',content:'first\nsecond',source_url:'https://synthetic.invalid/',created_at:'2026-10-01',updated_at:'2026-10-01'};
for(const locale of ['ko','ja']){
 const page=await Page({params:Promise.resolve({id:'synthetic',locale})});
 const bottom=find(page,n=>n.props?.['data-detail-saved-count']!==undefined);
 check(locale+' actual page count placement',()=>{assert.ok(bottom);assert.equal(find(bottom,n=>n.type===Count).props.listenForChanges,true);assert.equal(find(page,n=>n.type===Save).props.showCount,false)});
 check(locale+' body-column alignment',()=>assert.match(bottom.props.className,/lg:grid-cols-\[minmax\(0,1fr\)_minmax\(16rem,0.36fr\)\]/));
 const children=React.Children.toArray(page.props.children);
 check(locale+' count before comments',()=>{assert.equal(children.at(-2).props['data-detail-saved-count'],true);assert.equal(children.at(-1).props.showCount,undefined)});
}
globalThis.detailItem={...globalThis.detailItem,userCategory:null};
const noSave=await Page({params:Promise.resolve({id:'synthetic',locale:'ko'})});
check('non-saveable page unchanged',()=>assert.equal(find(noSave,n=>n.type===Count),null));
console.log(JSON.stringify({checks,syntheticOnly:true,databaseCalls:0,aiCalls:0,automaticWriteRetries:0}));
