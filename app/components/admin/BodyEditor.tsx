"use client";
import { createElement, useLayoutEffect, useMemo, useRef, useState, type ElementType, type ReactNode } from 'react';
import { markdownComponents } from '../Markdown';
import { readEditor, replaceInline, selectedInline, inlineText, inlineTokens, changeList, tableRow, safeLink,
  type Inline, type Leaf, type Block } from '../../lib/review/body-editor';
import { domInline, writeInline, selectionOffsets, restoreSelection } from '../../lib/review/body-editor-dom';

type Selection = {id:string;from:number;to:number};
const button='min-h-11 rounded-lg border border-info-rule px-3 py-2 text-sm font-semibold text-ink hover:bg-info-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-45';
function styled(tag:keyof typeof markdownComponents,key:string,children:ReactNode,props:Record<string,unknown>={}) {
  return createElement((markdownComponents[tag]??tag) as ElementType,{key,...props},children);
}
function inlineView(nodes:Inline[]):ReactNode {
  return nodes.map((n,i)=>n.type==='text'?n.value:n.type==='break'?<br key={i}/>:
    n.type==='strong'?styled('strong',String(i),inlineView(n.children)):
    n.type==='emphasis'?styled('em',String(i),inlineView(n.children)):
    n.type==='link'?styled('a',String(i),inlineView(n.children),{href:n.url,title:n.title}):null);
}

function InlineEditor({leaf,label,disabled,invalid,description,composing,onComposition,onEdit,onSelection,pending,onUndo,onRedo,onError}:
  {leaf:Leaf;label:string;disabled:boolean;invalid:boolean;description:string;composing:boolean;onComposition:(value:boolean)=>void;
   onEdit:(leaf:Leaf,nodes:Inline[])=>string|undefined;onSelection:(selection:Selection)=>void;
   pending:Selection|null;onUndo:()=>void;onRedo:()=>void;onError:(message:string)=>void}) {
  const root=useRef<HTMLSpanElement>(null),[initial]=useState(()=>leaf.children),published=useRef(leaf.raw);
  const previousDisabled=useRef(disabled),composition=useRef(false);
  useLayoutEffect(()=>{
    const element=root.current;
    if(element&&(published.current!==leaf.raw||previousDisabled.current!==disabled)){
      writeInline(element,leaf.children);published.current=leaf.raw;
    }
    if(element&&!disabled&&pending?.id===leaf.id)restoreSelection(element,pending.from,pending.to);
    previousDisabled.current=disabled;
  },[leaf.raw,leaf.children,leaf.id,disabled,pending]);
  const selected=()=>{const s=root.current&&selectionOffsets(root.current);if(s)onSelection({id:leaf.id,...s});};
  const publish=()=>{
    if(!root.current||composition.current||disabled)return;
    try{
      const raw=onEdit(leaf,domInline(root.current));
      if(raw!==undefined)published.current=raw;
      selected();
    }catch(e){onError(e instanceof Error?e.message:'입력을 확인해 주세요.');writeInline(root.current,leaf.children);restoreSelection(root.current,inlineText(leaf.children).length);}
  };
  const insert=(text:string)=>{
    if(!root.current||disabled||composition.current)return;
    const s=selectionOffsets(root.current);
    if(!s)return;
    if(leaf.cell&&/[\r\n]/.test(text)){onError('표 셀은 한 줄로 입력해 주세요. 여러 행은 원문 편집을 사용해 주세요.');return;}
    const nodes=selectedInline(domInline(root.current),s.from,s.to,{text:text.replace(/\r\n?/g,'\n')});
    writeInline(root.current,nodes);restoreSelection(root.current,s.from+text.replace(/\r\n?/g,'\n').length);publish();
  };
  return <span ref={root} data-editor-leaf={leaf.id} contentEditable={!disabled} suppressContentEditableWarning
    role="textbox" aria-label={label} aria-multiline={!leaf.cell} aria-disabled={disabled}
    aria-invalid={invalid} aria-describedby={description}
    tabIndex={disabled?-1:0} spellCheck={false}
    className="inline-block min-h-8 w-full min-w-0 align-top whitespace-pre-wrap break-words rounded-sm caret-ink focus:outline-2 focus:outline-offset-2 focus:outline-focus selection:bg-mineral selection:text-ink"
    onFocus={selected} onMouseUp={selected} onKeyUp={selected} onInput={publish}
    onCompositionStart={()=>{composition.current=true;onComposition(true);}}
    onCompositionEnd={()=>{composition.current=false;onComposition(false);publish();}}
    onClick={event=>{if((event.target as Element).closest('a'))event.preventDefault();}}
    onPaste={event=>{event.preventDefault();insert(event.clipboardData.getData('text/plain'));}}
    onDrop={event=>{event.preventDefault();onError('파일과 HTML 끌어놓기는 지원하지 않습니다. 텍스트를 붙여넣어 주세요.');}}
    onBeforeInput={event=>{
      const input=event.nativeEvent as InputEvent;
      if(disabled){event.preventDefault();return;}
      if(input.inputType==='historyUndo'||input.inputType==='historyRedo'){
        event.preventDefault();if(input.inputType==='historyUndo')onUndo();else onRedo();return;
      }
      if(input.inputType==='insertParagraph'||input.inputType==='insertLineBreak'){
        event.preventDefault();if(!leaf.cell)insert('\n');
      }
    }}
    onKeyDown={event=>{
      if(composing||event.nativeEvent.isComposing)return;
      if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'){
        event.preventDefault();if(event.shiftKey)onRedo();else onUndo();
      } else if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='y'){event.preventDefault();onRedo();}
      else if(event.key==='Enter'){event.preventDefault();if(!leaf.cell)insert('\n');}
    }}>{inlineView(initial)}</span>;
}

export default function BodyEditor({id,label,locale,value,onChange,disabled,error}:{id:string;label:string;locale:string;
  value:string;onChange:(next:string)=>void;disabled:boolean;error?:string}) {
  const model=useMemo(()=>readEditor(value,locale),[value,locale]);
  const [raw,setRaw]=useState(false),[selection,setSelection]=useState<Selection|null>(null),[composing,setComposing]=useState(false);
  const [message,setMessage]=useState(''),[link,setLink]=useState<{text:string;url:string}|null>(null);
  const [history,setHistory]=useState({entries:[value],index:0,published:value}),[pending,setPending]=useState<Selection|null>(null);
  const modeButton=useRef<HTMLButtonElement>(null),source=useRef<HTMLTextAreaElement>(null);
  const view=useRef<HTMLDivElement>(null);
  if(value!==history.published){setHistory({entries:[value],index:0,published:value});setPending(null);}
  const rawMode=raw||Boolean(model.error);
  const previousMode=useRef(rawMode);
  useLayoutEffect(()=>{
    if(previousMode.current!==rawMode&&!disabled){
      if(rawMode)source.current?.focus();else view.current?.querySelector<HTMLElement>('[data-editor-leaf]')?.focus();
    }
    previousMode.current=rawMode;
  },[rawMode,disabled]);
  const active=model.leaves.find(l=>l.id===selection?.id);
  function commit(next:string,focus:Selection|null=selection){
    if(disabled)return;
    if(next.length>200000)throw Error('상세 본문은 200,000자 이내로 입력해 주세요.');
    if(next===value)return;
    const entries=[...history.entries.slice(0,history.index+1),next].slice(-100);
    setHistory({entries,index:entries.length-1,published:next});setPending(focus);onChange(next);setMessage('');
  }
  function travel(direction:number){
    if(disabled||composing)return;
    const next=history.index+direction;
    if(next<0||next>=history.entries.length)return;
    setHistory({...history,index:next,published:history.entries[next]});setPending(selection);
    onChange(history.entries[next]);setMessage('');
  }
  function edit(leaf:Leaf,nodes:Inline[]){
    if(disabled)return;
    const next=replaceInline(value,leaf,nodes);
    commit(next,{id:leaf.id,from:inlineText(nodes).length,to:inlineText(nodes).length});
    return readEditor(next,locale).leaves.find(l=>l.id===leaf.id)?.raw;
  }
  function action(run:()=>void){try{run();}catch(e){setMessage(e instanceof Error?e.message:'입력을 확인해 주세요.');}}
  function focusCurrent(){
    const span=active&&view.current?.querySelector<HTMLElement>(`[data-editor-leaf="${active.id}"]`);
    if(span&&selection)restoreSelection(span,selection.from,selection.to);
  }
  function mark(){
    if(!active||!selection||selection.from===selection.to)return;
    let offset=0;
    const selected=inlineTokens(active.children).filter(t=>{const from=offset;offset+=t.text.length;return offset>selection.from&&from<selection.to;});
    const nodes=selectedInline(active.children,selection.from,selection.to,{bold:!selected.every(t=>t.bold)});
    commit(replaceInline(value,active,nodes),selection);
  }
  function list(ordered:boolean){
    if(!active)return;
    const i=model.leaves.indexOf(active),next=changeList(value,active,ordered),target=readEditor(next,locale).leaves[i];
    commit(next,target?{id:target.id,from:0,to:0}:null);
  }
  function openLink(){
    if(!active||!selection)return;
    let from=selection.from,to=selection.to,offset=0,url='';
    const tokens=inlineTokens(active.children);
    for(const t of tokens){const end=offset+t.text.length;
      if(from===to&&from>=offset&&from<=end&&t.url){from=offset;to=end;url=t.url;break;}
      if(from>=offset&&from<end)url=t.url??'';offset=end;
    }
    if(from===to){setMessage('링크로 사용할 문구를 선택해 주세요.');return;}
    setSelection({id:active.id,from,to});setLink({text:inlineText(active.children).slice(from,to),url});
  }
  function row(id:string,action:'insert'|'delete'){
    const table=model.tables.find(t=>t.id===id);if(!table)return;
    const current=active?.table===id?active.row??0:table.node.children.length-1;
    const next=tableRow(value,table,current,action),nextModel=readEditor(next,locale);
    const target=nextModel.leaves.find(l=>l.table===id&&l.row===(action==='insert'?current+1:Math.max(1,current-1)));
    commit(next,target?{id:target.id,from:0,to:0}:null);
  }
  const locked=disabled||composing;
  const leafView=(leaf:Leaf)=> <InlineEditor key={leaf.id} leaf={leaf}
    label={leaf.cell?`${label} 표 ${leaf.row===0?'머리글':`${leaf.row}행`} ${(leaf.column??0)+1}열`:`${label} 문단 ${model.leaves.indexOf(leaf)+1}`}
    disabled={disabled} invalid={Boolean(error)} description={`${id}-help${error?` ${id}-error`:''}`} composing={composing} onComposition={setComposing} onEdit={edit}
    onSelection={s=>{setSelection(s);setPending(null);}} pending={pending}
    onUndo={()=>travel(-1)} onRedo={()=>travel(1)} onError={setMessage}/>;
  function renderBlock(block:Block):ReactNode {
    const n=block.node;
    if(n.type==='paragraph')return styled('p',block.id,leafView(block.leaves[0]));
    if(n.type==='heading')return styled(('h'+n.depth) as keyof typeof markdownComponents,block.id,leafView(block.leaves[0]));
    if(n.type==='list')return styled(n.ordered?'ol':'ul',block.id,block.nested.map(item=>styled('li',item.id,item.nested.map(child=>
      child.node.type==='paragraph'&&!n.spread?leafView(child.leaves[0]):renderBlock(child)))),{start:n.ordered?n.start:undefined});
    if(n.type==='table')return <div key={block.id}>
      {styled('table',block.id,<><thead><tr>{n.children[0].children.map((_,j)=><th key={j} scope="col" className="min-w-20" style={{textAlign:n.align?.[j]??undefined}}>{leafView(block.leaves[j])}</th>)}</tr></thead>
        <tbody>{n.children.slice(1).map((r,i)=><tr key={i}>{r.children.map((_,j)=><td key={j} className="min-w-20" style={{textAlign:n.align?.[j]??undefined}}>{leafView(block.leaves[(i+1)*r.children.length+j])}</td>)}</tr>)}</tbody></>)}
      <div className="mb-5 flex flex-wrap gap-2" role="group" aria-label={`${label} 표 행 편집`}>
        <button type="button" className={button} disabled={locked} onClick={()=>action(()=>row(block.id,'insert'))}>행 추가</button>
        <button type="button" className={button} disabled={locked||active?.table!==block.id||!active.row||n.children.length<=2} onClick={()=>action(()=>row(block.id,'delete'))}>선택한 행 삭제</button>
      </div>
    </div>;
    return null;
  }
  return <div id={id} aria-labelledby={`${id}-label`} aria-describedby={`${id}-help${error?` ${id}-error`:''}`}>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 id={`${id}-label`} className="font-semibold">{label}</h4>
      <button ref={modeButton} type="button" className={button} disabled={locked||Boolean(model.error)} aria-pressed={rawMode}
        onClick={()=>{setRaw(!raw);setLink(null);setMessage('');setSelection(null);}}>{rawMode?'서식 편집으로':'원문 편집'}</button>
    </div>
    <p id={`${id}-help`} className="mt-2 text-sm leading-6 text-info-muted">공개 서식으로 보면서 수정합니다. 실제 저장은 아래 저장 버튼에서 진행합니다.</p>
    {model.error&&<p role="status" className="mt-3 text-sm leading-6 text-info-status">{model.error}</p>}
    <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label={`${label} 편집 도구`}>
      {!rawMode&&<>
        <button type="button" className={button} disabled={locked||!active||selection?.from===selection?.to} onMouseDown={e=>e.preventDefault()} onClick={()=>action(mark)}>굵게</button>
        <button type="button" className={button} disabled={locked||!active||active.cell} onMouseDown={e=>e.preventDefault()} onClick={()=>action(()=>list(false))}>글머리 목록</button>
        <button type="button" className={button} disabled={locked||!active||active.cell} onMouseDown={e=>e.preventDefault()} onClick={()=>action(()=>list(true))}>번호 목록</button>
        <button type="button" className={button} disabled={locked||!active} onMouseDown={e=>e.preventDefault()} onClick={openLink}>링크 수정</button>
      </>}
      <button type="button" className={button} disabled={locked||history.index===0} onMouseDown={e=>e.preventDefault()} onClick={()=>travel(-1)}>실행 취소</button>
      <button type="button" className={button} disabled={locked||history.index>=history.entries.length-1} onMouseDown={e=>e.preventDefault()} onClick={()=>travel(1)}>다시 실행</button>
    </div>
    {link&&<div className="my-4 space-y-3 border-y border-info-rule py-4" onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();setLink(null);focusCurrent();}}}>
      <label className="block text-sm font-semibold">표시 문구<input className="mt-2 block min-h-11 w-full rounded-lg border border-info-rule bg-info-surface px-3 py-2 text-base" value={link.text} disabled={locked} onChange={e=>setLink({...link,text:e.target.value})}/></label>
      <label className="block text-sm font-semibold">링크 주소<input type="url" className="mt-2 block min-h-11 w-full rounded-lg border border-info-rule bg-info-surface px-3 py-2 text-base" value={link.url} disabled={locked} onChange={e=>setLink({...link,url:e.target.value})}/></label>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={button} disabled={locked} onClick={()=>action(()=>{
          if(!active||!selection||!safeLink(link.url)||!link.text.trim())throw Error('표시 문구와 http 또는 https 링크를 입력해 주세요.');
          const nodes=selectedInline(active.children,selection.from,selection.to,{text:link.text,url:link.url});
          commit(replaceInline(value,active,nodes),{...selection,to:selection.from+link.text.length});setLink(null);
        })}>링크 적용</button>
        <button type="button" className={button} disabled={locked} onClick={()=>action(()=>{
          if(active&&selection)commit(replaceInline(value,active,selectedInline(active.children,selection.from,selection.to,{url:null})),selection);
          setLink(null);
        })}>링크 해제</button>
        <button type="button" className={button} disabled={locked} onClick={()=>{setLink(null);focusCurrent();}}>취소</button>
      </div>
    </div>}
    {rawMode?<textarea ref={source} aria-label={`${label} 원문`} className="mt-3 block min-h-80 w-full resize-y rounded-lg border border-info-rule bg-info-surface px-3 py-3 text-base leading-7 text-primary-text disabled:opacity-60"
      disabled={disabled} aria-invalid={Boolean(error)} aria-describedby={`${id}-help${error?` ${id}-error`:''}`} maxLength={200000} rows={16} value={value} onChange={e=>action(()=>commit(e.target.value,null))}
      onKeyDown={e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();travel(e.shiftKey?1:-1);}}}/>:
      <div ref={view} role="group" aria-label={`${label} 서식 편집`} aria-disabled={disabled}
        className="mt-3 min-h-80 min-w-0 rounded-lg border border-info-rule bg-info-surface p-4 md:p-6"
        onKeyDown={event=>{if(event.key==='Escape'&&!composing){event.preventDefault();setLink(null);modeButton.current?.focus();}}}>
        {model.segments.map((segment,i)=><section key={i} className="border-info-rule py-6 first:pt-0 last:pb-0 [&+section]:border-t">
          {segment.heading&&<h4 className="mb-2 text-base font-bold leading-7 text-primary-text md:text-lg">{segment.heading}</h4>}
          {segment.blocks.map(renderBlock)}
        </section>)}
      </div>}
    {message&&<p role="alert" className="mt-3 text-sm leading-6 text-info-status">{message}</p>}
    {error&&<p id={`${id}-error`} role="alert" className="mt-3 text-sm text-info-status">{error}</p>}
  </div>;
}
