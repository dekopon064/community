// Actual shared editor handlers with injected hooks; no browser/image requests.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
function load(file,deps){const code=ts.transpileModule(readFileSync(new URL(file,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 const exports={};new Function('require','exports',code)(s=>s in deps?deps[s]:require(s),exports);return exports;}
const {sourceImageUrl}=load('../app/lib/sourceImages.ts',{});
let state=[],cursor=0,value,changes=0;const hooks={...React,useRef:()=>({current:null}),useState(initial){const i=cursor++;if(!(i in state))state[i]=initial;return [state[i],v=>state[i]=v];}};
const {default:Editor,candidateImageError}=load('../app/components/admin/CandidateImageEditor.tsx',{
 react:hooks,'next/image':{default:function Image(){}},'@/app/lib/sourceImages':{sourceImageUrl},'../SourceImageDialog':{default:()=>null},'./ReviewEditors':{fieldClass:'fixture-field'}
});
const children=t=>[t,...React.Children.toArray(t?.props?.children).flatMap(n=>typeof n==='object'?children(n):[])];
const text=t=>typeof t==='string'?t:React.Children.toArray(t?.props?.children).map(text).join('');
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const saved={mode:'source',url:null,sourceUrl:null};
function render(disabled=false){cursor=0;return Editor({saved,value,onChange:v=>{value=v;changes++;},disabled,title:'합성 서울 예약',error:''});}
const originalFetch=globalThis.fetch;globalThis.fetch=()=>{throw Error('network forbidden');};
try{
 value={mode:'source',url:null};let tree=render();eq(text(tree).includes('등록된 이미지가 없습니다'),true);
 const mode=m=>children(render()).find(n=>n?.type==='input'&&n.props.value===m);
 mode('override').props.onChange();eq(value,{mode:'override',url:''});eq(candidateImageError(value).length>0,true);
 let input=children(render()).find(n=>n?.props?.id==='candidate-image-url');input.props.onChange({target:{value:'https://images.example.org/first.png'}});
 eq(candidateImageError(value),'');eq(value.url,'https://images.example.org/first.png');eq(text(render()).includes('미저장 이미지 선택'),true);
 input=children(render()).find(n=>n?.props?.id==='candidate-image-url');input.props.onChange({target:{value:'https://images.example.org/edited.png'}});eq(value.url,'https://images.example.org/edited.png');
 mode('none').props.onChange();eq(value,{mode:'none',url:null});eq(text(render()).includes('등록된 이미지가 없습니다'),true);
 mode('override').props.onChange();eq(value.url,'https://images.example.org/edited.png'); // draft URL survives mode toggle
 const image=children(render()).find(n=>n?.props?.src===value.url);eq(image.props.unoptimized,true);eq(image.props.referrerPolicy,'no-referrer');
 image.props.onError();eq(text(render()).includes('이미지를 불러오지 못했습니다'),true);
 mode('source').props.onChange();eq(value,{mode:'source',url:null});eq(render(true).props.disabled,true);
 eq(saved,{mode:'source',url:null,sourceUrl:null});eq(changes,6);
 console.log(`Shared candidate image editor: ${checks} actual add/edit/remove/toggle/failure/disabled checks passed; fetch=0.`);
}finally{globalThis.fetch=originalFetch;}
