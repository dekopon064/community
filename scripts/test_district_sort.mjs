// Local selection vocabulary and real admin rendering only; no DB, Auth or AI.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const root=fileURLToPath(new URL('../',import.meta.url)),cache=new Map();
globalThis.fetch=()=>{throw Error('external_network_forbidden');};
function load(relative){
 const file=path.resolve(root,relative);if(cache.has(file))return cache.get(file);
 const exports={};cache.set(file,exports);
 const code=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 new Function('require','exports',code)(s=>{
  if(s.startsWith('@/')||s.startsWith('.')){const target=s.startsWith('@/')?path.join(root,s.slice(2)):path.resolve(path.dirname(file),s);for(const ext of ['.ts','.tsx',''])if(fs.existsSync(target+ext))return load(path.relative(root,target+ext));}
  return require(s);
 },exports);return exports;
}
const cf=load('app/lib/contentFilters.ts'),sort=load('app/lib/districtSort.ts');
const readings=load('app/lib/districtJapaneseReadings.ts').default;
const pub=load('app/lib/publicContentFilters.ts');
const admin=load('app/components/admin/FilterReviewPanel.tsx');
const classification=load('app/lib/review/classification.ts');
const messages=JSON.parse(fs.readFileSync(path.join(root,'messages/ja.json'),'utf8'));
const glossary=fs.readFileSync(path.join(root,'docs/ingest-inputs/region_ja_glossary.v1.yaml'),'utf8');
const parents={'11':'서울특별시','41':'경기도','28':'인천광역시'};
let checks=0,coverage=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;},ok=v=>{assert(v);checks++;};
const original=JSON.stringify(cf.districtChoices);
eq(sort.sortedDistrictChoices('11','ko'),['강남구','강동구','강북구','강서구','관악구','광진구','구로구','금천구','노원구','도봉구','동대문구','동작구','마포구','서대문구','서초구','성동구','성북구','송파구','양천구','영등포구','용산구','은평구','종로구','중구','중랑구']);
eq(sort.sortDistrictNames(['강북구','관악구','강남구','구로구','강서구','은평구','광진구','강동구','금천구'],'ja',readings['11']),['은평구','강서구','강동구','강남구','강북구','관악구','광진구','금천구','구로구']);
// Hanzi labels put 城南 before 水原, whereas スウォン precedes ソンナム.
ok(new Intl.Collator('ja').compare('城南市','水原市')<0);
eq(sort.sortDistrictNames(['성남시','수원시'],'ja',readings['41']),['수원시','성남시']);
eq(sort.sortDistrictNames(['나','가'],'ja',{가:'かな',나:'かな'}),['가','나']);
eq(sort.sortDistrictNames(['나','확인됨','가'],'ja',{확인됨:'あ'}),['확인됨','가','나']);
eq(sort.sortDistrictNames(['나','가'],'ja'),['가','나']);
eq(sort.sortedDistrictChoices('invalid','ja'),[]);
for(const province of Object.keys(cf.provinceLabels)){
 const names=cf.districtChoices[province];eq(Object.keys(readings[province]).sort(),[...names].sort());
 eq(Object.keys(messages.PublicFilters.districts[province]).sort(),[...names].sort());
 for(const name of names){
  coverage++;ok(/^[ぁ-ゖー]+$/.test(readings[province][name]));
  if(province==='28'&&name==='서구'){eq(readings[province][name],'そ');continue;}
  const entry=[...glossary.matchAll(/- \{parent_ko: ([^,]+), ko: ([^,]+), level: [^,]+, ja: ([^,]+), status: active\}/g)].filter(x=>x[1]===parents[province]&&x[2]===name);
  eq(entry.length,1);
  eq(readings[province][name],entry[0][3].slice(0,-1).replace(/[ァ-ヶ]/g,c=>String.fromCharCode(c.charCodeAt(0)-0x60)));
 }
 for(const locale of ['ko','ja']){
  const result=sort.sortedDistrictChoices(province,locale);eq([...result].sort(),[...names].sort());eq(new Set(result).size,names.length);
  eq(sort.sortedDistrictChoices(province,locale),result);ok(result!==names);
 }
 const location={status:'known',value:{scope:'specific',venues:[{province,district:names[0],facility:'',address:''}]}};
 const data={...cf.emptyContentFilters('program'),location};const before=JSON.stringify(data);
 const html=renderToStaticMarkup(React.createElement(admin.FilterInputs,{data,fields:['location'],onChange:()=>{throw Error('unexpected_edit');},disabled:false,missing:[]}));
 const selected=html.match(/<select[^>]*>[\s\S]*?<\/select>/g).find(x=>x.includes('시·군·구')===false&&x.includes(names[0]));
 // The district select keeps its Korean values while only options move.
 const options=[...selected.matchAll(/<option[^>]*>([^<]*)<\/option>/g)].map(x=>x[1]).slice(1);
 eq(options,sort.sortedDistrictChoices(province,'ko'));ok(selected.includes(`selected="">${names[0]}</option>`));eq(JSON.stringify(data),before);
 const query=pub.readExplorationQuery(new URLSearchParams(`region=${province}&district=${province}:${names[0]}&foreigner=other`),'program');
 eq(query.districts,[`${province}:${names[0]}`]);eq(query.foreignerPrograms,['other']);
 const written=pub.writeExplorationQuery(new URLSearchParams('unrelated=kept'),query,'program');
 eq(pub.readExplorationQuery(written,'program'),query);eq(written.get('unrelated'),'kept');
 const saved={schema:cf.contentFilterSchema,revision:'a'.repeat(64),filterVersion:7,data,missing:[],origins:{}};
 const body=admin.filterSaveBody(saved,'b'.repeat(64),structuredClone(data),['location']);
 eq(body.filterVersion,7);eq(body.revision,saved.revision);eq(body.data.location,location);
 const classified=classification.classificationFields('program');ok(classified.includes('location'));
}
eq(JSON.stringify(cf.districtChoices),original);eq(coverage,67);
console.log(JSON.stringify({checks,result:'passed',readings:coverage,missingReadings:0,externalConnections:0}));
