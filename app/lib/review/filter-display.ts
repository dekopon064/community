import {programTopics,eventTopics,provinceLabels} from '../contentFilters';
import type {ContentFilters,FilterKey,FilterEndpoint} from '../contentFilters';
export function filterEndpointLabel(endpoint:FilterEndpoint):string {
 const date=endpoint.value.slice(0,10).replaceAll('-','.');
 return endpoint.precision==='day'?date:`${date} ${endpoint.value.slice(11,endpoint.precision==='second'?19:16)}`;
}
export function filterValueLabel(data:ContentFilters,key:FilterKey):string {
 const f=data[key];if(f.status!=='known')return f.status==='unknown'?'입력 전':'해당 없음';
 if(key==='topic'){const options:Record<string,string>=data.category==='program'?programTopics:eventTopics;return options[String(f.value)]??String(f.value);}
 if(key==='delivery')return {online:'온라인',onsite:'오프라인',mixed:'혼합'}[String(f.value) as 'online'];
 if(key==='audience')return f.value==='children'?'어린이 프로그램':'이외';
 if(key==='spaceKind')return f.value==='introduction'?'공간 소개':'관련 소식';
 if(key==='location'&&data.location.status==='known'){const v=data.location.value;return v.scope==='nationwide'?'실제 전국 이용':v.venues.map(x=>[provinceLabels[x.province],x.district??'시·도까지만 지정',x.facility,x.address].filter(Boolean).join(' · ')).join(' / ');}
 if(key==='application'&&data.application.status==='known'){const a=data.application.value;return `신청 시작 ${a.start?filterEndpointLabel(a.start):'미확인'}\n신청 마감 ${a.deadlineKind==='none'?'원래 마감일 없음':a.end?filterEndpointLabel(a.end):'미확인'}${a.sourceStatus==='unknown'?'':`\n접수 상태: ${{not_started:'신청 전',open:'접수 중',closed:'마감'}[a.sourceStatus]}`}`;}
 if(key==='schedule'&&data.schedule.status==='known')return data.schedule.value.occurrences.map(o=>o.start.value===o.end.value?filterEndpointLabel(o.start):`${filterEndpointLabel(o.start)} ~ ${filterEndpointLabel(o.end)}`).join('\n');
 return '미확인';
}
