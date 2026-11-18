import type {CandidateItem} from '../../app/lib/review/contracts';
import {emptyContentFilters} from '../../app/lib/contentFilters';

export function focusCandidates(): CandidateItem[] {
  const filters=emptyContentFilters('program');
  filters.topic={status:'known',value:'culture_experience'};
  filters.delivery={status:'known',value:'onsite'};
  const base:CandidateItem={id:'20000000-0000-4000-8000-000000000001',kind:'candidates',status:'pending',category:'program',period:'2026-11-30',revision:'a'.repeat(64),version:'1',publishedAt:null,publishedId:null,
    source:{name:'seoul_reservation',title:'[합성] 한옥 역사 산책',url:'http://127.0.0.1:3418/local-original.html',body:'합성 자료입니다. 누구나 참여할 수 있습니다.\n11월 28일 11시부터 13시까지 진행합니다.'},
    image:{mode:'none',url:null,sourceUrl:null},
    content:{titleKo:'[합성] 한옥 역사 산책',titleJa:'[合成] 韓屋歴史散策',summaryKo:'해설사와 한옥의 역사를 알아보세요.',summaryJa:'解説員と韓屋の歴史を学びましょう。',contentKo:'## 대상\n누구나 참여할 수 있습니다.\n\n## 일정 안내\n11월 28일 11~13시에 진행합니다.',contentJa:'## 対象\nどなたでも参加できます。\n\n## 日程\n11月28日の11時～13時に実施します。'},
    programInfo:{inputFactsVersion:4,currentFactsVersion:4,inputChanged:false,canPublish:true,applicationPeriod:'2026-11-06T10:00:00+09:00 ~ 2026-11-25T11:59:00+09:00',operatingPeriod:'2026-11-28 ~ 2026-11-28'},
    filterInfo:{schema:'content-filters-v1',inputVersion:6,approvedVersion:6,currentVersion:6,inputRevision:'a'.repeat(64),approvedRevision:'a'.repeat(64),currentRevision:'a'.repeat(64),input:structuredClone(filters),approved:structuredClone(filters),current:structuredClone(filters),changed:false,canPublish:true},
    history:[{action:'save_candidate',actor:'local-synthetic-operator',at:'2026-11-18T01:30:00Z',note:'가짜 RPC 저장 기록: 원문 조건 유지'}]};
  const noUrl=structuredClone(base);noUrl.id=noUrl.id.slice(0,-1)+'2';noUrl.source.name='myseoul_program';noUrl.source.url='';noUrl.content.titleKo='[합성] My서울+ 원문 링크 없음';
  const changed=structuredClone(base);changed.id=changed.id.slice(0,-1)+'3';changed.content.titleKo='[합성] 사실·탐색값 변경';changed.programInfo!.inputChanged=true;changed.programInfo!.canPublish=false;changed.programInfo!.currentFactsVersion=5;changed.filterInfo!.changed=true;changed.filterInfo!.canPublish=false;changed.filterInfo!.currentVersion=7;changed.filterInfo!.current.delivery={status:'known',value:'online'};
  const ai=structuredClone(base);ai.id=ai.id.slice(0,-1)+'4';ai.content.titleKo='[합성] AI 수정·근거 확인';
  const my=structuredClone(base);my.id=my.id.slice(0,-1)+'5';my.source.name='myseoul_program';my.content.titleKo='[합성] My서울+ 원문 변경';my.programInfo={...my.programInfo!,inputChanged:true,currentFactsVersion:5,canPublish:false,changedFields:['신청 기간'],comparisonAvailable:true,changeReviewed:false};
  return [base,noUrl,changed,ai,my];
}

export const syntheticReview={matchesSavedOutput:true,source:'합성 원문: 누구나 참여. 11월 28일 11~13시. 취소 기한은 확인 필요.',issues:[
  {stage:'translation',rule:'clock',reason:'mismatch',expected:'13:00',actual:'14:00',disposition:'change',field:'contentJa',before:'11月28日の11時～13時に実施します。',after:'11月28日の11時から13時までです。',evidence:'11월 28일 11~13시'},
  {stage:'translation',rule:'participation_constraint',reason:'missing',disposition:'needs_review',field:'contentKo',before:'누구나 참여할 수 있습니다.',evidence:'취소 기한에 대한 근거가 부족합니다.'},
  {stage:'translation',rule:'per_session',reason:'added',disposition:'equivalent',evidence:'누구나 참여할 수 있습니다.'}
]};
