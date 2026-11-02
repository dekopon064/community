'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { normalizePublicSearch, publicSearchLimit } from '@/app/lib/publicContentFilters';
import styles from './PublicCurationFilters.module.css';

export default function PublicContentSearch({id,value,onSearch}:{id:string;value:string;onSearch:(value:string)=>void}) {
  const t=useTranslations('PublicSearch');
  const [draft,setDraft]=useState(value);
  return <form role="search" className={styles.search} aria-label={t('label')} onSubmit={event=>{event.preventDefault();const next=normalizePublicSearch(draft);setDraft(next);onSearch(next);}}>
    <label htmlFor={`${id}-search`}>{t('label')}</label>
    <div className={styles.searchControls}>
      <input id={`${id}-search`} name="q" type="search" value={draft} maxLength={publicSearchLimit} placeholder={t('placeholder')} aria-describedby={`${id}-search-help`} onChange={event=>setDraft(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'&&(event.nativeEvent.isComposing||event.keyCode===229))event.preventDefault();}}/>
      <button type="submit" className={styles.searchSubmit}>{t('submit')}</button>
      {value&&<button type="button" className={styles.searchClear} onClick={()=>{setDraft('');onSearch('');}}>{t('clear')}</button>}
    </div>
    <p id={`${id}-search-help`} className={styles.note}>{t('help')}</p>
  </form>;
}
