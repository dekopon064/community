/** Whitelisted inline DOM only. Never save innerHTML or pasted HTML. */
import { safeLink, type Inline } from './body-editor';

export function domInline(root:Node):Inline[] {
  const result:Inline[]=[];
  for(const node of root.childNodes){
    if(node.nodeType===3){
      for(const value of (node.textContent??'').split(/(\n)/).filter(Boolean))result.push(value==='\n'?{type:'break'}:{type:'text',value});
      continue;
    }
    if(node.nodeType!==1)continue;
    const element=node as HTMLElement;
    const tag=element.tagName;
    if(['SCRIPT','STYLE','IFRAME','OBJECT','IMG'].includes(tag))throw Error('지원하지 않는 붙여넣기 요소입니다.');
    if(tag==='BR'){result.push({type:'break'});continue;}
    const children=domInline(element);
    if(tag==='STRONG'||tag==='B')result.push({type:'strong',children});
    else if(tag==='EM'||tag==='I')result.push({type:'emphasis',children});
    else if(tag==='A'){
      const url=element.getAttribute('href')??'';
      if(!safeLink(url))throw Error('http 또는 https 링크를 입력해 주세요.');
      result.push({type:'link',url,title:element.getAttribute('title'),children});
    } else {
      if(['DIV','P'].includes(tag)&&result.length)result.push({type:'break'});
      result.push(...children);
    }
  }
  return result;
}

export function writeInline(root:HTMLElement,nodes:Inline[]) {
  const doc=root.ownerDocument;
  function create(node:Inline):Node {
    if(node.type==='text')return doc.createTextNode(node.value);
    if(node.type==='break')return doc.createElement('br');
    if(node.type!=='strong'&&node.type!=='emphasis'&&node.type!=='link')throw Error('Unsupported inline');
    const element=doc.createElement(node.type==='strong'?'strong':node.type==='emphasis'?'em':'a');
    if(node.type==='link'){
      if(!safeLink(node.url))throw Error('Unsafe link');
      element.setAttribute('href',node.url);
      if(node.title)element.setAttribute('title',node.title);
      element.className='font-bold text-ink underline underline-offset-4 break-words';
    } else element.className=node.type==='strong'?'font-bold text-ink':'italic';
    for(const child of node.children)element.appendChild(create(child));
    return element;
  }
  root.replaceChildren(...nodes.map(create));
}

const length=(node:Node):number => node.nodeType===3?(node.textContent??'').length:
  node.nodeType===1&&(node as Element).tagName==='BR'?1:Array.from(node.childNodes).reduce((n,c)=>n+length(c),0);
function offset(root:Node,target:Node,index:number):number {
  if(root===target)return root.nodeType===3?index:Array.from(root.childNodes).slice(0,index).reduce((n,c)=>n+length(c),0);
  let sum=0;
  for(const node of root.childNodes){if(node===target||node.contains(target))return sum+offset(node,target,index);sum+=length(node);}
  return sum;
}
export function selectionOffsets(root:HTMLElement):{from:number;to:number}|null {
  const selection=root.ownerDocument.getSelection();
  if(!selection?.rangeCount)return null;
  const r=selection.getRangeAt(0);
  if(!root.contains(r.startContainer)||!root.contains(r.endContainer))return null;
  return {from:offset(root,r.startContainer,r.startOffset),to:offset(root,r.endContainer,r.endOffset)};
}
export function restoreSelection(root:HTMLElement,from:number,to=from) {
  const doc=root.ownerDocument;
  function point(index:number):[Node,number]{
    let remaining=index;
    function walk(node:Node):[Node,number]|null {
      if(node.nodeType===3){const n=length(node);if(remaining<=n)return[node,remaining];remaining-=n;return null;}
      if(node.nodeType===1&&(node as Element).tagName==='BR'){
        const parent=node.parentNode!;const position=Array.from(parent.childNodes).indexOf(node as ChildNode);
        if(remaining<=1)return[parent,position+remaining];remaining--;return null;
      }
      for(const child of node.childNodes){const found=walk(child);if(found)return found;}
      return null;
    }
    return walk(root)??[root,root.childNodes.length];
  }
  root.focus();
  const range=doc.createRange(),a=point(from),b=point(to);
  range.setStart(...a);range.setEnd(...b);
  const selection=doc.getSelection();selection?.removeAllRanges();selection?.addRange(range);
}
