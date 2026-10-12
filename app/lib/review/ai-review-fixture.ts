// Development-only synthetic state. No Auth, DB, credentials, provider or timer.
import { ReviewFailure } from './contracts';
import type { AiReview, AiReviewStore, AiRecheckCommand } from './ai-review';
import type { AiSnapshot, AiJob } from './ai-queue';
const ids=['10000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000002','10000000-0000-4000-8000-000000000003'];
export class LocalAiReviewStore implements AiReviewStore {
 readonly mode='local-fixture' as const;
 private items:AiReview[]=ids.map((jobId,i)=>({jobId,sourceItemId:`20000000-0000-4000-8000-00000000000${i+1}`,sourceName:i===1?'myseoul_program':'seoul_reservation',title:i===0?'합성 가족 문화체험':i===1?'합성 일본어 안내 프로그램':'합성 처리 중인 프로그램',revision:'a'.repeat(64),version:'b'.repeat(64),status:i===2?'claimed':'queued',canRecheck:i!==2,recheckPending:false,note:'',source:{url:'https://example.test/synthetic',body:'합성 원문입니다.\n대상: 보호자를 동반한 어린이\n일정: 2099년 10월 18일 10:00~12:00\n수강료: 무료\n실제 콘텐츠가 아닙니다.'},values:[{label:'참여 대상',value:'보호자를 동반한 어린이'},{label:'진행 방식',value:'오프라인'},{label:'개최 지역',value:'서울'},{label:'신청·운영 기간',value:'신청: 2099.10.01~2099.10.10\n운영: 2099.10.18 10:00~12:00'},{label:'수강료',value:'무료'},{label:'거주 조건',value:'확인 필요 · 원문에 미표기'}]}));
 async read(offset=0,watch:string[]=[]):Promise<AiSnapshot>{
  const project=(v:AiReview):AiJob=>({jobId:v.jobId,sourceItemId:v.sourceItemId,revision:v.revision,currentRevision:true,status:v.status as AiJob['status'],title:v.title,sourceName:v.sourceName as AiJob['sourceName'],completedAt:null,retryCount:0,nextRetryAt:null,leaseState:v.status==='claimed'?'active':'none',errorCode:null,resultState:null});
  const pending=this.items.filter(v=>['queued','claimed','failed'].includes(v.status));
  return {checkedAt:new Date().toISOString(),items:pending.slice(offset,offset+25).map(project),held:this.items.filter(v=>v.recheckPending).slice(offset,offset+25).map(project),observed:this.items.filter(v=>watch.includes(v.jobId)).map(project),hasMore:pending.length>offset+25};
 }
 async get(id:string){const v=this.items.find(v=>v.jobId===id);if(!v)throw new ReviewFailure('not_found');return structuredClone(v);}
 async execute(id:string,c:AiRecheckCommand,_actor:string){
  void _actor;const v=this.items.find(v=>v.jobId===id);if(!v)throw new ReviewFailure('not_found');
  if(v.revision!==c.revision||v.version!==c.version||v.status==='claimed'||c.action==='request_recheck'&&!v.canRecheck||c.action==='complete_recheck'&&!v.recheckPending)throw new ReviewFailure('conflict');
  if(c.action==='request_recheck'){v.status='cancelled';v.recheckPending=true;v.canRecheck=false;v.note=c.note;v.version='c'.repeat(64);}
  else{v.recheckPending=false;v.status='cancelled';v.canRecheck=false;v.version='d'.repeat(64);}
  return structuredClone(v);
 }
}
