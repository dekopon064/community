import type { PeriodDecision, ProgramFacts } from "@/app/lib/review/program-contract";
import { compareProgramPeriods, dateOrderValid, type PeriodMap } from "@/app/lib/review/seoul-period-review";
import { displayProgramDate, periodLabels, programDateInput } from "@/app/lib/review/program-ui";
import { fieldClass, primaryButton, secondaryButton } from "./ReviewEditors";

type Props = {
  facts: ProgramFacts; source: string; reasons: string[]; draft: PeriodMap;
  disabled: boolean; held: boolean; onChange: (value: PeriodMap) => void;
  onDecide: (action: PeriodDecision, periods: PeriodMap) => void;
};
export default function ProgramPeriodDecision({ facts, source, reasons, draft, disabled, held, onChange, onDecide }: Props) {
  const { quotes, keys, suggested } = compareProgramPeriods(facts, source, reasons);
  const saved = facts.periods as PeriodMap;
  const dirty = JSON.stringify(saved) !== JSON.stringify(draft);
  const proposal = { ...saved, ...suggested };
  const hasProposal = Object.keys(suggested).length > 0;
  const label = keys.length === 1 ? periodLabels[keys[0]] + "일" : "신청·운영 기간";
  function change(key: string, precision: string, value: string) {
    const normalized = precision === "day" ? value : (value.length === 16 ? value + ":00" : value) + "+09:00";
    onChange({ ...draft, [key]: { raw: value || null, value: value ? normalized : null, precision, status: value ? "ok" : "missing" } });
  }
  return <section className="my-6 border-y border-info-rule py-4" aria-label="기간 판단">
    <h3 className="text-lg font-bold">{label} {held ? "확인 보류 중" : "확인"}</h3>
    <p className="my-2">{hasProposal ? "등록된 기간과 본문에 적힌 회차 날짜가 다릅니다." :
      reasons.includes("period_missing_or_unparsed") ? "비어 있거나 읽을 수 없는 날짜를 확인해 주세요." :
      reasons.includes("period_order_conflict") ? "시작일과 종료일의 순서를 확인해 주세요." :
      reasons.includes("date_weekday_conflict") ? "원문의 날짜와 요일이 맞는지 확인해 주세요." :
      reasons.includes("invalid_body_date") ? "원문에 유효하지 않은 날짜가 있습니다." : "등록된 기간과 본문 일정을 대조해 주세요."}</p>
    <div className="grid gap-4 my-3 sm:grid-cols-2">
      <div><strong>현재 등록값</strong>{keys.map(key=><p key={key}>{periodLabels[key]} · {displayProgramDate(saved[key])}</p>)}</div>
      <div><strong>수집된 원문</strong>{quotes.length ? quotes.map(line=><p className="whitespace-pre-wrap break-words" key={line}>{line}</p>) :
        <p>해당 날짜의 원문 인용을 찾을 수 없습니다. 아래 원문을 확인해 주세요.</p>}</div>
    </div>
    <div className="flex flex-wrap gap-2">
      <button type="button" className={primaryButton} disabled={disabled || dirty || !dateOrderValid(saved)} onClick={()=>onDecide("keep", saved)}>현재 값 유지</button>
      {hasProposal && <button type="button" className={secondaryButton} disabled={disabled || dirty || !dateOrderValid(proposal)} onClick={()=>onDecide("edit", proposal)}>{Object.entries(suggested).map(([k,p])=>periodLabels[k]+" "+displayProgramDate(p)).join(" · ")}로 수정</button>}
      <button type="button" className={secondaryButton} disabled={disabled || dirty || held} onClick={()=>onDecide("hold", saved)}>보류</button>
    </div>
    <details className="mt-3" onToggle={e=>{if(dirty && !e.currentTarget.open)e.currentTarget.open=true;}}>
      <summary className="cursor-pointer py-2">다른 날짜 직접 입력</summary>
      <fieldset disabled={disabled} className="space-y-2">{Object.entries(periodLabels).map(([key,name])=>{
        const p=draft[key], unit=p.precision ?? "day", value=programDateInput(p);
        return <div key={key} className="flex flex-wrap items-center gap-2"><label htmlFor={"decision-"+key}>{name}</label>
          <select aria-label={name+" 정밀도"} value={unit} onChange={e=>change(key,e.target.value,e.target.value==="day"?value.slice(0,10):value.includes("T")?value:"")}>
            <option value="day">날짜만 명시</option><option value="second">시간까지 명시</option>
          </select><input id={"decision-"+key} type={unit==="day"?"date":"datetime-local"} step={unit==="day"?undefined:1} className={fieldClass} value={value} onChange={e=>change(key,unit,e.target.value)}/></div>;
      })}
      <button type="button" className={primaryButton} disabled={!dirty || !dateOrderValid(draft)} onClick={()=>onDecide("edit",draft)}>입력한 날짜로 수정</button>
      {dirty && <button type="button" className={secondaryButton} onClick={()=>onChange(saved)}>입력 취소</button>}
      </fieldset>
    </details>
  </section>;
}
