import {homeCardPalette, type HomeTone} from '../homeCardPalette';
import type {RpcClient} from '../review/database-store';
import {ReviewFailure} from '../review/contracts';

export const homeToneNames: Record<HomeTone,string> = {default:'회청보라',orange:'살구',yellow:'버터 옐로',green:'소프트 청록',blue:'페리윙클',purple:'라벤더',red:'더스티 로즈'};
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i,hash=/^[a-f0-9]{64}$/;
const states=['missing','pending','processing','completed','failed','no_image'] as const;
type AnalysisState=typeof states[number];
export type HomeColorDetail={id:string;publishedId:string;revision:string;version:string;analysisState:AnalysisState;analysisTone:HomeTone;analysisReason:string|null;analysisActive:boolean;tone:HomeTone;manual:boolean;choiceVersion:number;canEdit:boolean;changedAt:string|null};
export type HomeColorCommand={revision:string;version:string;tone:HomeTone;requestId:string};
function object(raw:unknown):Record<string,unknown>{if(!raw||typeof raw!=='object'||Array.isArray(raw))throw new ReviewFailure('invalid_input');return raw as Record<string,unknown>;}
function tone(value:unknown):value is HomeTone{return typeof value==='string'&&Object.hasOwn(homeCardPalette,value);}
export function homeColorCommand(raw:unknown):HomeColorCommand{
 const v=object(raw);
 if(Object.keys(v).sort().join(',')!=='requestId,revision,tone,version'||typeof v.revision!=='string'||!hash.test(v.revision)||typeof v.version!=='string'||!hash.test(v.version)||!tone(v.tone)||typeof v.requestId!=='string'||!uuid.test(v.requestId))throw new ReviewFailure('invalid_input');
 return {revision:v.revision,version:v.version,tone:v.tone,requestId:v.requestId};
}
export function homeColorDetail(raw:unknown,id:string):HomeColorDetail{
 try{
  const v=object(raw);
  if(v.id!==id||typeof v.publishedId!=='string'||!uuid.test(v.publishedId)||typeof v.revision!=='string'||!hash.test(v.revision)||typeof v.version!=='string'||!hash.test(v.version)
   ||!states.includes(v.analysisState as AnalysisState)||!tone(v.analysisTone)||!tone(v.tone)||typeof v.manual!=='boolean'||typeof v.canEdit!=='boolean'||typeof v.analysisActive!=='boolean'
   ||!Number.isSafeInteger(v.choiceVersion)||Number(v.choiceVersion)<0||v.manual!==(Number(v.choiceVersion)>0)
   ||v.canEdit===v.analysisActive||v.analysisState!=='completed'&&v.analysisTone!=='default'
   ||!(v.analysisReason===null||['matched','ambiguous','analysis_failed','image_changed','expired'].includes(String(v.analysisReason)))
   ||!(v.changedAt===null||typeof v.changedAt==='string'&&Number.isFinite(Date.parse(v.changedAt))))throw new ReviewFailure('unavailable');
  return {id,publishedId:v.publishedId,revision:v.revision,version:v.version,analysisState:v.analysisState as AnalysisState,analysisTone:v.analysisTone,analysisReason:v.analysisReason as string|null,analysisActive:v.analysisActive,tone:v.tone,manual:v.manual,choiceVersion:Number(v.choiceVersion),canEdit:v.canEdit,changedAt:v.changedAt as string|null};
 }catch{throw new ReviewFailure('unavailable');}
}
export function homeAnalysisLabel(item:HomeColorDetail):string{
 if(item.analysisActive)return '분석 중';
 switch(item.analysisState){
  case 'completed':return item.analysisReason==='ambiguous'?'색상 판단 어려움':`완료 · ${homeToneNames[item.analysisTone]}`;
  case 'failed':return '분석 실패';
  case 'no_image':return '이미지 없음';
  case 'missing':return '분석 기록 없음';
  default:return '처리 결과 미확인';
 }
}
export class HomeColorStore{
 constructor(private client:RpcClient){}
 private async invoke(name:string,args:Record<string,unknown>){
  try{const {data,error}=await this.client.rpc(name,args);if(error)throw new ReviewFailure(error.message==='home_color_conflict'?'conflict':error.message==='home_color_not_found'?'not_found':error.message==='home_color_invalid'?'invalid_input':'unavailable');return data;}
  catch(e){if(e instanceof ReviewFailure)throw e;throw new ReviewFailure('unavailable');}
 }
 async get(id:string){return homeColorDetail(await this.invoke('admin_review_home_color',{p_id:id}),id);}
 async save(id:string,command:HomeColorCommand,actor:string){
  const item=homeColorDetail(await this.invoke('admin_review_set_home_color',{p_id:id,p_revision:command.revision,p_version:command.version,p_tone:command.tone,p_request:command.requestId,p_actor:actor}),id);
  if(item.revision!==command.revision||item.tone!==command.tone||!item.manual||item.version===command.version)throw new ReviewFailure('unavailable');
  return item;
 }
}
