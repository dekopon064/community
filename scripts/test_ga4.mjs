// Synthetic hosts, fake admin responses and an in-memory Google command queue.
// Fail on any real network, credentials, DB or analytics connection.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { registerHooks, syncBuiltinESMExports } from 'node:module';
import http from 'node:http'; import https from 'node:https'; import net from 'node:net';
import ts from 'typescript';
const deny = () => { throw Error('external_network_forbidden'); };
globalThis.fetch = http.get = http.request = https.get = https.request = net.Socket.prototype.connect = deny;
syncBuiltinESMExports();
registerHooks({
 resolve(s,c,next) { try { return next(s,c); } catch(e) { if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e; } },
 load(url,c,next) { return url.startsWith('file:')&&url.endsWith('.ts') ? {format:'module',shortCircuit:true,source:ts.transpileModule(fs.readFileSync(new URL(url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText} : next(url,c); },
});
const { ga4Config,ga4Page,ga4Referrer,ga4OfficialUrl }=await import('../app/lib/analytics/ga4.ts');
const { createGa4Runtime,browserGa4 }=await import('../app/lib/analytics/ga4-browser.ts');
const env={NODE_ENV:'production',VERCEL_ENV:'production',GA4_MANUAL_MEASUREMENT_READY:'true',GA4_MEASUREMENT_ID:'G-FAKE000001',GA4_SITE_ORIGIN:'https://machimoa.example.org'};
const config=ga4Config(env),origin=config.origin;
let checks=0;
const test=async(name,fn)=>{await fn();checks++;console.log('PASS '+name);};
const flush=async()=>{for(let n=0;n<8;n++)await Promise.resolve();};
class Events {
 listeners=new Map();
 addEventListener(name,fn){if(!this.listeners.has(name))this.listeners.set(name,new Set());this.listeners.get(name).add(fn);}
 removeEventListener(name,fn){this.listeners.get(name)?.delete(fn);}
 emit(name,event={}){for(const fn of [...this.listeners.get(name)??[]])fn({type:name,...event});}
 count(name){return this.listeners.get(name)?.size??0;}
}
function fixture(path='/ko',status=401) {
 const scripts=[],observers=new Set(),auth=[];
 const doc=new Events(),win=new Events();
 let marker=null,resolveAuth=null;
 Object.assign(doc,{referrer:'https://www.instagram.com/profile?private=never-copy',body:{},
  querySelector:()=>marker,createElement:()=>({addEventListener(name,fn){this[name]=fn;}}),head:{appendChild:s=>scripts.push(s)}});
 Object.assign(win,{document:doc,location:{href:origin+path},navigator:{doNotTrack:null},
  MutationObserver:class {constructor(fn){this.fn=fn;}observe(){observers.add(this);}disconnect(){observers.delete(this);}},
  fetch:async(url,options)=>{auth.push({url,options});
   if(status==='pending')return new Promise(resolve=>{resolveAuth=resolve;});
   if(status==='throw')throw Error('secret-error-never-log');
   return response(status);
  }});
 function response(code){return {status:code,json:async()=>({status:code===401?'signed_out':code===403?'forbidden':code===200?'admin':'auth_unavailable'})};}
 return {win,doc,scripts,auth,observers,
  setStatus:value=>{status=value;},resolve:code=>resolveAuth(response(code)),
  marker:(slug,language='ko',title='합성 콘텐츠')=>{marker={dataset:{ga4ContentSlug:slug,ga4ContentLanguage:language,ga4ContentTitle:title}};for(const observer of [...observers])observer.fn();},
  navigate:(path)=>{win.location.href=path.startsWith('http')?path:origin+path;},
  commands:()=>Array.from(win.dataLayer??[],args=>Array.from(args)),
  events:()=>Array.from(win.dataLayer??[],args=>Array.from(args)).filter(c=>c[0]==='event'),
  click:(placement='trust_panel',href='https://reserve.example.org/detail?SVCID=secret-value#token',extra={})=>{
   const anchor={dataset:{ga4OfficialLink:placement},href};const event={button:0,target:{closest:()=>anchor},defaultPrevented:false,...extra};doc.emit(extra.type??'click',event);
  },
 };
}

await test('only explicit production/readiness/ID/canonical origin enables the integration',()=>{
 assert(config);
 for(const [key,value]of [['NODE_ENV','development'],['NODE_ENV','test'],['VERCEL_ENV','preview'],['VERCEL_ENV','development'],['VERCEL_ENV',undefined],['GA4_MANUAL_MEASUREMENT_READY',undefined],['GA4_MEASUREMENT_ID','G-X\";bad'],['GA4_SITE_ORIGIN','http://localhost:3000'],['GA4_SITE_ORIGIN','https://127.0.0.1'],['GA4_SITE_ORIGIN','https://app.local'],['GA4_SITE_ORIGIN','https://machimoa.example.org/path'],['GA4_SITE_ORIGIN','https://user:password@machimoa.example.org']]) assert.equal(ga4Config({...env,[key]:value}),null,key);
});
await test('public routes only; local, deployment aliases, auth/admin/private and unknown paths excluded',()=>{
 for(const lang of ['ko','ja'])for(const path of ['', '/info','/info/category/living','/info/living-abc','/privacy','/qna','/feedback'])assert(ga4Page(config,origin+'/'+lang+path));
 for(const path of ['/ko/admin','/ja/admin/living','/ko/admin-extra','/api/admin/living','/ko/login','/ko/saved','/ko/auth/callback','/ko/feedback/delete','/ko/%61dmin','/ko/info/../admin','/ko/info/a/b','/ko/info/category/bad'])assert.equal(ga4Page(config,origin+path),null,path);
 for(const href of ['http://localhost:3298/ko','https://localhost/ko','http://127.0.0.1/ko','https://community-preview.vercel.app/ko','https://machimoa.example.org.evil.org/ko'])assert.equal(ga4Page(config,href),null);
});
await test('campaign allowlist survives; search text, filters, secrets, auth fragments and raw referrer paths never leave',()=>{
 const p=ga4Page(config,origin+'/ja/info/abc?utm_source=instagram&utm_medium=social&utm_campaign=autumn&utm_content=card_2&utm_term=private&q=person@example.com&code=secret#access_token=secret');
 assert.equal(p.location,origin+'/ja/info/abc?utm_source=instagram&utm_medium=social&utm_campaign=autumn&utm_content=card_2');
 assert.equal(ga4Page(config,origin+'/ko?utm_campaign=person%40example.com').location,origin+'/ko');
 assert.equal(ga4Referrer(config,'https://www.instagram.com/private-account?token=private#secret'),'https://www.instagram.com');
 assert.equal(ga4Referrer(config,origin+'/ko/admin/living?secret=x'),'');
 assert.equal(ga4Referrer(config,origin+'/ko/info/abc?q=secret'),origin+'/ko/info/abc');
 assert.equal(ga4Referrer(config,'https://user:password@instagram.com/private'),'');
});
await test('admin authorization pending/excluded/error/malformed fails closed without loading Google',async()=>{
 for(const status of [200,503,500,'throw']){const f=fixture('/ko',status),r=createGa4Runtime(config,f.win);const off=r.connect();await flush();assert.equal(f.scripts.length,0);assert.equal(f.events().length,0);assert.equal(f.win['ga-disable-'+config.measurementId],true);off();}
 const f=fixture('/ko','pending'),r=createGa4Runtime(config,f.win),off=r.connect();assert.equal(f.scripts.length,0);f.navigate('/ko/admin');r.sync();f.resolve(401);await flush();assert.equal(f.scripts.length,0);off();
 const bad=fixture();bad.win.fetch=async()=>({status:401,json:async()=>({status:'untrusted'})});const badOff=createGa4Runtime(config,bad.win).connect();await flush();assert.equal(bad.scripts.length,0);badOff();
});
await test('initial admin, preview alias, and local browser issue no Auth or Google request',async()=>{
 for(const path of ['/ko/admin/living','https://preview.vercel.app/ko','http://localhost:3300/ko']){const f=fixture();f.navigate(path);const off=createGa4Runtime(config,f.win).connect();await flush();assert.equal(f.auth.length,0);assert.equal(f.scripts.length,0);off();}
});
await test('anonymous and verified non-admin may collect, without sending identity or calling any write',async()=>{
 for(const code of [401,403]){const f=fixture('/ko',code),r=createGa4Runtime(config,f.win),off=r.connect();await flush();assert.equal(f.events().length,1);assert.equal(f.scripts.length,1);assert.deepEqual(f.auth[0],{url:'/api/admin/access',options:{credentials:'same-origin',cache:'no-store'}});assert.equal(f.events()[0][1],'page_view');assert(!JSON.stringify(f.commands()).includes('private-account'));off();}
});
await test('initial hydration, StrictMode and remount use one SDK and one pageview',async()=>{
 const f=fixture(),r=browserGa4(config,f.win),off=r.connect();r.sync();off();const again=browserGa4({...config},f.win),end=again.connect();r.sync();await flush();r.sync();assert.equal(r,again);assert.equal(f.scripts.length,1);assert.equal(f.events().length,1);assert.equal(f.doc.count('click'),1);end();assert.equal(f.doc.count('click'),0);assert.equal(f.win['ga-disable-'+config.measurementId],true);
 assert.equal(browserGa4({...config,measurementId:'G-DIFFERENT'},f.win),null);
});
await test('SPA A→B→A records three visits, query/hash edits do not fabricate more',async()=>{
 const f=fixture(),r=createGa4Runtime(config,f.win),off=r.connect();await flush();
 for(const path of ['/ko/info','/ko','/ko?q=private','/ko#part']){f.navigate(path);r.sync();}
 assert.equal(f.events().length,3);assert.equal(f.events()[1][2].page_referrer,origin+'/ko');assert.equal(f.events()[2][2].page_referrer,origin+'/ko/info');off();
});
await test('streamed detail waits for the matching locale marker; same content ID across ko/ja, one view each',async()=>{
 const f=fixture('/ko/info/abc'),r=createGa4Runtime(config,f.win),off=r.connect();await flush();assert.equal(f.events().length,0);assert.equal(f.observers.size,1);
 f.marker('old');assert.equal(f.events().length,0);f.marker('abc');assert.equal(f.events().length,1);assert.equal(f.observers.size,0);
 f.navigate('/ja/info/abc');r.sync();assert.equal(f.events().length,1);assert.equal(f.win['ga-disable-'+config.measurementId],true);
 f.marker('abc','ja','合成コンテンツ');r.sync();assert.equal(f.events().length,2);assert.deepEqual(f.events().map(e=>e[2].content_language),['ko','ja']);assert.deepEqual(f.events().map(e=>e[2].content_id),['abc','abc']);off();
});
await test('private navigation disables native collection immediately, before React sync; returning public rechecks Auth',async()=>{
 const f=fixture(),r=createGa4Runtime(config,f.win),off=r.connect();await flush();assert.equal(f.win['ga-disable-'+config.measurementId],false);
 f.navigate('/ja/admin/living');assert.equal(f.win['ga-disable-'+config.measurementId],true);r.sync();assert.equal(f.events().length,1);
 f.navigate('/ja');assert.equal(f.win['ga-disable-'+config.measurementId],true);r.sync();await flush();assert.equal(f.auth.length,2);assert.equal(f.events().length,2);assert.equal(f.events()[1][2].page_referrer,'');off();
});
await test('account changes, focus and access ambiguity stop collection; stale Auth result cannot override current identity',async()=>{
 const f=fixture('/ko','pending'),r=createGa4Runtime(config,f.win),off=r.connect();const first=f.resolve;
 f.setStatus(200);f.win.emit('machimoa-account-change');await flush();assert.equal(f.events().length,0);first(401);await flush();assert.equal(f.events().length,0);off();
 const a=fixture(),x=createGa4Runtime(config,a.win),end=x.connect();await flush();a.setStatus(200);a.win.emit('machimoa-account-change');assert.equal(a.win['ga-disable-'+config.measurementId],true);await flush();a.navigate('/ko/info');x.sync();assert.equal(a.events().length,1);
 a.setStatus(401);a.win.emit('machimoa-account-change');await flush();assert.equal(a.events().length,2);assert.equal(a.events()[1][2].page_location,origin+'/ko/info');x.sync();assert.equal(a.events().length,2);end();
});
await test('PC/mobile/keyboard/modified and middle clicks enqueue once; preserve links and strip link queries',async()=>{
 const f=fixture('/ko/info/abc'),r=createGa4Runtime(config,f.win);f.marker('abc');const off=r.connect();await flush();
 f.click('trust_panel');f.click('mobile_source');f.click('trust_panel',undefined,{detail:0});f.click('trust_panel',undefined,{ctrlKey:true});f.click('trust_panel',undefined,{type:'auxclick',button:1});
 const clicks=f.events().filter(e=>e[1]==='official_link_click');assert.equal(clicks.length,5);
 for(const c of clicks){assert.equal(c[2].content_id,'abc');assert.equal(c[2].link_url,'https://reserve.example.org/detail');assert.equal(c[2].link_domain,'reserve.example.org');assert.equal(c[2].outbound,true);}
 assert(!JSON.stringify(f.commands()).includes('secret-value'));
 for(const extra of [{button:2},{defaultPrevented:true},{type:'auxclick',button:2}])f.click('trust_panel',undefined,extra);
 f.click('unmarked');f.click('trust_panel',origin+'/ko');f.click('trust_panel','javascript:alert(1)');f.click('trust_panel','https://user:pass@reserve.example.org/');
 assert.equal(f.events().filter(e=>e[1]==='official_link_click').length,5);off();
 assert.equal(ga4OfficialUrl('https://localhost/x',origin),null);
});
await test('ads signals and automatic pageviews off on EVERY config; native engagement remains SDK-owned',async()=>{
 const f=fixture(),r=createGa4Runtime(config,f.win),off=r.connect();await flush();f.navigate('/ja');r.sync();
 for(const c of f.commands().filter(c=>c[0]==='config')){assert.equal(c[2].send_page_view,false);assert.equal(c[2].allow_google_signals,false);assert.equal(c[2].allow_ad_personalization_signals,false);}
 assert.equal(f.events().some(c=>c[1]==='user_engagement'),false);assert.equal(f.events().some(c=>'engagement_time_msec'in c[2]),false);assert.equal(f.win['ga-disable-'+config.measurementId],false);off();
});
await test('explicit opt-out, DNT, pre-existing tag and script failure never produce replacement tags or retry',async()=>{
 const d=fixture();d.win['ga-disable-'+config.measurementId]=true;const r=createGa4Runtime(config,d.win),end=r.connect();await flush();assert.equal(d.scripts.length,0);end();
 const n=fixture();n.win.navigator.doNotTrack='1';const x=createGa4Runtime(config,n.win),off=x.connect();await flush();assert.equal(n.auth.length,0);off();
 const old=fixture();old.win.gtag=()=>{};assert.equal(createGa4Runtime(config,old.win),null);
 const f=fixture(),a=createGa4Runtime(config,f.win),stop=a.connect();await flush();f.scripts[0].error();f.navigate('/ja');a.sync();assert.equal(f.scripts.length,1);assert.equal(f.events().length,1);assert.equal(f.win['ga-disable-'+config.measurementId],true);stop();
});
await test('actual app wiring uses a server activation gate, one shared client and exact official markers',()=>{
 const read=name=>fs.readFileSync(new URL('../'+name,import.meta.url),'utf8');
 const layout=read('app/[locale]/layout.tsx');assert(layout.includes('ga4Config(process.env)'));assert(layout.includes('analytics ? <Ga4Analytics'));
 const component=read('app/components/Ga4Analytics.tsx');assert(component.includes("from 'next/navigation'"));assert(component.includes('?.connect()'));assert(component.includes('?.sync()'));assert(!component.includes('useSearchParams'));
 assert(read('app/components/CurationTrustPanel.tsx').includes('data-ga4-official-link="trust_panel"'));
 assert(read('app/components/CurationMobileSourceLink.tsx').includes('data-ga4-official-link="mobile_source"'));
 assert(read('app/[locale]/info/[id]/page.tsx').includes('data-ga4-content-language={locale}'));
});
console.log(JSON.stringify({groups:checks,real_ga4:0,real_auth:0,operational_db:0,production_writes:0,google_dashboard_verified:false}));
