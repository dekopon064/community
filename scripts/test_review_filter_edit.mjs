// Synthetic selections and the actual panel's handlers. All fetches are denied
// unless explicitly supplied below; no environment file, Auth, DB or AI.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url), ts = require('typescript'), React = require('react');
const root = fileURLToPath(new URL('../', import.meta.url));
let states = [], refs = [], cursor = 0, refCursor = 0;
const fakeReact = { ...React, useState(initial) { const i = cursor++; if (!(i in states)) states[i] = typeof initial === 'function' ? initial() : initial; return [states[i], value => { states[i] = typeof value === 'function' ? value(states[i]) : value; }]; }, useEffect() {}, useRef(initial) { return refs[refCursor++] ??= { current: initial }; } };
const cache = new Map();
function load(name) {
  const filename = path.resolve(root, name);
  if (cache.has(filename)) return cache.get(filename);
  const exports = {}; cache.set(filename, exports);
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
  new Function('require', 'exports', code)(s => {
    if (s === 'react') return fakeReact;
    if (s === 'next/link') return { default: () => null };
    if (s.startsWith('@/') || s.startsWith('.')) {
      const target = s.startsWith('@/') ? path.join(root, s.slice(2)) : path.resolve(path.dirname(filename), s);
      for (const suffix of ['.ts', '.tsx', '']) if (fs.existsSync(target + suffix)) return load(path.relative(root, target + suffix));
    }
    return require(s);
  }, exports);
  return exports;
}
let checks = 0;
const eq = (a, b) => { assert.deepEqual(a, b); checks++; };
const ok = a => { assert.ok(a); checks++; };

const {SavedFilterValues,confirmedFilterFields,changedFilterFields,FilterInputs}=load('app/components/admin/FilterReviewPanel.tsx');
const {ReviewStatus}=load('app/components/admin/ReviewStates.tsx');
const known=value=>({status:'known',value}),na={status:'not_applicable',value:null};
const saved={schema:'content-filters-v1',category:'program',topic:known('culture_experience'),location:known({scope:'specific',venues:[{province:'11',district:'강서구',facility:'',address:''}]}),delivery:known('onsite'),audience:known('other'),spaceKind:na,application:known({deadlineKind:'none',start:null,end:null,sourceStatus:'unknown'}),schedule:na};
const info={schema:saved.schema,revision:'a'.repeat(64),filterVersion:1,data:saved,missing:[],origins:{topic:'operator',location:'confirmed_facts',delivery:'automatic',audience:'source_change'}};
const nodes = tree => !tree || typeof tree !== 'object' ? [] : [tree,...React.Children.toArray(tree.props?.children).flatMap(nodes)];
const text = tree => typeof tree === 'string' || typeof tree === 'number' ? String(tree) : React.Children.toArray(tree?.props?.children).map(text).join('');
let writes=0,applied=[],active=null,data,version;
globalThis.fetch=async()=>{writes++;throw Error('Network forbidden');};
const render=()=>{cursor=0;refCursor=0;return SavedFilterValues({saved,data,onChange:v=>{applied.push(v);data=v;},disabled:false,missing:[],confirmed:confirmedFilterFields(info),version,onEditing:v=>{active=v;}});};
const reset=()=>{states=[];refs=[];data=structuredClone(saved);version='b'.repeat(64);applied=[];active=null;};
const button=name=>{const n=nodes(render()).find(n=>n.type==='button'&&(n.props['aria-label']===name||text(n)===name));assert.ok(n,name);return n;};
const edit=value=>nodes(render()).find(n=>n.type===FilterInputs).props.onChange(value);
// Individual saved confirmation is independent of other pending fields; source observations never count as operator confirmation.
eq(confirmedFilterFields(info),['topic','location']);
eq(confirmedFilterFields({...info,missing:['location']}),['topic']);
ok(text(ReviewStatus({needed:false,confirmed:true,changed:false})).includes('확인됨'));
ok(!text(ReviewStatus({needed:false,confirmed:true,changed:true})).includes('확인됨'));
ok(text(ReviewStatus({needed:true,confirmed:true,changed:false})).includes('확인 필요'));
reset();ok(nodes(render()).some(n=>n.type==='summary'&&text(n)==='현재 저장값 확인·수정'));
// Values are shown once until changed. Opening and editing do not mutate the parent or perform writes.
eq(nodes(render()).filter(n=>n.type==='p'&&text(n).startsWith('변경할 값:')).length,0);
button('대표 분야 수정').props.onClick();eq(active,'topic');eq(nodes(render()).filter(n=>n.type===FilterInputs).length,1);
edit({...saved,topic:known('language_learning')});eq(data,saved);eq(applied.length,0);
button('취소').props.onClick();eq(data,saved);eq(active,null);eq(applied.length,0);
button('대표 분야 수정').props.onClick();edit({...saved,topic:known('language_learning')});button('변경 적용').props.onClick();eq(applied.length,1);eq(data.topic,known('language_learning'));eq(active,null);eq(changedFilterFields(saved,data),['topic']);
eq(nodes(render()).filter(n=>n.type==='p'&&text(n).startsWith('변경할 값:')).length,1);
// Cancel preserves a previously applied unsaved draft rather than resetting to the server value.
button('대표 분야 수정').props.onClick();edit({...data,topic:known('employment_job')});button('취소').props.onClick();eq(data.topic,known('language_learning'));
// Coupled delivery/location changes are both submitted in the existing save contract.
reset();button('진행 방식 수정').props.onClick();edit({...saved,delivery:known('online'),location:na});button('변경 적용').props.onClick();eq(changedFilterFields(saved,data),['delivery','location']);eq(data.location,na);
// Invalid partial input is retained and never copied to the parent.
reset();button('개최 지역 수정').props.onClick();edit({...saved,location:known({scope:'specific',venues:[{province:'',district:null,facility:'',address:''}]})});button('변경 적용').props.onClick();eq(applied.length,0);eq(active,'location');ok(nodes(render()).some(n=>n.props?.role==='alert'));eq(states[1].location.value.venues[0].province,'');
// Version changes and unfinished recurrence prevent applying an old edit.
reset();button('대표 분야 수정').props.onClick();edit({...saved,topic:known('language_learning')});version='c'.repeat(64);eq(button('변경 적용').props.disabled,true);eq(applied.length,0);ok(nodes(render()).some(n=>n.props?.role==='alert'&&text(n).includes('저장 버전')));
reset();button('신청 기간·마감 수정').props.onClick();nodes(render()).find(n=>n.type===FilterInputs).props.onPending(true);eq(button('변경 적용').props.disabled,true);
reset();button('대표 분야 수정').props.onClick();let stopped=false;nodes(render()).find(n=>n.props?.role==='group').props.onKeyDown({key:'Escape',preventDefault(){},stopPropagation(){stopped=true;}});eq(active,null);ok(stopped);eq(applied.length,0);
// The warning heading is wholly inside a flat strip; its actual legend is screen-reader only.
const input=FilterInputs({data:saved,fields:['location'],onChange(){},disabled:false,missing:['location']});
eq(nodes(input).find(n=>n.type==='legend').props.className,'sr-only');ok(nodes(input).some(n=>n.type==='div'&&String(n.props.className).includes('bg-[#fff3c4]')));ok(!String(nodes(input).find(n=>n.type==='fieldset').props.className).includes('bg-'));
eq(writes,0);
console.log(JSON.stringify({checks,result:'passed',syntheticOnly:true,externalConnections:0}));
