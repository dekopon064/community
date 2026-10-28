import type { CandidateContent } from '../review/contracts';
import { ReviewFailure } from '../review/contracts';
import { validateContent } from '../review/validation';
import { sourceImageUrl } from '../sourceImages';
import { parseLivingImages, type LivingImage } from './images';

export type LivingDocument = { content: CandidateContent; imageUrl: string; referenceUrl: string; checkedOn: string; images?: LivingImage[] };
export type LivingArticle = { id: string; version: string; status: 'draft'|'published'; document: LivingDocument;
  publishedSlug: string|null; history: { action: string; actor: string; at: string }[] };
export type LivingListItem = Pick<LivingArticle,'id'|'status'> & {title:string};
export type LivingCommand = { id: string; version: string; requestId: string; action: 'save'|'publish'; document: LivingDocument|null };
export const livingId = (v: unknown): v is string => typeof v==='string' && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(v);
export function emptyLivingDocument(): LivingDocument {
  return {content:{titleKo:'',summaryKo:'',contentKo:'',titleJa:'',summaryJa:'',contentJa:''},imageUrl:'',referenceUrl:'',checkedOn:'',images:[]};
}
function record(v: unknown): Record<string,unknown> {
  if(!v||typeof v!=='object'||Array.isArray(v))throw new ReviewFailure('invalid_input');
  return v as Record<string,unknown>;
}
function exact(v: Record<string,unknown>,keys: string[]) {
  if(Object.keys(v).length!==keys.length||keys.some(k=>!Object.hasOwn(v,k)))throw new ReviewFailure('invalid_input');
}
export function livingDocument(value: unknown, publish=false): LivingDocument {
  const v=record(value);exact(v,['content','imageUrl','referenceUrl','checkedOn',...(Object.hasOwn(v,'images')?['images']:[])]);const c=record(v.content);
  const images=Object.hasOwn(v,'images')?parseLivingImages(v.images):[];
  const limits={titleKo:300,titleJa:300,summaryKo:1000,summaryJa:1000,contentKo:200000,contentJa:200000};exact(c,Object.keys(limits));
  const fields: Record<string,string>={};
  for(const [k,max] of Object.entries(limits))if(typeof c[k]!=='string'||(c[k] as string).length>max)fields[k]=`${max.toLocaleString('ko-KR')}자 이내로 입력해 주세요.`;
  for(const k of ['imageUrl','referenceUrl','checkedOn'])if(typeof v[k]!=='string')throw new ReviewFailure('invalid_input');
  if(v.imageUrl && (!(v.imageUrl as string).startsWith('https://')||sourceImageUrl(v.imageUrl)!==v.imageUrl))fields.imageUrl='사용 가능한 HTTPS 이미지 주소를 입력해 주세요.';
  if(v.referenceUrl && (!(v.referenceUrl as string).startsWith('https://')||sourceImageUrl(v.referenceUrl)!==v.referenceUrl))fields.referenceUrl='사용 가능한 HTTPS 참고 링크를 입력해 주세요.';
  if(v.checkedOn && (typeof v.checkedOn!=='string'||!/^\d{4}-\d\d-\d\d$/.test(v.checkedOn)||!Number.isFinite(Date.parse(v.checkedOn))||new Date(v.checkedOn).toISOString().slice(0,10)!==v.checkedOn))fields.checkedOn='유효한 정보 확인일을 입력해 주세요.';
  if(Object.keys(fields).length)throw new ReviewFailure('invalid_input',fields);
  if(publish)validateContent(images.length?{...c,contentKo:(c.contentKo as string).trim()||c.summaryKo,contentJa:(c.contentJa as string).trim()||c.summaryJa}:c);
  return structuredClone(v) as LivingDocument;
}
export function livingCommand(value: unknown): LivingCommand {
  const v=record(value);exact(v,['id','version','requestId','action','document']);
  if(!livingId(v.id)||!livingId(v.requestId)||typeof v.version!=='string'||!(/^[a-f0-9]{64}$/.test(v.version)||v.version==='0')||!['save','publish'].includes(String(v.action)))throw new ReviewFailure('invalid_input');
  if(v.action==='publish'&&(v.document!==null||v.version==='0'))throw new ReviewFailure('invalid_input');
  return {id:v.id,requestId:v.requestId,version:v.version,action:v.action as 'save'|'publish',document:v.action==='save'?livingDocument(v.document):null};
}
export function livingBody(doc: LivingDocument,locale: 'ko'|'ja') {
  const raw=doc.content[locale==='ko'?'contentKo':'contentJa'];
  return (raw.trim()?raw.trim():((doc.images?.length??0)>0?doc.content[locale==='ko'?'summaryKo':'summaryJa'].trim():''))+(doc.checkedOn?`\n\n${locale==='ko'?'정보 확인일':'情報確認日'}: ${doc.checkedOn}`:'');
}
// Normalize only the new public projection. The saved draft and history stay exact.
export function livingPublicContent(doc:LivingDocument):CandidateContent {
  return validateContent({...doc.content,contentKo:livingBody(doc,'ko'),contentJa:livingBody(doc,'ja')});
}
export function livingArticle(value: unknown): LivingArticle {
  try {
    const v=record(value);
    if(!livingId(v.id)||typeof v.version!=='string'||!/^[a-f0-9]{64}$/.test(v.version)||!['draft','published'].includes(String(v.status))||!(v.publishedSlug===null||v.publishedSlug===`living-${v.id}`)||!Array.isArray(v.history))throw Error();
    const history=v.history.map(x=>{const h=record(x);if(!['save','publish'].includes(String(h.action))||typeof h.actor!=='string'||!Number.isFinite(Date.parse(String(h.at))))throw Error();return {action:String(h.action),actor:h.actor,at:String(h.at)};});
    return {id:v.id,version:v.version,status:v.status as LivingArticle['status'],document:livingDocument(v.document),publishedSlug:v.publishedSlug as string|null,history};
  }catch{throw new ReviewFailure('unavailable');}
}
