import { workerSources } from '../pc-worker/contracts';

export function candidateSourceName(name: string): string {
  return workerSources[name] ?? (/^[a-z0-9_-]+$/i.test(name) ? '수집원 이름 확인 필요' : name || '수집원 확인 필요');
}

// Display only. Do not reinterpret naive timestamps or remove stored precision.
export function candidatePeriodText(value: string): string {
  return value.replace(/\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2}))?/g, token => {
    if (/^\d{4}-\d{2}-\d{2}$/.test(token)) return token.replaceAll('-', '.');
    const date = new Date(token);
    if (!Number.isFinite(date.valueOf())) return token;
    const parts = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Seoul', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23'}).formatToParts(date);
    const get = (type: string) => parts.find(p => p.type === type)?.value;
    const seconds = /:\d{2}:\d{2}/.test(token) ? `:${get('second')}${token.match(/\.\d+/)?.[0] ?? ''}` : '';
    return `${get('year')}.${get('month')}.${get('day')} ${get('hour')}:${get('minute')}${seconds} (한국 시간)`;
  }) || '기록 없음';
}
