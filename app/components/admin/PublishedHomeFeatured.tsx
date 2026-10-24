'use client';
import { useEffect, useRef, useState } from 'react';
import { featuredDetail, type FeaturedDetail } from '@/app/lib/home-featured/admin';
import { fieldClass, primaryButton, secondaryButton } from './ReviewEditors';

export default function PublishedHomeFeatured({ id, disabled, onBlocked }: { id: string; disabled: boolean; onBlocked: (value: boolean) => void }) {
  const [item, setItem] = useState<FeaturedDetail | null>(null), [position, setPosition] = useState<1 | 2>(1);
  const [editing, setEditing] = useState(false), [busy, setBusy] = useState(false), [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const sending = useRef(false);
  useEffect(() => { onBlocked(editing || busy); return () => onBlocked(false); }, [editing, busy, onBlocked]);
  useEffect(() => {
    const abort = new AbortController();
    void fetch(`/api/admin/review-home-featured/${id}`, { cache: 'no-store', credentials: 'same-origin', signal: abort.signal })
      .then(async r => { const data = await r.json(); if (!r.ok) throw Error('read'); const next = featuredDetail(data.item, id);
        if (!abort.signal.aborted) { setItem(next); setPosition(next.position ?? 1); } })
      .catch(() => { if (!abort.signal.aborted) setError('대표 고정 정보를 확인하지 못했습니다.'); });
    return () => abort.abort();
  }, [id]);
  async function reload() {
    if (sending.current) return; setBusy(true); setError(''); setNotice('');
    try {
      const r = await fetch(`/api/admin/review-home-featured/${id}`, { cache: 'no-store', credentials: 'same-origin' });
      const data = await r.json(); if (!r.ok) throw Error('read'); const next = featuredDetail(data.item, id);
      setItem(next); setPosition(next.position ?? 1); setEditing(false); setUncertain(false);
    } catch { setError('대표 고정 정보를 확인하지 못했습니다.'); } finally { setBusy(false); }
  }
  async function save(targetId: string, nextPosition: 1 | 2 | null) {
    if (!item || disabled || busy || sending.current || uncertain) return;
    if (nextPosition !== null && (!item.eligible || !item.position && item.pins.length === 2 || nextPosition === item.position)) return;
    sending.current = true; setBusy(true); setError(''); setNotice('');
    try {
      const r = await fetch(`/api/admin/review-home-featured/${id}`, { method: 'POST', cache: 'no-store', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision: item.revision, version: item.version,
          targetId, position: nextPosition, requestId: crypto.randomUUID() }) });
      const data = await r.json().catch(() => null);
      if (!r.ok) {
        setError(data?.code === 'conflict' ? '다른 변경으로 저장 버전이 달라졌습니다. 선택은 유지했습니다.'
          : data?.code === 'signed_out' || data?.code === 'forbidden' ? '관리자 권한을 확인하지 못했습니다. 선택은 유지했습니다.'
          : '고정 저장 결과를 확인하지 못했습니다. 자동 재시도하지 않습니다.'); setUncertain(true); return;
      }
      const next = featuredDetail(data?.item, id);
      if (next.revision !== item.revision || next.version === item.version || next.stateVersion !== item.stateVersion + 1
        || (next.pins.find(pin => pin.id === targetId)?.position ?? null) !== nextPosition) throw Error('unknown');
      setItem(next); setPosition(next.position ?? 1); setEditing(false);
      setNotice(nextPosition === null ? '대표 고정을 해제했습니다. 남은 자리는 자동으로 채웁니다.' : '대표 고정 순서를 저장했습니다.');
    } catch { setError('고정 저장 결과를 확인하지 못했습니다. 선택을 유지하며 자동 재시도하지 않습니다.'); setUncertain(true); }
    finally { sending.current = false; setBusy(false); }
  }
  return <section className="my-6 border-b border-info-rule pb-5" aria-label="홈 대표 콘텐츠 고정" aria-busy={busy}>
    <h3 className="font-semibold">홈 대표 콘텐츠 고정</h3>
    <p className="mt-2 text-sm leading-7 text-info-muted">최대 2개를 먼저 표시하고, 나머지는 자동으로 채웁니다. 종료되거나 공개 조건을 충족하지 않으면 노출에서 제외합니다.</p>
    {item ? <>
      <p className="mt-2 leading-7 text-info-body">이 글: {item.position ? `${item.position}번째 고정${item.eligible ? '' : ' · 현재 노출 제외'}` : item.eligible ? '자동 선정 대상' : '현재 대표 노출 대상이 아닙니다.'}</p>
      {item.pins.length > 0 && <ol className="mt-3 space-y-2" aria-label="현재 고정한 콘텐츠">{item.pins.map(pin => <li key={pin.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="min-w-0 break-words leading-7 text-info-body">{pin.position}. {pin.title}{!pin.eligible && ' · 현재 노출 제외'}</span>
        <button type="button" className={secondaryButton} aria-label={`${pin.title} 고정 해제`} disabled={disabled || busy || uncertain || editing} onClick={() => void save(pin.id, null)}>해제</button>
      </li>)}</ol>}
      {!editing ? <button type="button" className={`${secondaryButton} mt-3`} disabled={disabled || busy || uncertain || !item.eligible || !item.position && item.pins.length === 2}
        onClick={() => { setPosition(item.position ?? (item.pins.length ? 2 : 1)); setEditing(true); setError(''); setNotice(''); }}>{item.position ? '고정 순서 변경' : '대표로 고정'}</button>
        : <form className="mt-4" onSubmit={e => { e.preventDefault(); void save(item.publishedId, position); }}>
          <label className="block">고정 순서<select className={`${fieldClass} mt-2 max-w-sm`} value={position} disabled={disabled || busy || uncertain} onChange={e => setPosition(Number(e.target.value) as 1 | 2)}>
            <option value={1}>1번째</option>{(item.pins.length - Number(Boolean(item.position))) > 0 && <option value={2}>2번째</option>}
          </select></label>
          <div className="mt-3 flex flex-wrap gap-2"><button type="submit" className={primaryButton} disabled={disabled || busy || uncertain || position === item.position}>{busy ? '저장 중…' : '고정 저장'}</button>
            <button type="button" className={secondaryButton} disabled={busy} onClick={() => { setPosition(item.position ?? 1); setEditing(false); if (!uncertain) setError(''); }}>취소</button></div>
        </form>}
      {!item.position && item.pins.length === 2 && <p className="mt-2 text-sm leading-7 text-info-muted">이미 2개가 고정돼 있습니다. 먼저 한 항목을 해제해 주세요.</p>}
    </> : !error && <p className="mt-2 text-info-muted">대표 고정 정보를 불러오는 중입니다.</p>}
    {error && <p role="alert" className="mt-3 leading-7 text-info-status">{error}</p>}
    {notice && <p role="status" className="mt-3 leading-7 text-info-body">{notice}</p>}
    {(uncertain || !item && error) && <button type="button" className={`${secondaryButton} mt-3`} disabled={disabled || busy} onClick={() => void reload()}>{editing ? '선택 취소·최신 고정 정보 확인' : '최신 고정 정보 확인'}</button>}
  </section>;
}
