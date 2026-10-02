import type { ProgramCommand, ProgramFacts, ProgramField } from "./program-contract";
import { programCommand } from "./program-contract";
import { ReviewFailure } from "./contracts";
export const programLabels: Partial<Record<ProgramField, string>> = {
  content_kind: "정보 성격", application_actor: "신청 주체", delivery_mode: "실제 진행 방식", activity_region: "실제 개최 지역",
  activity_evidence: "개최지의 원문 근거", residence_scope: "참여자의 거주 지역 범위", residence_evidence: "거주 조건의 원문 근거",
  target_raw: "대상 안내", conditions: "연령·보호자·증빙 등 명시 조건", application_methods: "신청 방법", fee_kind: "비용 구분",
  fee_amounts: "확인한 금액", source_status: "현재 접수 상태", period_evidence: "기간·요일 확인 근거", official_url: "공식 상세 링크", description: "확인한 프로그램 설명",
};
export const programChoices: Record<string, Record<string, string>> = {
 content_kind: {program:"문화·생활교육·체험 등 프로그램",unknown:"확인 필요",employment:"취업 목적",institutional_business:"기관·사업주 대상 사업",policy_finance:"정책·금융 지원"},
 application_actor:{individual:"개인 신청 가능",individual_or_group:"개인·단체 신청 가능",institution:"개인 신청 불가 · 학교·기관 전용",nationality_excluded:"국적 제한으로 대상 제외"},
 delivery_mode:{unknown:"확인 필요",online:"온라인 진행",offline:"오프라인 진행",hybrid:"온·오프라인 혼합"},
 activity_region:{unknown:"확인 필요",capital:"서울·경기·인천",noncapital:"수도권 외",mixed:"수도권·비수도권 개최지 혼합",not_applicable:"순수 온라인 · 개최지 없음"},
 residence_scope:{unknown:"확인 필요",not_stated:"거주 조건 미표기",nationwide:"전국·지역 제한 없음",includes_capital:"수도권 포함 복수 지역",capital:"수도권 거주자",noncapital:"비수도권 거주자 전용"},
 fee_kind:{unknown:"확인 필요",free:"무료",paid:"유료"}, source_status:{unknown:"확인 필요",open:"접수 중",reservation_closed:"예약 마감",application_closed:"접수 종료"},
};
export const periodLabels: Record<string,string>={RCPTBGNDT:"신청 시작",RCPTENDDT:"신청 종료",SVCOPNBGNDT:"운영 시작",SVCOPNENDDT:"운영 종료"};
export const reasonPatchFields: Record<string,string[]>={
 activity_location_unknown:["delivery_mode","activity_region","activity_evidence"],delivery_mode_unknown:["delivery_mode","activity_region","activity_evidence"],
 residence_scope_unknown:["residence_scope","residence_evidence"],program_purpose_unconfirmed:["content_kind","description"],policy_eligibility_unconfirmed:["content_kind","description"],
 attachment_dependent:["description","content_kind","delivery_mode","activity_region","activity_evidence","application_methods"],program_description_missing:["description","content_kind","delivery_mode","activity_region","activity_evidence","application_methods"],
 missing_source_url:["official_url"],source_status_unknown:["source_status"],source_status_conflict:["source_status"],application_actor_conflict:["application_actor","conditions","target_raw"],
 target_conflict:["target_raw","conditions"],fee_conflict:["fee_kind","fee_amounts"],eligibility_document_unconfirmed:["conditions"],
};
for(const code of ["period_missing_or_unparsed","body_period_needs_confirmation","period_order_conflict","body_api_period_conflict","invalid_body_date","date_weekday_conflict"])reasonPatchFields[code]=["periods","period_evidence"];
export function reviewDetailPath(kind:string,id:string,source:string) {
 return kind==="facts"&&source==="seoul_reservation"?`/api/admin/program-review/${id}`:`/api/admin/review/${kind}/${id}`;
}
export function programPatch(saved:ProgramFacts,draft:ProgramFacts,editable:string[]) {
 return Object.fromEntries(editable.filter(k=>JSON.stringify(saved[k as ProgramField])!==JSON.stringify(draft[k as ProgramField])).map(k=>[k,draft[k as ProgramField]])) as Partial<ProgramFacts>;
}
export function buildProgramSave(item:{revision:string;version:string;facts:ProgramFacts;editableFields:string[];restoredReviewPending?:boolean},draft:ProgramFacts,note:string,resolve:string[]):ProgramCommand {
 const cleaned=Object.fromEntries(Object.entries(draft).map(([k,v])=>[k,Array.isArray(v)?v.map(x=>x.trim()).filter(Boolean):v])) as ProgramFacts;
 const patch=programPatch(item.facts,cleaned,item.editableFields);
 if(!Object.keys(patch).length&&!item.restoredReviewPending)throw new ReviewFailure("invalid_input",{form:"확인한 사실을 변경해 주세요."});
 if(resolve.some(code=>!reasonPatchFields[code]?.some(field=>Object.hasOwn(patch,field))))throw new ReviewFailure("invalid_input",{resolve:"해소를 확인한 사유에 해당하는 사실을 입력해 주세요."});
 return programCommand({action:"save_facts",revision:item.revision,version:item.version,note:note||(item.restoredReviewPending&&!Object.keys(patch).length?"복구 후 사실 재확인":""),patch,resolve,...(item.restoredReviewPending?{confirmRestored:true}:{})});
}
export function displayProgramValue(key:string,value:unknown):string {
 if(Array.isArray(value))return value.length?value.map(v=>programChoices[key]?.[String(v)]??({internet:"인터넷 예약",onsite:"현장 접수",phone:"전화 접수"}[String(v)]??String(v))).join("\n"):"미표기";
 return programChoices[key]?.[String(value)]??(typeof value==="string"&&value?value:"미확인");
}
export function programOutcome(decision:string) {return ({in_scope:"서비스 범위 통과 · 신청 가능",out_of_scope:"서비스 범위에서 제외",review_required:"확인할 사실이 남아 있습니다",not_currently_available:"현재 신청 불가 · 서비스 범위 제외와 구분"}[decision]??"상태 확인 필요");}
