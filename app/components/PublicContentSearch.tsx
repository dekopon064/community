'use client';

import { useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { normalizePublicSearch, publicSearchLimit } from '@/app/lib/publicContentFilters';
import styles from './PublicCurationFilters.module.css';

export default function PublicContentSearch({id,value,onSearch}:{id:string;value:string;onSearch:(value:string)=>void}) {
  const t=useTranslations('PublicSearch');
  const [draft,setDraft]=useState(value);
  const [previousValue,setPreviousValue]=useState(value);
  const input=useRef<HTMLInputElement>(null);
  // Restore URL state without replacing the focused input or reviving an old draft.
  if(value!==previousValue){setPreviousValue(value);setDraft(value);}
  function apply(nextDraft:string) {
    const next=normalizePublicSearch(nextDraft);
    setDraft(next);
    onSearch(next);
    input.current?.focus({preventScroll:true});
  }
  return <form role="search" className={styles.search} aria-label={t('label')} onSubmit={event=>{event.preventDefault();apply(draft);}}>
    <label htmlFor={`${id}-search`}>{t('label')}</label>
    <div className={styles.searchControls}>
      <input ref={input} id={`${id}-search`} name="q" type="search" value={draft} maxLength={publicSearchLimit} placeholder={t('placeholder')} aria-describedby={value?`${id}-applied-search`:undefined} onChange={event=>setDraft(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'&&(event.nativeEvent.isComposing||event.keyCode===229))event.preventDefault();}}/>
      <button type="submit" className={styles.searchSubmit}>{t('submit')}</button>
    </div>
    {value&&<button type="button" className={styles.searchClear} onClick={()=>apply('')}>{t('clear')}</button>}
  </form>;
}
