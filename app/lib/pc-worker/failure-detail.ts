import labels from './failure-labels.json' with {type:'json'};

type Value = null | boolean | number | string | Value[];
export type FailureDetail = {
  stage:keyof typeof labels.stage; code:string; rule:keyof typeof labels.rule; reason:keyof typeof labels.reason;
  location?:Record<string,string|number>; expected?:Value; actual?:Value;
};
const atoms = new Set('date time people families age count minimum maximum under over approximately'.split(' '));
const codes = new Set('unknown ai_schema_error ai_or_enqueue_failed ai_refusal ai_unexpected_thinking ai_timeout ai_network ai_call_budget ai_sampling_forbidden ai_cost_bound_breach ai_blocked_cost_cap ai_http_400 ai_http_401 ai_http_403 ai_http_404 ai_http_429 ai_http_4xx ai_http_5xx'.split(' '));
function validValue(v:unknown, depth=0):boolean {
  if (Array.isArray(v)) return depth<3 && v.length<=6 && v.every(part=>validValue(part,depth+1));
  return v===null || typeof v==='boolean' || typeof v==='number' && Number.isInteger(v) && Math.abs(v)<=1e9
    || typeof v==='string' && (atoms.has(v)||/^-?\d{1,10}(?:\.\d{1,6})?$/.test(v));
}
const fieldNames:Record<string,string>={content_ko:'한국어 본문',content_ja:'일본어 본문',title_ja:'일본어 제목',title:'제목',body:'본문',facts:'사실값','facts.audience':'대상','facts.geo_age_income':'지역·연령·소득','facts.amount_period_deadline':'금액·기간·기한','facts.how_to_apply':'신청 방법',one_line_summary:'한 줄 요약',application:'신청 기간',operation:'운영 기간',meeting:'집결',deadline:'마감'};
const coords:Record<string,string>={table:'표',row:'행',column:'열',line:'줄',item:'항목'};
export function failureDetail(raw:unknown):FailureDetail {
  const d=raw as FailureDetail;
  if(!d || typeof d!=='object' || !Object.hasOwn(labels.stage,d.stage) || !codes.has(d.code)
    || !Object.hasOwn(labels.rule,d.rule) || !Object.hasOwn(labels.reason,d.reason)
    || Object.keys(d).some(k=>!['stage','code','rule','reason','location','expected','actual'].includes(k))
    || 'expected' in d && !validValue(d.expected) || 'actual' in d && !validValue(d.actual)) throw Error('invalid_failure_detail');
  if('location' in d && (!d.location || typeof d.location!=='object' || Array.isArray(d.location)
    || Object.entries(d.location).some(([k,v])=>Object.hasOwn(coords,k)?typeof v!=='number'||!Number.isInteger(v)||v<0||v>100000
      : !['field','period_role'].includes(k)||typeof v!=='string'||!Object.hasOwn(fieldNames,v)))) throw Error('invalid_failure_location');
  return d;
}
const tags:Record<string,string>={people:'명',families:'가족',age:'나이',minimum:'최소',maximum:'최대',under:'미만',over:'초과',approximately:'약',count:'수량'};
export function displayComparison(v:Value|undefined,rule:string):string {
  if(v==null)return '확인값 없음';
  if(Array.isArray(v)){
    if(!v.length)return '검출값 없음';
    if(v[0]==='time')return v.slice(1).filter(x=>x!==null).map(x=>String(x).padStart(2,'0')).join(':');
    if(v[0]==='date')return v.slice(1).filter(x=>x!==null).join('.');
    if(rule==='schedule_times' && v.length===2 && v.every(n=>typeof n==='number'))
      return (v as number[]).map(n=>Math.floor(n/60)+':'+String(n%60).padStart(2,'0')).join('–');
    if(rule==='schedule_dates' && v.length===2 && v.every(n=>typeof n==='number'))return v[0]+'월 '+v[1]+'일';
    if(rule==='reviewed_fee' && typeof v[1]==='boolean')return [v[1]?'무료':'',Array.isArray(v[0])&&v[0].length?displayComparison(v[0],rule)+'원':''].filter(Boolean).join(' · ')||'금액 미검출';
    return v.map(x=>displayComparison(x,rule)).join(' · ');
  }
  if(typeof v==='number' && ['schedule_weekdays','dated_schedule_weekday'].includes(rule))return '월화수목금토일'[v]+'요일';
  return tags[String(v)]??String(v);
}
export function failureLines(d:FailureDetail):string[] {
  const position=Object.entries(d.location??{}).map(([k,v])=>typeof v==='number'?v+coords[k]:fieldNames[v]).join(' · ');
  const common:Record<string,string>={ai_http_401:'Pro 인증 실패',ai_http_403:'Pro 접근 권한 부족',ai_http_429:'사용량 또는 호출 한도',ai_timeout:'AI 응답 시간 초과',ai_network:'AI 연결 결과 불명',ai_call_budget:'호출 상한 도달',ai_blocked_cost_cap:'비용 상한 도달',ai_http_5xx:'AI 서비스 장애'};
  const lines=[labels.stage[d.stage]+' · '+labels.rule[d.rule],(common[d.code]??labels.reason[d.reason])+' ('+d.code+')'];
  if(position)lines.push(position);
  if(d.rule==='official_link' && d.reason==='missing'){
    const part=fieldNames[String(d.location?.field)] ?? '번역';
    const location=part.startsWith('일본어') ? part : '일본어 '+part;
    lines.push(`${location}에서 한국어 원문과 일치하는 공식 링크를 찾을 수 없습니다. 링크 주소와 표시 횟수를 확인해 주세요.`);
  }
  if(d.stage==='claim' && d.rule==='weekly_schedule_cell' && d.reason==='missing')
    lines.push('요약 호출 전 · 요일별 셀 위치 확인 필요. 공식 시간표의 빈칸까지 대조해 주세요.');
  if(d.stage==='japanese_validation' && ['schedule_dates','schedule_times','schedule_counts','schedule_weekdays','schedule_years'].includes(d.rule))
    lines.push('비교 근거: 확인된 일정·집결 안내와 일본어 본문');
  if('expected' in d || 'actual' in d)lines.push('기준값 '+displayComparison(d.expected,d.rule)+' / 검사값 '+displayComparison(d.actual,d.rule));
  return lines;
}
