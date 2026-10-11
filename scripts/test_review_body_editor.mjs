// Offline: real candidate/save-handler regression installs the TS loader and
// rejects external fetches. These cases exercise actual source-range editing.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
await import('./test_generated_body_candidate.mjs');
const {readEditor,replaceInline,selectedInline,inlineText,changeList,tableRow,safeLink}=await import('../app/lib/review/body-editor.ts');
const {domInline,writeInline}=await import('../app/lib/review/body-editor-dom.ts');
const {CandidateEditor}=await import('../app/components/admin/ReviewEditors.tsx');
const {default:CurationBody}=await import('../app/components/CurationBody.tsx');
const {LocalReviewStore}=await import('../app/lib/review/local-fixture.ts');
const {reviewDetail}=await import('../app/lib/review/handlers.ts');
const {ReviewFailure}=await import('../app/lib/review/contracts.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const text=value=>[{type:'text',value}];
const body='[한 줄 요약]\n합성 시험입니다.\n\n[기간·상태]\n기간: 2026-10-03 ~ 2026-10-10\n\n| 회차 | 일시 | 활동 |\n| :--- | --- | ---: |\n| 1회차 | 10월 3일 10:00~11:30 | 문서 작성 |\n| 2회차 | 10월 10일 14:00~15:30 | 문서 제출 |\n\n[주요 내용]\n**보호자 동반 필수**. 수강료 10,000원; 재료비 2,000원.\n\n1. 작성\n2. 제출\n\n[신청 방법]\n[신청](https://synthetic.invalid/apply?id=1 "공식 링크")';
const candidate={titleKo:'합성',titleJa:'合成',summaryKo:'요약',summaryJa:'要約',contentKo:body,contentJa:'[要約]\n合成です。\n[日程案内]\n2026-10-03 ~ 2026-10-10\n[主な内容]\n**保護者同伴必須**\n\n| 回 | 日時 | 活動 |\n| --- | --- | --- |\n| 第1回 | 10月3日10時～11時 | 文書作成 |'};
test('opening/no-op preserves bytes, aliases, amounts, constraints, dates',()=>{
 const m=readEditor(body,'ko');assert.equal(m.error,undefined);assert.equal(m.segments[1].heading,'일정 안내');
 for(const leaf of m.leaves)assert.equal(replaceInline(body,leaf,leaf.children),body);
});
test('cell edit splices only activity range; dates, other rows, alignment stay exact',()=>{
 const m=readEditor(body,'ko'),leaf=m.leaves.find(l=>l.cell&&l.row===1&&l.column===2);
 const next=replaceInline(body,leaf,text('문서 작성 실습'));
 assert.equal(next,body.slice(0,leaf.start)+'문서 작성 실습'+body.slice(leaf.end));
 assert.equal(readEditor(next,'ko').tables[0].node.align[2],'right');
 assert.equal(readEditor(next,'ko').leaves.find(l=>l.cell&&l.row===2&&l.column===2).raw,'문서 제출');
});
test('cell pipes cannot create columns and multiline is rejected',()=>{
 const m=readEditor(body,'ko'),leaf=m.leaves.find(l=>l.cell&&l.row===1&&l.column===2);
 const n=readEditor(replaceInline(body,leaf,text('작성 | 제출')),'ko');
 assert.equal(n.tables[0].node.children[1].children.length,3);
 assert.equal(inlineText(n.leaves.find(l=>l.cell&&l.row===1&&l.column===2).children),'작성 | 제출');
 assert.throws(()=>replaceInline(body,leaf,text('작성\n제출')),/한 줄/);
});
test('table insertion is blank; explicit deletion preserves other rows/header',()=>{
 const m=readEditor(body,'ko'),table=m.tables[0];
 const added=tableRow(body,table,1,'insert'),a=readEditor(added,'ko');
 assert.equal(a.tables[0].node.children.length,4);
 assert.ok(a.tables[0].node.children[2].children.every(c=>c.children.length===0));
 assert.equal(inlineText(a.tables[0].node.children[3].children[2].children),'문서 제출');
 const removed=readEditor(tableRow(added,a.tables[0],2,'delete'),'ko');
 assert.equal(removed.tables[0].node.children.length,3);
 assert.throws(()=>tableRow(body,table,0,'delete'),/머리글/);
});
test('empty table cell writable range keeps delimiters',()=>{
 const input='| A | B |\n| --- | --- |\n| | |',m=readEditor(input,'ko');
 for(let col=0;col<2;col++){
  const edited=readEditor(replaceInline(input,m.leaves.find(l=>l.row===1&&l.column===col),text('새 값')),'ko');
  assert.equal(edited.tables[0].node.children[1].children.length,2);
  assert.equal(inlineText(edited.tables[0].node.children[1].children[col].children),'새 값');
 }
});
test('partial strong toggling preserves text and outside source',()=>{
 const input='앞 **중요 조건** 뒤\n\n다른 문단',leaf=readEditor(input,'ko').leaves[0];
 const bold=replaceInline(input,leaf,selectedInline(leaf.children,0,1,{bold:true}));
 assert.ok(bold.startsWith('**앞**'));assert.ok(bold.endsWith('\n\n다른 문단'));
 const plain=replaceInline(input,leaf,selectedInline(leaf.children,2,7,{bold:false}));
 assert.equal(inlineText(readEditor(plain,'ko').leaves[0].children),'앞 중요 조건 뒤');
});
test('safe link edit/removal retains labels; dangerous schemes rejected',()=>{
 const input='[안내](https://synthetic.invalid/a?id=1 "원문")',leaf=readEditor(input,'ko').leaves[0];
 const linked=replaceInline(input,leaf,selectedInline(leaf.children,0,2,{text:'신청',url:'https://synthetic.invalid/b?id=2'}));
 assert.equal(readEditor(linked,'ko').leaves[0].children[0].url,'https://synthetic.invalid/b?id=2');
 assert.equal(replaceInline(input,leaf,selectedInline(leaf.children,0,2,{url:null})),'안내');
 for(const url of ['javascript:alert(1)','data:text/html,test','/relative','https://a\nX'])assert.equal(safeLink(url),false);
 assert.throws(()=>replaceInline(input,leaf,[{type:'link',url:'javascript:x',children:text('안내')}]),/서식/);
});
test('nested/numbered list edits keep order and outside source',()=>{
 const input='앞\n\n3. 첫째\n4. 둘째\n   - 내부\n\n뒤',m=readEditor(input,'ko');
 const leaf=m.leaves.find(l=>inlineText(l.children)==='둘째');
 const n=replaceInline(input,leaf,text('둘째 수정'));
 assert.ok(n.includes('3. 첫째\n4. 둘째 수정\n   - 내부'));assert.ok(n.endsWith('\n\n뒤'));
 const bulleted=changeList(input,leaf,false);assert.ok(bulleted.includes('- 첫째'));assert.ok(bulleted.includes('내부'));
 assert.ok(bulleted.startsWith('앞\n\n')&&bulleted.endsWith('\n\n뒤'));
});
test('paragraph/list conversion and heading delimiters preserve content',()=>{
 const input='문단\n\n뒤',leaf=readEditor(input,'ko').leaves[0];
 const list=changeList(input,leaf,true);assert.ok(list.startsWith('1. 문단'));
 const back=changeList(list,readEditor(list,'ko').leaves[0],true);assert.equal(back,input);
 const h='## 제목 ##\n\n뒤',hl=readEditor(h,'ko').leaves[0];
 assert.equal(replaceInline(h,hl,text('새 제목')),'## 새 제목 ##\n\n뒤');
});
test('multiline insertion and nested list conversion keep block/list boundaries',()=>{
 const input='- 외부\n  - 내부 첫째\n  - 내부 둘째\n\n뒤',m=readEditor(input,'ko');
 const inner=m.leaves.find(l=>inlineText(l.children)==='내부 첫째');
 const expanded=replaceInline(input,inner,selectedInline(inner.children,0,inlineText(inner.children).length,{text:'첫 줄\n\n둘째 줄'}));
 const parsed=readEditor(expanded,'ko');assert.equal(parsed.error,undefined);
 assert.equal(parsed.segments[0].blocks.length,2);assert.equal(parsed.leaves.length,4);
 assert.equal(inlineText(parsed.leaves[1].children),'첫 줄\n\n둘째 줄');
 const numbered=readEditor(changeList(input,inner,true),'ko');
 assert.equal(numbered.segments[0].blocks.length,2);
 assert.ok(numbered.leaves.some(l=>inlineText(l.children)==='내부 둘째'&&l.list.ordered));
});
test('ragged tables and inline section markers use raw fallback without corruption',()=>{
 for(const input of ['| A | B |\n| --- | --- |\n| one |','| A | B |\n| --- | --- |\n| one | two | three |','[한 줄 요약] 요약\n[주요 내용] 설명']){
  assert.ok(readEditor(input,'ko').error,input);assert.equal(readEditor(input,'ko').source,input);
 }
});
test('unsupported syntax is retained as raw, never silently converted',()=>{
 for(const input of ['<script>alert(1)</script>','![이미지](https://synthetic.invalid/a)','`code`','> 인용','- [x] 완료','~~취소~~','[ref][id]\n\n[id]: https://synthetic.invalid']){
  const m=readEditor(input,'ko');assert.ok(m.error,input);assert.equal(m.source,input);
 }
 const input='<script>alert(1)</script>';
 const html=renderToStaticMarkup(createElement(CandidateEditor,{value:{...candidate,contentKo:input},formattedBody:true,onChange:()=>{},errors:{},disabled:false}));
 assert.ok(!html.includes('<script>'));assert.ok(html.includes('&lt;script&gt;'));assert.ok(html.includes('한국어 상세 원문'));
});
test('both locale editors expose public formatting and keep title/summary textareas',()=>{
 const html=renderToStaticMarkup(createElement(CandidateEditor,{value:candidate,formattedBody:true,onChange:()=>{},errors:{},disabled:false}));
 assert.equal((html.match(/contenteditable="true"/gi)||[]).length,readEditor(body,'ko').leaves.length+readEditor(candidate.contentJa,'ja').leaves.length);
 assert.equal((html.match(/<textarea/g)||[]).length,4);assert.equal((html.match(/<table/g)||[]).length,2);
 assert.ok(html.includes('한국어 상세 표 1행 2열')&&html.includes('일본어 상세 표 1행 2열'));
 assert.ok(html.includes('<strong')&&html.includes('<ol'));assert.ok(!html.includes('[기간·상태]'));
 const locked=renderToStaticMarkup(createElement(CandidateEditor,{value:candidate,formattedBody:true,onChange:()=>{},errors:{},disabled:true}));
 assert.ok(!/contenteditable="true"/i.test(locked));assert.ok(locked.includes('aria-disabled="true"'));
 const publicHTML=renderToStaticMarkup(createElement(CurationBody,{content:body,locale:'ko'}));assert.equal((publicHTML.match(/<table/g)||[]).length,1);
});
test('DOM extractor accepts whitelisted inline nodes, rejects unsafe DOM without saving HTML',()=>{
 const leaf=value=>({nodeType:3,textContent:value}),element=(tag,children=[],href=null)=>({nodeType:1,tagName:tag,childNodes:children,getAttribute:k=>k==='href'?href:null});
 assert.equal(inlineText(domInline(element('SPAN',[leaf('앞'),element('STRONG',[leaf('조건')]),element('BR'),leaf('뒤')]))),'앞조건\n뒤');
 assert.throws(()=>domInline(element('SPAN',[element('SCRIPT')])),/붙여넣기/);
 assert.throws(()=>domInline(element('SPAN',[element('A',[leaf('링크')],'javascript:bad')])),/https/);
 const doc={createTextNode:leaf,createElement:tag=>({tag,children:[],setAttribute(){},appendChild(c){this.children.push(c);}})};
 const root={ownerDocument:doc,replaceChildren(...nodes){this.nodes=nodes;}};
 writeInline(root,[{type:'strong',children:text('<script>literal</script>')}]);
 assert.equal(root.nodes[0].tag,'strong');assert.equal(root.nodes[0].children[0].textContent,'<script>literal</script>');
});
test('edited Markdown uses existing save/version contract; stale save rejected with history intact',async()=>{
 const store=new LocalReviewStore(),id='20000000-0000-4000-8000-000000000001',actor='00000000-0000-4000-8000-000000000001';
 const initial=await store.get('candidates',id),m=readEditor(body,'ko');
 const edited={...candidate,contentKo:replaceInline(body,m.leaves.find(l=>l.cell&&l.row===1&&l.column===2),text('문서 작성 실습'))};
 const command={action:'save_candidate',content:edited,version:initial.version,revision:initial.revision};
 const request=()=>new Request('http://localhost/api/admin/review/candidates/'+id,{method:'POST',headers:{origin:'http://localhost','content-type':'application/json'},body:JSON.stringify(command)});
 const deps={authorize:async()=>({userId:actor}),store:()=>store};
 const saved=await reviewDetail(request(),'candidates',id,deps);assert.equal(saved.status,200);
 const current=await store.get('candidates',id);assert.deepEqual(current.content,edited);assert.equal(current.history.length,1);
 const stale=await reviewDetail(request(),'candidates',id,deps);assert.equal(stale.status,409);
 assert.equal((await store.get('candidates',id)).history.length,1);assert.deepEqual(edited.contentKo,command.content.contentKo);
});
test('unknown response and expired auth do not retry or complete another write',async()=>{
 const store=new LocalReviewStore(),id='20000000-0000-4000-8000-000000000001',item=await store.get('candidates',id);let calls=0;
 const request=()=>new Request('http://localhost/api/admin/review/candidates/'+id,{method:'POST',headers:{origin:'http://localhost','content-type':'application/json'},body:JSON.stringify({action:'save_candidate',content:candidate,version:item.version,revision:item.revision})});
 const unavailable=await reviewDetail(request(),'candidates',id,{authorize:async()=>({userId:'00000000-0000-4000-8000-000000000001'}),store:()=>({...store,execute:async()=>{calls++;throw new ReviewFailure('unavailable');}})});
 assert.equal(unavailable.status,503);assert.equal(calls,1);
 const expired=await reviewDetail(request(),'candidates',id,{authorize:async()=>{throw new AdminAccessError('signed_out')},store:()=>{throw Error('store must not be touched')}});
 assert.equal(expired.status,401);assert.equal(calls,1);assert.ok(expired.headers.get('cache-control').includes('no-store'));
});
