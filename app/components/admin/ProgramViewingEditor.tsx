import { viewingSubjects, type Viewing } from '../../lib/programOutings';

const blank: Viewing = {subject:'exhibition', from:'', through:'', weekdays:[], exceptions:[], reservationNotRequired:true};
export default function ProgramViewingEditor({value,onChange,disabled}: {
  value: Viewing | null; onChange:(v: Viewing | null)=>void; disabled:boolean;
}) {
  return <details className="my-4"><summary>예약 없는 일반 관람 일정 (선택)</summary>
    <fieldset disabled={disabled} className="grid gap-3 py-3">
      <label><input type="checkbox" checked={!!value} onChange={e=>onChange(e.target.checked ? {...blank} : null)}/> 사전예약 없이 입장해 아래 대상을 일반 관람할 수 있음을 원문에서 확인했습니다</label>
      {value && <>
        <label>관람 대상 <select value={value.subject} onChange={e=>{
          const subject = e.target.value as Viewing['subject'];
          const next = {...value, subject};
          delete next.labelKo; delete next.labelJa;
          onChange(subject === 'other' ? {...next,labelKo:'',labelJa:''} : next);
        }}>{Object.entries(viewingSubjects).map(([k,v])=><option key={k} value={k}>{v[0]}</option>)}</select></label>
        {value.subject === 'other' && <>
          <label>관람 대상 (한국어) <input required maxLength={80} value={value.labelKo ?? ''} onChange={e=>onChange({...value,labelKo:e.target.value})}/></label>
          <label>관람 대상 (일본어) <input required maxLength={80} value={value.labelJa ?? ''} onChange={e=>onChange({...value,labelJa:e.target.value})}/></label>
        </>}
        <label>관람 시작일 <input type="date" required value={value.from} onChange={e=>onChange({...value,from:e.target.value})}/></label>
        <label>관람 종료일 <input type="date" required min={value.from} value={value.through} onChange={e=>onChange({...value,through:e.target.value})}/></label>
        <fieldset><legend>일반 관람 운영 요일</legend>{Array.from('일월화수목금토').map((s,i)=><label key={s} className="mr-3"><input type="checkbox" checked={value.weekdays.includes(i)} onChange={e=>onChange({...value,weekdays:e.target.checked?[...value.weekdays,i].sort():value.weekdays.filter(d=>d!==i)})}/> {s}</label>)}</fieldset>
        <label>임시 휴관·제외일 (한 줄에 하나, YYYY-MM-DD) <textarea value={value.exceptions.join('\n')} onChange={e=>onChange({...value,exceptions:e.target.value ? e.target.value.split('\n') : []})}/></label>
      </>}
    </fieldset></details>;
}
