// Existing shared component fallback only; injected state, no browser/network.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ts=require('typescript');
const load=(path,deps)=>{
 const code=ts.transpileModule(readFileSync(new URL(path,import.meta.url),'utf8'),{
  compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}
 }).outputText;
 const exports={};new Function('require','exports',code)(s=>s in deps?deps[s]:require(s),exports);return exports;
};
const {sourceImageUrl}=load('../app/lib/sourceImages.ts',{});
let failed=null;
const {default:SourceImage}=load('../app/components/SourceImage.tsx',{
 react:{useState:()=>[failed,v=>{failed=v;}]},'next/image':{default:()=>null},
 '@/app/lib/sourceImages':{sourceImageUrl},'./SourceImage.module.css':{default:{}}
});
const props={title:'합성 프로그램',locale:'ko',variant:'detail'};
assert.equal(SourceImage(props),null);
assert.equal(SourceImage({...props,url:'http://global.seoul.go.kr/unsafe.jpg'}),null);
const url='https://global.seoul.go.kr/synthetic-poster.jpg';
const figure=SourceImage({...props,url});
assert.equal(figure.type,'figure');
const image=figure.props.children[0].props.children[0];
assert.equal(image.props.src,url);assert.equal(image.props.unoptimized,true);
assert.equal(image.props.referrerPolicy,'no-referrer');
image.props.onError();assert.equal(SourceImage({...props,url}),null);
assert.notEqual(SourceImage({...props,url:'https://global.seoul.go.kr/changed.jpg'}),null);
console.log('Existing source image fallback: 8 checks passed; injected state only, no live image request.');
