import type {FactsItem} from "@/app/lib/review/contracts";
import {fieldsForReason,factLabels,factValue,visibleFactFields} from "@/app/lib/review/facts-guidance";
import {reasonText} from "@/app/lib/review/presentation";
export default function FactsGuidance({item}:{item:FactsItem}){
 const editable=item.editableFields??Object.keys(item.facts) as (keyof FactsItem["facts"])[];
 const fields=item.restoredReviewPending?visibleFactFields(item.facts):[...new Set(item.reasons.flatMap(code=>fieldsForReason(code,item.facts,editable)))];
 return <section className="my-6" aria-label="이번에 확인할 사항">
 <h3 className="text-lg font-bold">이번에 확인할 사항</h3>
 {!item.reasons.length?<p className="mt-3 text-info-body">남은 확인 사유가 없습니다.</p>:<ul className="mt-3 divide-y divide-info-rule border-y border-info-rule">{item.reasons.map(code=>{
  const text=reasonText(code),fields=fieldsForReason(code,item.facts,editable);
  return <li key={code} className="py-4"><p className="font-semibold leading-7">{text.title}</p><p className="mt-1 max-w-3xl leading-7 text-info-body">{text.help}</p>
  {fields.length?<p className="mt-2 flex flex-wrap gap-x-4 gap-y-2 text-sm leading-6">{fields.map(field=><a key={field} href={"#"+field} className="min-h-11 py-2 underline underline-offset-4">{factLabels[field]} 입력</a>)}</p>:code!=="restored_review_pending"&&<p className="mt-2 text-sm leading-6 text-info-muted">현재 열린 입력만으로 바로 해결할 수 없는 사유입니다. 공식 원문과 선행 확인 사항을 확인해 주세요.</p>}
  </li>;
 })}</ul>}
 {fields.length>0&&<dl className="mt-4 grid gap-3 sm:grid-cols-2" aria-label="확인 사유에 관련된 현재 사실">{fields.map(key=><div key={key}><dt className="font-semibold">{factLabels[key]}</dt><dd className="whitespace-pre-wrap break-words text-info-body">{factValue(item.facts,key)}</dd></div>)}</dl>}
 </section>;
}
