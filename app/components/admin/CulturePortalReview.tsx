import type { FactsItem } from '../../lib/review/contracts';
import { reasonText } from '../../lib/review/presentation';

const fields:Record<string,string>={scope:'문화·체험 범위',venue:'장소',period:'행사 기간',hours:'운영 시간',audience:'참여 대상',fee:'비용',booking:'신청 방법',subprograms:'세부 프로그램',poster_text:'이미지 대체텍스트',description:'상세 본문'};

export default function CulturePortalReview({review}:{review:NonNullable<FactsItem['collectionReview']>}) {
  return <section className="my-6 border-y border-info-rule py-5" aria-label="서울문화포털 수집 검토">
    <h3 className="font-semibold">서울문화포털 수집 검토</h3>
    <p className="mt-2 text-sm leading-6">문화·체험 행사 원문을 수집했습니다. 중복 의심이나 불명확한 조건은 확정하지 않았으며, AI 작업으로 자동 전환하지 않습니다.</p>
    {review.outcome==='change_review'&&<p role="status" className="mt-3 text-info-status">새 원문 변경을 기록했습니다. 기존 저장값·운영자 판단은 유지되어 있으며, 변경 내용의 영향 확인이 필요합니다.</p>}
    {review.matches.length>0&&<div className="mt-4"><h4 className="font-semibold">중복 비교 대상</h4><ul className="mt-2 space-y-2">{review.matches.map(m=><li key={m.id}>{m.title} · {m.source}<br/><span className="text-sm">{m.kind==='same_official_identity'?'같은 공식 상세 식별자':'중복 의심 · 별도 행사/회차인지 확인 필요'}</span><br/><code className="text-xs break-all">항목 ID: {m.id}</code></li>)}</ul></div>}
    {review.issues.map((issue,i)=><div key={i} className="mt-4 border-t border-info-rule pt-3">
      <h4 className="font-semibold">{fields[issue.field]??issue.field} · {reasonText(issue.code).title}</h4>
      <p className="mt-1 text-sm leading-6">{reasonText(issue.code).help}</p>
      {issue.evidence.length?issue.evidence.map((value,j)=><blockquote key={j} className="mt-2 whitespace-pre-wrap break-words border-l-2 border-info-rule pl-3 leading-7">{value}</blockquote>):<p className="mt-2 text-sm">수집된 근거 없음</p>}
    </div>)}
  </section>;
}
