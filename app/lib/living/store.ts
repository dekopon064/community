import { createHash } from 'node:crypto';
import type { LivingArticle, LivingCommand,LivingListItem } from './contract';
import { livingArticle, livingPublicContent, livingDocument,livingId } from './contract';
import { ReviewFailure } from '../review/contracts';
import type { RpcClient } from '../review/database-store';
import type { ImageMeta } from './image-store';
import { livingImageSrc } from './images';
export interface LivingStore {
  mode: 'database'|'local-fixture';
  list(offset:number):Promise<LivingListItem[]>;
  get(id:string):Promise<LivingArticle>;
  write(command:LivingCommand,actor:string):Promise<LivingArticle>;
}
export class DatabaseLivingStore implements LivingStore {
  readonly mode='database' as const;
  constructor(private client:RpcClient){}
  private async invoke(name:string,args:Record<string,unknown>) {
    try{
      const {data,error}=await this.client.rpc(name,args);
      if(error)throw new ReviewFailure(error.message==='living_conflict'?'conflict':error.message==='living_not_found'?'not_found':error.message==='living_already_published'?'already_processed':error.message==='living_invalid_input'?'invalid_input':'unavailable');
      if(data==null)throw new ReviewFailure('unavailable');return data;
    }catch(error){if(error instanceof ReviewFailure)throw error;throw new ReviewFailure('unavailable');}
  }
  async list(offset:number){const data=await this.invoke('admin_living_read',{p_id:null,p_offset:offset});if(!Array.isArray(data)||data.length>25)throw new ReviewFailure('unavailable');return data.map(v=>{if(!v||!livingId(v.id)||!['draft','published'].includes(v.status)||typeof v.title!=='string')throw new ReviewFailure('unavailable');return {id:v.id,status:v.status,title:v.title} as LivingListItem;});}
  async get(id:string){return livingArticle(await this.invoke('admin_living_read',{p_id:id,p_offset:0}));}
  async write(command:LivingCommand,actor:string){return livingArticle(await this.invoke('admin_living_write',{p_id:command.id,p_version:command.version,p_request_id:command.requestId,p_action:command.action,p_document:command.document,p_actor:actor}));}
}
// Explicit development fixture only. Production selects the RPC adapter.
export class LocalLivingStore implements LivingStore {
  readonly mode='local-fixture' as const;
  articles=new Map<string,LivingArticle>();
  imageAssets=new Map<string,ImageMeta&{actor:string}>();
  publications=new Map<string,{slug:string;user_category:'living';title_ko:string;title_ja:string;summary_ko:string;summary_ja:string;content_ko:string;content_ja:string;source_image_url:string|null;is_published:true}>();
  private receipts=new Map<string,{fingerprint:string;result:LivingArticle}>();
  async list(offset:number){return [...this.articles.values()].reverse().slice(offset,offset+25).map(x=>({id:x.id,status:x.status,title:x.document.content.titleKo||x.document.content.titleJa||'제목 없는 초안'}));}
  async get(id:string){const item=this.articles.get(id);if(!item)throw new ReviewFailure('not_found');return structuredClone(item);}
  async write(c:LivingCommand,actor:string){
    const canonical=(value:unknown):unknown=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>[k,canonical(v)])):value;
    const fingerprint=JSON.stringify(canonical({c,actor}));const receipt=this.receipts.get(c.requestId),current=this.articles.get(c.id);
    if(receipt){if(receipt.fingerprint!==fingerprint||current?.version!==receipt.result.version)throw new ReviewFailure('conflict');return structuredClone(receipt.result);}
    if(c.version!==(current?.version??'0'))throw new ReviewFailure('conflict');
    if(current?.status==='published')throw new ReviewFailure('already_processed');
    if(c.action==='publish'&&!current)throw new ReviewFailure('not_found');
    const document=c.action==='save'?livingDocument(c.document):livingDocument(current!.document,true);
    if(document.images?.some(image=>{const a=this.imageAssets.get(image.id);return !a||a.status!=='ready'||a.articleId!==c.id;}))throw new ReviewFailure('invalid_input');
    const at=new Date().toISOString(),history=[...(current?.history??[]),{action:c.action,actor,at}];
    const item:LivingArticle={id:c.id,document,status:c.action==='publish'?'published':'draft',publishedSlug:c.action==='publish'?`living-${c.id}`:null,history,version:createHash('sha256').update(fingerprint+history.length+at).digest('hex')};
    if(c.action==='publish'){const content=livingPublicContent(document);this.publications.set(c.id,{slug:item.publishedSlug!,user_category:'living',title_ko:content.titleKo,title_ja:content.titleJa,summary_ko:content.summaryKo,summary_ja:content.summaryJa,content_ko:content.contentKo,content_ja:content.contentJa,source_image_url:document.imageUrl||(document.images?.[0]?livingImageSrc(document.images[0].id):null),is_published:true});}
    this.articles.set(c.id,structuredClone(item));this.receipts.set(c.requestId,{fingerprint,result:structuredClone(item)});return structuredClone(item);
  }
}
