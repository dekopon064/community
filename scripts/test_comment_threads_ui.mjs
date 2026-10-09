import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
import ts from 'typescript';
import * as contracts from '../app/lib/comments/contracts.ts';
const root=process.cwd();
const source=fs.readFileSync(path.join(root,'app/components/ContentComments.tsx'),'utf8');
let messages=JSON.parse(fs.readFileSync(path.join(root,'messages/ko.json'))).Comments;
let slots=[],index=0,effects=[],tree,checks=0,calls=[],viewer={signedIn:true,code:'00031',moderator:false},total=25,countFailure=false,replyReadFailure=false,rootsNext=null,secondRoots=null,roots=[],replies=[],outcome='absent',createMode='uncertain';
const check=v=>{assert.ok(v);checks++};
const depsEqual=(a,b)=>a&&b&&a.length===b.length&&a.every((v,i)=>Object.is(v,b[i]));
const react={useState(init){const i=index++;if(!(i in slots))slots[i]={value:typeof init==='function'?init():init};return [slots[i].value,v=>{slots[i].value=typeof v==='function'?v(slots[i].value):v}]},useRef(value){const i=index++;return (slots[i]??={current:value})},useId(){index++;return 'test-input'},useCallback(fn,deps){const i=index++;if(!slots[i]||!depsEqual(slots[i].deps,deps))slots[i]={value:fn,deps};return slots[i].value},useEffect(fn,deps){const i=index++;if(!slots[i]||!depsEqual(slots[i].deps,deps)){slots[i]={deps};effects.push(fn)}}};
const jsx=(type,props)=>({type,props:props??{}});
const sandbox={module:{exports:{}},exports:{},console,URLSearchParams,Intl,Date,Map,Set,Error,crypto:webcrypto,queueMicrotask,window:new EventTarget(),fetch:async(url,options={})=>{
 const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
 if(body?.action==='create'){if(createMode==='uncertain')return {ok:false,status:503,json:async()=>({error:'unavailable'})};if(createMode==='knownFailure')return {ok:false,status:429,json:async()=>({error:'rate_limited'})};return {ok:true,status:200,json:async()=>({outcome:'accepted'})};}
 if(body?.action==='prepare')return {ok:true,status:200,json:async()=>({code:viewer.code??'00031'})};
 if(url.includes('view=count'))return {ok:!countFailure,status:countFailure?503:200,json:async()=>countFailure?({error:'unavailable'}):({count:total})};
 if(url.includes('parentId=')&&replyReadFailure)return {ok:false,status:503,json:async()=>({error:'unavailable'})};
 if(url.includes('requestId='))return {ok:true,status:200,json:async()=>({outcome})};
 return {ok:true,status:200,json:async()=>({viewer:{...viewer},items:url.includes('parentId=')?replies:secondRoots&&url.includes('at=')?secondRoots:roots,next:url.includes('parentId=')||url.includes('at=')?null:rootsNext,parentState:roots[0]?.state??"live"})};
},require(s){if(s==='react')return react;if(s==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:'fragment'};if(s==='next-intl')return {useTranslations:()=>((key,values={})=>Object.entries(values).reduce((out,[k,v])=>out.replaceAll('{'+k+'}',v),messages[key]??key))};if(s==='lucide-react')return {MessageSquare:'icon'};if(s.endsWith('PublicNavigationLink'))return {default:'link'};if(s.endsWith('/auth/urls'))return {loginUrl:(l,n)=>'/'+l+'/login?next='+encodeURIComponent(n)};if(s.endsWith('/comments/contracts'))return contracts;if(s.endsWith('.css'))return {default:{}};throw Error('unexpected import '+s)}};
sandbox.exports=sandbox.module.exports;
vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText,sandbox);
const Component=sandbox.module.exports.default;
let locale='ko';
function render(){index=0;tree=Component({id:'10000000-0000-4000-8000-000000000001',slug:'synthetic-program',locale});const pending=effects;effects=[];for(const fn of pending)fn();return tree}
function nodes(n){if(!n||typeof n!=='object')return [];if(Array.isArray(n))return n.flatMap(x=>nodes(x));return [n,...nodes(n.props?.children)]}
function text(n){if(n==null)return '';if(typeof n==='string'||typeof n==='number')return String(n);if(Array.isArray(n))return n.map(text).join('');return text(n.props?.children)}
const button=key=>{const n=nodes(tree).find(n=>n.type==='button'&&text(n)===messages[key]);assert.ok(n,'missing button '+key);return n};
const flush=async()=>{for(let i=0;i<5;i++){await new Promise(r=>setImmediate(r));render()}};
const writes=()=>calls.filter(c=>c.body?.action==='create');
function reset(code){slots=[];effects=[];calls=[];viewer={signedIn:true,code,moderator:false};sandbox.window=new EventTarget();createMode='uncertain';outcome='absent';}

const ROOT='20000000-0000-4000-8000-000000000001',OTHER='20000000-0000-4000-8000-000000000002';
const row=(id,body='합성 원댓글')=>({id,body,residentCode:'00031',createdAt:'2026-10-09T00:00:00Z',canDelete:true,state:'live',replyCount:0});
const replyInput=()=>nodes(tree).find(n=>n.type==='textarea'&&n.props.id.includes(ROOT));
(async()=>{
 reset('00031');roots=[{...row(ROOT),replyCount:1},row(OTHER)];replies=[row('40000000-0000-4000-8000-000000000001','합성 답글')];render();await flush();
 check(text(tree).includes('댓글 (25)'));check(!calls.some(c=>c.body));
 check(text(tree).includes('합성 답글'));check(!text(tree).includes('답글 1개 보기'));
 button('reply').props.onClick();await flush();check(!!replyInput());check(text(tree).includes('마을주민 00031'));
 const draft='보존할 답글 😀';replyInput().props.onChange({target:{value:draft}});render();button('postReply').props.onClick();await flush();
 check(writes().length===1&&writes()[0].body.parentId===ROOT);check(replyInput().props.value===draft&&replyInput().props.readOnly);
 outcome='absent';button('checkSubmission').props.onClick();await flush();check(writes().length===1);check(!!button('retrySame'));check(replyInput().props.value===draft);
 createMode='accepted';button('retrySame').props.onClick();await flush();check(writes().length===2);check(writes()[0].body.requestId===writes()[1].body.requestId);check(!replyInput());button('reply').props.onClick();await flush();check(replyInput().props.value==='');
 replyInput().props.onChange({target:{value:'세션 변화 입력 보존'}});render();viewer.code='99999';sandbox.window.dispatchEvent(new Event('focus'));await flush();check(replyInput().props.value==='세션 변화 입력 보존');check(writes().length===2);
 const originalRoots=roots;roots=[row(OTHER)];sandbox.window.dispatchEvent(new Event('focus'));await flush();check(replyInput().props.value==='세션 변화 입력 보존');check(!replyInput().props.readOnly);check(!text(tree).includes(messages.parent_unavailable));replyReadFailure=true;sandbox.window.dispatchEvent(new Event('focus'));await flush();check(replyInput().props.value==='세션 변화 입력 보존');check(!replyInput().props.readOnly);check(text(tree).includes(messages.read_failed));check(!text(tree).includes(messages.parent_unavailable));check(button('postReply').props.disabled);replyReadFailure=false;sandbox.window.dispatchEvent(new Event('focus'));await flush();check(!button('postReply').props.disabled);roots=originalRoots;
 roots[0]={...roots[0],state:'hidden',body:null,residentCode:null,canDelete:false};sandbox.window.dispatchEvent(new Event('focus'));await flush();check(text(tree).includes(messages.hiddenParent));check(replyInput().props.readOnly);check(button('postReply').props.disabled);check(replyInput().props.value==='세션 변화 입력 보존');
 countFailure=true;sandbox.window.dispatchEvent(new Event('focus'));await flush();check(text(tree).includes(messages.count_failed));check(!text(tree).includes('댓글 (0)'));check(text(tree).includes(messages.hiddenParent));
 countFailure=false;total=0;button('reloadCount').props.onClick();await flush();check(text(tree).includes('댓글 (0)'));
 locale='ja';messages=JSON.parse(fs.readFileSync(path.join(root,'messages/ja.json'))).Comments;render();check(text(tree).includes('コメント (0)'));check(text(tree).includes(messages.hiddenParent));
 locale='ko';messages=JSON.parse(fs.readFileSync(path.join(root,'messages/ko.json'))).Comments;
 reset('00031');roots=[{...row(ROOT),replyCount:1},...Array.from({length:19},(_,i)=>row(`50000000-0000-4000-8000-${String(i+1).padStart(12,'0')}`,'첫 페이지 원댓글 '+i))];secondRoots=[row(OTHER,'두 번째 페이지 원댓글')];rootsNext={at:'2026-10-08T00:00:00Z',id:ROOT};render();await flush();
 check(text(tree).includes('합성 답글'));check(!calls.some(c=>c.body));
 const rootInput=()=>nodes(tree).find(n=>n.type==='textarea'&&n.props.id==='test-input');rootInput().props.onChange({target:{value:'원댓글 초안'}});render();button('reply').props.onClick();await flush();replyInput().props.onChange({target:{value:'답글 초안'}});render();
 const pageButton=n=>nodes(tree).find(x=>x.type==='button'&&x.props['aria-label']===messages.pageLabel.replace('{page}',n));
 pageButton(2).props.onClick();await flush();check(text(tree).includes('두 번째 페이지 원댓글'));check(!text(tree).includes('첫 페이지 원댓글'));check(!replyInput());check(rootInput().props.value==='원댓글 초안');check(button('nextPage').props.disabled);check(pageButton(2).props['aria-current']==='page');
 pageButton(1).props.onClick();await flush();button('reply').props.onClick();await flush();check(replyInput().props.value==='답글 초안');check(rootInput().props.value==='원댓글 초안');check(text(tree).includes('첫 페이지 원댓글'));check(!text(tree).includes('두 번째 페이지 원댓글'));check(writes().length===0);
 console.log(JSON.stringify({checks,actualComponent:true,network:'fake-only'}));
})().catch(e=>{console.error(e);process.exitCode=1});
