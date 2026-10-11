/** Source ranges are the storage boundary. Never serialize an untouched document. */
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import { toMarkdown } from 'mdast-util-to-markdown';
import { gfmToMarkdown } from 'mdast-util-gfm';
import type { Root, RootContent, PhrasingContent, Table, List } from 'mdast';
import { parseCurationBodySections } from '../curationBodySections';
import { CURATION_SECTION_LABELS, curationHeadingAliases, type BodyLocale } from '../curationSectionLabels';

export type Inline = PhrasingContent;
export type Leaf = { id: string; start: number; end: number; children: Inline[]; raw: string;
  cell?: boolean; table?: string; row?: number; column?: number; list?: List; block: RootContent; base: number };
export type Block = { node: RootContent; id: string; leaves: Leaf[]; nested: Block[] };
export type Segment = { heading?: string; blocks: Block[] };
export type Document = { source: string; segments: Segment[]; leaves: Leaf[]; tables: {id:string;node:Table;base:number}[]; error?: string };
const parser = unified().use(remarkParse).use(remarkGfm, { singleTilde: false });
export const safeLink = (url: string) => /^https?:\/\/[^\s\u0000-\u001f]+$/i.test(url);
const start = (node: RootContent | Inline) => node.position?.start.offset ?? 0;
const end = (node: RootContent | Inline) => node.position?.end.offset ?? 0;

function supportedInline(nodes: Inline[]): boolean {
  return nodes.every(n => n.type === 'text' || n.type === 'break' ||
    ((n.type === 'strong' || n.type === 'emphasis' || n.type === 'link' && safeLink(n.url)) && supportedInline(n.children)));
}

export function readEditor(source: string, locale: string): Document {
  const model: Document = { source, segments: [], leaves: [], tables: [] };
  const ranges: {heading?:string;start:number;end:number}[] = [];
  const parsedSections=parseCurationBodySections(source, locale);
  if (parsedSections) {
    const labels = CURATION_SECTION_LABELS[locale as BodyLocale];
    let current = { start: 0, end: source.length, heading: undefined as string | undefined };
    for (const match of source.matchAll(/^\[([^\]\r\n]+)\][ \t]*(?:\r?\n|$)/gm)) {
      const heading = labels.find(h => curationHeadingAliases(h).includes(match[1]));
      if (!heading) continue;
      current.end = match.index!;
      if (source.slice(current.start,current.end).trim()) ranges.push(current);
      current = { heading, start: match.index! + match[0].length, end: source.length };
    }
    ranges.push(current);
  } else ranges.push({start:0,end:source.length});
  let unsupported = Boolean(parsedSections&&ranges.filter(r=>r.heading).length!==parsedSections.sections.length);
  for (const [section, range] of ranges.entries()) {
    const tree = parser.parse(source.slice(range.start,range.end)) as Root;
    const leaves: Leaf[] = [];
    function block(node: RootContent, id: string, list?: List): Block {
      const b: Block = {node,id,leaves:[],nested:[]};
      const leaf = (children: Inline[], s: number, e: number, suffix: string, extra: Partial<Leaf> = {}) => {
        if (!supportedInline(children)) unsupported = true;
        const item: Leaf = {id:id+suffix,start:range.start+s,end:range.start+e,children,
          raw:source.slice(range.start+s,range.start+e),block:node,base:range.start,list,...extra};
        b.leaves.push(item); leaves.push(item); model.leaves.push(item);
      };
      if (node.type === 'paragraph' || node.type === 'heading') {
        const s = node.type === 'heading' && node.children.length ? start(node.children[0]) : start(node);
        leaf(node.children, s, node.type==='heading'&&node.children.length?end(node.children.at(-1)!):end(node), '');
      } else if (node.type === 'list') {
        for (const [i,item] of node.children.entries()) {
          if (item.checked !== null && item.checked !== undefined) unsupported = true;
          b.nested.push({node:item,id:id+'.'+i,leaves:[],nested:item.children.map((n,j)=>block(n,id+'.'+i+'.'+j,node))});
        }
      } else if (node.type === 'table') {
        if(node.children.some(row=>row.children.length!==node.children[0].children.length))unsupported=true;
        model.tables.push({id,node,base:range.start});
        for (const [i,row] of node.children.entries()) for (const [j,cell] of row.children.entries()) {
          const first=cell.children[0], last=cell.children.at(-1);
          let s=first ? start(first) : cell.position!.start.offset!;
          const e=last ? end(last) : s;
          // Empty cells still have a writable point inside their delimiters.
          if (!first && source[range.start+s] === '|') s++;
          leaf(cell.children,s,first?e:s,'.'+i+'.'+j,{cell:true,table:id,row:i,column:j});
        }
      } else unsupported = true;
      return b;
    }
    const blocks=tree.children.map((n,i)=>block(n,'s'+section+'.'+i));
    if (!blocks.length) {
      const node: RootContent = {type:'paragraph',children:[]};
      const item:Leaf={id:'s'+section+'.0',start:range.start,end:range.start,children:[],raw:'',block:node,base:range.start};
      blocks.push({node,id:item.id,leaves:[item],nested:[]});model.leaves.push(item);
    }
    model.segments.push({heading:range.heading,blocks});
  }
  if (unsupported) model.error='이 본문에는 현재 서식 편집으로 보존할 수 없는 요소가 있습니다. 원문 편집을 사용해 주세요.';
  return model;
}

type Token = {text:string;bold?:boolean;italic?:boolean;url?:string;title?:string|null;break?:boolean};
export function inlineTokens(nodes: Inline[], marks: Omit<Token,'text'> = {}): Token[] {
  return nodes.flatMap(n => {
    if (n.type==='text') return [{...marks,text:n.value}];
    if (n.type==='break') return [{...marks,text:'\n',break:true}];
    if (n.type==='strong') return inlineTokens(n.children,{...marks,bold:true});
    if (n.type==='emphasis') return inlineTokens(n.children,{...marks,italic:true});
    if (n.type==='link') return inlineTokens(n.children,{...marks,url:n.url,title:n.title});
    throw Error('Unsupported inline');
  });
}
export const inlineText = (nodes: Inline[]) => inlineTokens(nodes).map(t=>t.text).join('');

export function tokensInline(tokens: Token[]): Inline[] {
  const result: Inline[]=[];
  for (const t of tokens) {
    if (!t.text) continue;
    let n:Inline=t.break ? {type:'break'} : {type:'text',value:t.text};
    if (t.url) n={type:'link',url:t.url,title:t.title,children:[n]};
    if (t.italic) n={type:'emphasis',children:[n]};
    if (t.bold) n={type:'strong',children:[n]};
    const previous=result.at(-1);
    function merge(a: Inline, b: Inline): boolean {
      if(a.type==='text'&&b.type==='text'){a.value+=b.value;return true;}
      if(a.type===b.type&&'children' in a&&'children' in b&&
        (a.type!=='link'||b.type==='link'&&a.url===b.url&&a.title===b.title)){
        if(!merge(a.children.at(-1)!,b.children[0]))a.children.push(b.children[0]);
        a.children.push(...b.children.slice(1));return true;
      }
      return false;
    }
    if (!previous || !merge(previous,n)) result.push(n);
  }
  return result;
}

export function selectedInline(nodes:Inline[], from:number,to:number, action:{bold?:boolean;url?:string|null;text?:string}):Inline[] {
  let offset=0;
  const output:Token[]=[];
  let inserted=false;
  const insertion=()=>action.text!.split(/(\n)/).filter(Boolean).map(text=>({text,url:action.url??undefined,...(text==='\n'?{break:true}: {})}));
  for(const token of inlineTokens(nodes)){
    const left=offset,right=offset+token.text.length;offset=right;
    if(right<=from||left>=to){
      if(action.text!==undefined&&!inserted&&left>=from){output.push(...insertion());inserted=true;}
      output.push(token);continue;
    }
    const a=Math.max(0,from-left),b=Math.min(token.text.length,to-left);
    if(a)output.push({...token,text:token.text.slice(0,a)});
    if(action.text!==undefined){if(!inserted){output.push(...insertion());inserted=true;}}
    else output.push({...token,text:token.text.slice(a,b),
      ...(action.bold!==undefined?{bold:action.bold}:{}),...(action.url!==undefined?{url:action.url??undefined}: {})});
    if(b<token.text.length)output.push({...token,text:token.text.slice(b)});
  }
  if(action.text!==undefined&&!inserted)output.push(...insertion());
  return tokensInline(output);
}

export function replaceInline(source:string,leaf:Leaf,children:Inline[]):string {
  if (inlineText(children)===inlineText(leaf.children)&&JSON.stringify(inlineTokens(children))===JSON.stringify(inlineTokens(leaf.children))) return source;
  if (!supportedInline(children)) throw Error('지원하지 않는 서식입니다.');
  if (leaf.cell && inlineText(children).includes('\n')) throw Error('표 셀은 한 줄로 입력해 주세요. 여러 행은 원문 편집을 사용해 주세요.');
  if(leaf.block.type==='heading'&&inlineText(children).includes('\n'))throw Error('제목은 한 줄로 입력해 주세요.');
  const fragment=toMarkdown({type:'root',children:[{type:'paragraph',children}]},{extensions:[gfmToMarkdown()],bullet:'-',emphasis:'*',strong:'*'}).replace(/\n$/,'');
  // GFM cell delimiters cannot be introduced by a text edit. Escaping is a
  // Markdown boundary operation, never a change to the displayed cell value.
  const text=leaf.cell ? fragment.replace(/(?<!\\)\|/g,'\\|') : leaf.list
    ? fragment.replace(/\n/g,'\n'+' '.repeat((leaf.block.position?.start.column??1)-1)) : fragment;
  return source.slice(0,leaf.start)+text+source.slice(leaf.end);
}

export function changeList(source:string,leaf:Leaf,ordered:boolean):string {
  if(leaf.cell)throw Error('표 셀에는 목록을 적용하지 않습니다.');
  const original=leaf.list??leaf.block;
  if(original.type!=='list'&&original.type!=='paragraph')throw Error('문단이나 목록을 선택해 주세요.');
  const n=structuredClone(original);
  const children:RootContent[]=n.type==='list'
    ? n.ordered===ordered ? n.children.flatMap(i=>i.children) : [{...n,ordered,start:ordered?1:null}]
    : [{type:'list',ordered,start:ordered?1:null,spread:false,children:[{type:'listItem',spread:false,children:[n]}]}];
  const indent=' '.repeat((original.position?.start.column??1)-1);
  const text=toMarkdown({type:'root',children},{extensions:[gfmToMarkdown()],bullet:'-'}).replace(/\n$/,'').replace(/\n/g,'\n'+indent);
  return source.slice(0,leaf.base+start(original))+text+source.slice(leaf.base+end(original));
}

export function tableRow(source:string,table:{node:Table;base:number},index:number,action:'insert'|'delete'):string {
  if(action==='delete'&&(index<1||table.node.children.length<=2))throw Error('머리글과 마지막 본문 행은 삭제할 수 없습니다.');
  const node=structuredClone(table.node);
  if(action==='insert')node.children.splice(Math.max(1,index+1),0,{type:'tableRow',children:node.children[0].children.map(()=>({type:'tableCell',children:[]}))});
  else node.children.splice(index,1);
  const text=toMarkdown({type:'root',children:[node]},{extensions:[gfmToMarkdown()]}).replace(/\n$/,'');
  return source.slice(0,table.base+start(table.node))+text+source.slice(table.base+end(table.node));
}
