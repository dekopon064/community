import type {Facts} from "./contracts";
export const factLabels:Record<keyof Facts,string>={productType:"정보 성격",category:"공개 카테고리",scope:"신청·이용 대상 지역",regions:"대상 지역",evidence:"대상 지역의 원문 근거",foreignEligibility:"외국인 거주자의 신청 자격",delivery:"진행 방식",deadlineKind:"신청 마감",deadlineOn:"신청 마감일",eventStart:"행사 시작일",eventEnd:"행사 종료일"};
const maps:Record<string,(keyof Facts)[]>={
 product_type_unknown:["productType"],product_type_unconfirmed:["productType"],policy_lifecycle_uncertain:["productType"],policy_lifecycle_conflict:["productType"],end_date_absent_not_reference:["productType"],
 region_scope_unknown:["scope","regions","evidence","delivery"],relevance_unconfirmed:["foreignEligibility","evidence","delivery"],
 user_category_unconfirmed:["category","eventStart","eventEnd"],application_deadline_unknown:["deadlineKind","deadlineOn"],event_period_unknown:["eventStart","eventEnd"]
};
export function visibleFactFields(f:Facts):(keyof Facts)[]{return ["productType","category","delivery",...(f.productType!=="living_guide"?["scope","evidence",...(f.scope==="specific"?["regions"]:[])]:[]),...(f.productType==="policy_reference"?["foreignEligibility"]:[]),...(["policy","program"].includes(f.category)?["deadlineKind",...(f.deadlineKind==="fixed"?["deadlineOn"]:[])]:[]),...(f.category==="event"?["eventStart","eventEnd"]:[])] as (keyof Facts)[];}
export function fieldsForReason(code:string,facts:Facts,editable:(keyof Facts)[]){const visible=visibleFactFields(facts);return (maps[code]??[]).filter(k=>editable.includes(k)&&visible.includes(k));}
export function reasonsForField(field:keyof Facts,reasons:string[]){return reasons.filter(r=>maps[r]?.includes(field));}
export function factValue(facts:Facts,key:keyof Facts){
 const v=facts[key];if(Array.isArray(v))return v.length?v.map(x=>({"11":"서울","28":"인천","41":"경기"}[x]??x)).join(", "):"미표기";
 const labels:Record<string,string>={policy_reference:"정책 참고자료",event_program:"행사·프로그램",living_guide:"생활 안내",policy:"정책",program:"프로그램",event:"행사",living:"생활",youth_space:"청년공간",nationwide:"전국",specific:"특정 지역",unknown:"미확인",eligible:"신청 가능",ineligible:"신청 불가",online:"온라인",offline:"오프라인",hybrid:"온·오프라인 병행",fixed:"마감일 있음",none:"정해진 마감 없음",closed:"접수 종료"};
 return labels[v]??(v||"미확인");
}
