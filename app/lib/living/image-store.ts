import type { SupabaseClient } from '@supabase/supabase-js';
import { ReviewFailure } from '../review/contracts';
import { imageId, livingImageBytes, parseLivingImages, type LivingImage } from './images';
import type { LocalLivingStore } from './store';

export const livingImageBucket = 'living-card-images';
export type ImageMeta = { id: string; articleId: string; path: string; hash: string; status: 'pending'|'ready'; width: number; height: number; size: number; fresh?: boolean };
export interface LivingImageStore {
  begin(id:string,articleId:string,version:string,hash:string,meta:{width:number;height:number;size:number},actor:string):Promise<ImageMeta>;
  finish(id:string,actor:string):Promise<ImageMeta>;
  read(id:string,admin:boolean):Promise<ImageMeta>;
  put(path:string,bytes:Uint8Array):Promise<void>;
  download(path:string):Promise<Blob>;
  gallery(articleId:string):Promise<LivingImage[]>;
}
// Explicit in-memory test adapter, never selected by production routes.
export class LocalLivingImageStore implements LivingImageStore {
  blobs=new Map<string,Uint8Array>();
  constructor(readonly articles:LocalLivingStore){}
  async begin(id:string,articleId:string,version:string,hash:string,meta:{width:number;height:number;size:number},actor:string){
    const draft=this.articles.articles.get(articleId),old=this.articles.imageAssets.get(id);
    if(version!==(draft?.version??'0')||draft?.status==='published')throw new ReviewFailure('conflict');
    if(old){if(old.hash!==hash||old.actor!==actor||old.articleId!==articleId||old.size!==meta.size||old.width!==meta.width||old.height!==meta.height)throw new ReviewFailure('conflict');return {...old,fresh:false};}
    const item={id,articleId,hash,actor,...meta,status:'pending' as const,path:`${articleId}/${id}.webp`};
    this.articles.imageAssets.set(id,item);return {...item,fresh:true};
  }
  async finish(id:string,actor:string){const item=await this.read(id,true);
    if(this.articles.imageAssets.get(id)?.actor!==actor||this.articles.articles.get(item.articleId)?.status==='published')throw new ReviewFailure('conflict');
    const next={...this.articles.imageAssets.get(id)!,status:'ready' as const};this.articles.imageAssets.set(id,next);return next;}
  async read(id:string,admin:boolean){const item=this.articles.imageAssets.get(id);
    if(!item||!admin&&!(await this.gallery(item.articleId)).some(i=>i.id===id))throw new ReviewFailure('not_found');return structuredClone(item);}
  async put(path:string,bytes:Uint8Array){if(this.blobs.has(path))throw new ReviewFailure('conflict');this.blobs.set(path,new Uint8Array(bytes));}
  async download(path:string){const data=this.blobs.get(path);if(!data)throw new ReviewFailure('not_found');return new Blob([new Uint8Array(data)],{type:'image/webp'});}
  async gallery(articleId:string){return this.articles.publications.has(articleId)?structuredClone(this.articles.articles.get(articleId)?.document.images??[]):[];}
}
export class DatabaseLivingImageStore implements LivingImageStore {
  constructor(private client:SupabaseClient){}
  private async call(name:string,args:Record<string,unknown>) {
    try {
      const {data,error}=await this.client.rpc(name,args);
      if(error) throw new ReviewFailure(error.message==='living_conflict'?'conflict':error.message==='living_not_found'?'not_found':error.message==='living_invalid_input'?'invalid_input':'unavailable');
      if(data==null)throw new ReviewFailure('not_found');return data;
    }catch(e){if(e instanceof ReviewFailure)throw e;throw new ReviewFailure('unavailable');}
  }
  private meta(v:ImageMeta):ImageMeta {
    if(!v||!imageId(v.id)||!imageId(v.articleId)||v.path!==`${v.articleId}/${v.id}.webp`||!['ready','pending'].includes(v.status)||!/^[a-f0-9]{64}$/.test(v.hash)
      ||!Number.isInteger(v.size)||v.size<1||v.size>livingImageBytes||!Number.isInteger(v.width)||!Number.isInteger(v.height)||v.width<1||v.height<1||v.width*v.height>16_000_000)throw new ReviewFailure('unavailable');
    return v;
  }
  private mutation(id:string,actor:string,action:string,articleId:string|null=null,version:string|null=null,hash:string|null=null,meta:unknown=null){
    return this.call('admin_living_image',{p_id:id,p_article:articleId,p_version:version,p_action:action,p_hash:hash,p_meta:meta,p_actor:actor}).then(v=>this.meta(v));
  }
  begin(id:string,articleId:string,version:string,hash:string,meta:{width:number;height:number;size:number},actor:string){return this.mutation(id,actor,'begin',articleId,version,hash,meta);}
  finish(id:string,actor:string){return this.mutation(id,actor,'finish');}
  async read(id:string,admin:boolean){return this.meta(await this.call(admin?'admin_living_image_read':'public_living_image',{p_id:id}));}
  async gallery(articleId:string){return parseLivingImages(await this.call('public_living_gallery',{p_article:articleId}));}
  async put(path:string,bytes:Uint8Array){
    try{const {error}=await this.client.storage.from(livingImageBucket).upload(path,bytes,{contentType:'image/webp',upsert:false,cacheControl:'0'});if(error)throw Error();}
    catch{throw new ReviewFailure('unavailable');}
  }
  async download(path:string){
    try{const {data,error}=await this.client.storage.from(livingImageBucket).download(path);if(error||!data||data.size>livingImageBytes||data.type!=='image/webp')throw Error();return data;}
    catch{throw new ReviewFailure('unavailable');}
  }
}
