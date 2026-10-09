const assert=require('node:assert/strict'), fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=process.cwd(),ts=require(path.join(root,'node_modules/typescript'));
const contracts=require(path.join(root,'app/lib/comments/contracts.ts'));
const source=fs.readFileSync(path.join(root,'app/components/ContentComments.tsx'),'utf8');
let messages=JSON.parse(fs.readFileSync(path.join(root,'messages/ko.json'))).Comments;
let slots=[],index=0,effects=[],tree,checks=0,calls=[],viewer={signedIn:true,code:'00031',moderator:false},outcome='absent',createMode='uncertain',delayResolve;
const check=v=>{assert.ok(v);checks++};
const depsEqual=(a,b)=>a&&b&&a.length===b.length&&a.every((v,i)=>Object.is(v,b[i]));
const react={useState(init){const i=index++;if(!(i in slots))slots[i]={value:typeof init==='function'?init():init};return [slots[i].value,v=>{slots[i].value=typeof v==='function'?v(slots[i].value):v}]},useRef(value){const i=index++;return (slots[i]??={current:value})},useId(){index++;return 'test-input'},useCallback(fn,deps){const i=index++;if(!slots[i]||!depsEqual(slots[i].deps,deps))slots[i]={value:fn,deps};return slots[i].value},useEffect(fn,deps){const i=index++;if(!slots[i]||!depsEqual(slots[i].deps,deps)){slots[i]={deps};effects.push(fn)}}};
const jsx=(type,props)=>({type,props:props??{}});
const sandbox={module:{exports:{}},exports:{},console,URLSearchParams,Intl,Date,Map,Set,Error,crypto:require('node:crypto').webcrypto,queueMicrotask,window:new EventTarget(),fetch:async(url,options={})=>{
 const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
 if(body?.action==='create'){if(createMode==='delayed')await new Promise(r=>delayResolve=r);if(createMode==='uncertain')return {ok:false,status:503,json:async()=>({error:'unavailable'})};if(createMode==='knownFailure')return {ok:false,status:429,json:async()=>({error:'rate_limited'})};return {ok:true,status:200,json:async()=>({outcome:'accepted'})};}
 if(body?.action==='prepare')return {ok:true,status:200,json:async()=>({code:viewer.code??'00031'})};
 if(url.includes('requestId='))return {ok:true,status:200,json:async()=>({outcome})};
 return {ok:true,status:200,json:async()=>({viewer:{...viewer},items:[],next:null})};
},require(s){if(s==='react')return react;if(s==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:'fragment'};if(s==='next-intl')return {useTranslations:()=>((key,values={})=>Object.entries(values).reduce((out,[k,v])=>out.replaceAll('{'+k+'}',v),messages[key]??key))};if(s==='lucide-react')return {MessageSquare:'icon'};if(s.endsWith('PublicNavigationLink'))return {default:'link'};if(s.endsWith('/auth/urls'))return {loginUrl:(l,n)=>'/'+l+'/login?next='+encodeURIComponent(n)};if(s.endsWith('/comments/contracts'))return contracts;if(s.endsWith('.css'))return {default:{}};throw Error('unexpected import '+s)}};
sandbox.exports=sandbox.module.exports;
vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText,sandbox);
const Component=sandbox.module.exports.default;
let locale='ko';
function render(){index=0;tree=Component({id:'10000000-0000-4000-8000-000000000001',slug:'synthetic-program',locale});const pending=effects;effects=[];for(const fn of pending)fn();return tree}
function nodes(n){if(!n||typeof n!=='object')return [];if(Array.isArray(n))return n.flatMap(x=>nodes(x));return [n,...nodes(n.props?.children)]}
function text(n){if(n==null)return '';if(typeof n==='string'||typeof n==='number')return String(n);if(Array.isArray(n))return n.map(text).join('');return text(n.props?.children)}
const button=key=>{const n=nodes(tree).find(n=>n.type==='button'&&text(n)===messages[key]);assert.ok(n,'missing button '+key);return n};
const textarea=()=>nodes(tree).find(n=>n.type==='textarea');
const flush=async()=>{for(let i=0;i<5;i++){await new Promise(r=>setImmediate(r));render()}};
const writes=()=>calls.filter(c=>c.body?.action==='create');
function reset(code){slots=[];effects=[];calls=[];viewer={signedIn:true,code,moderator:false};sandbox.window=new EventTarget();createMode='uncertain';outcome='absent';}
(async()=>{
 for(const code of ['00000','00031','99999']){
  reset(code);render();await flush();check(text(tree).includes('마을주민 '+code));check(!calls.some(c=>c.body));
  sandbox.window.dispatchEvent(new Event('focus'));await flush();check(text(tree).includes('마을주민 '+code));check(!calls.some(c=>c.body));
 }
 reset('A7K2Q9');render();await flush();
 textarea().props.onChange({target:{value:'전환 이전 성공 여부 확인'}});render();button('post').props.onClick();await flush();
 const oldRequest=writes()[0].body;check(oldRequest.expectedCode==='A7K2Q9');check(textarea().props.readOnly);
 viewer.code='00031';sandbox.window.dispatchEvent(new Event('focus'));await flush();check(textarea().props.value==='전환 이전 성공 여부 확인');check(writes().length===1);
 outcome='accepted';button('checkSubmission').props.onClick();await flush();check(textarea().props.value==='');check(writes().length===1);
 reset('A7K2Q9');render();await flush();
 const draft='전환 이전 미처리 입력 보존 😀';textarea().props.onChange({target:{value:draft}});render();button('post').props.onClick();await flush();
 const absentRequest=writes()[0].body;viewer.code='00031';sandbox.window.dispatchEvent(new Event('focus'));await flush();
 button('checkSubmission').props.onClick();await flush();check(textarea().props.value===draft);check(textarea().props.readOnly);check(writes().length===1);
 check(!nodes(tree).some(n=>n.type==='button'&&text(n)===messages.retrySame));check(text(tree).includes(messages.identity_changed));
 button('newAccountDraft').props.onClick();await flush();check(!textarea().props.readOnly);check(textarea().props.value===draft);check(writes().length===1);
 createMode='accepted';button('post').props.onClick();await flush();check(writes().length===2);check(writes()[1].body.expectedCode==='00031');check(writes()[1].body.requestId!==absentRequest.requestId);check(writes()[1].body.body===draft);check(textarea().props.value==='');
 locale='ja';messages=JSON.parse(fs.readFileSync(path.join(root,'messages/ja.json'))).Comments;reset('00031');render();await flush();check(text(tree).includes('村人 00031'));check(!calls.some(c=>c.body));
 console.log(JSON.stringify({checks,actualComponent:true,realNetwork:false,conversion:'synthetic',writes:'fake-only'}));
})().catch(e=>{console.error(e);process.exitCode=1});
