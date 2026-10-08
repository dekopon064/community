'use client';

import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { ChevronDown, RotateCcw, SlidersHorizontal, X } from 'lucide-react';
import CurationCard from './CurationCard';
import InfoStatePanel from './InfoStatePanel';
import PublicFilterCalendar from './PublicFilterCalendar';
import { districtChoices, eventTopics, programTopics, provinceLabels } from '@/app/lib/contentFilters';
import type { FilterCategory, FilterEndpoint } from '@/app/lib/contentFilters';
import { applicationStates, deliveries, eventTiming, exploreCurations, nextExplorationTransition, programTiming, readExplorationQuery, writeExplorationQuery } from '@/app/lib/publicContentFilters';
import type { ExplorationQuery, PublicCurationItem } from '@/app/lib/publicContentFilters';
import Link from './PublicNavigationLink';
import styles from './PublicCurationFilters.module.css';

type MultiKey = 'topics' | 'provinces' | 'districts' | 'deliveries' | 'audiences' | 'states';
type GroupKey = 'topics' | 'region' | 'states' | 'additional' | 'date';
type Choice = { key: MultiKey | 'date'; value: string; label: string };

export default function PublicCurationList({items,category,todayKst,nowIso}:{items:PublicCurationItem[];category?:FilterCategory;todayKst:string;nowIso:string}) {
  const locale=useLocale(), t=useTranslations('PublicFilters'), infoT=useTranslations('Info'), categoriesT=useTranslations('Categories');
  const params=useSearchParams(), id=useId();
  const [openGroup,setOpenGroup]=useState<GroupKey | null>(null);
  const [panelOpen,setPanelOpen]=useState(false);
  const [position,setPosition]=useState({left:12,top:12,width:360,maxHeight:600});
  const popover=useRef<HTMLDivElement>(null), dialog=useRef<HTMLDialogElement>(null);
  const triggers=useRef<Partial<Record<GroupKey,HTMLButtonElement>>>({});
  const filterTrigger=useRef<HTMLButtonElement>(null), panelClose=useRef<HTMLButtonElement>(null);
  const selectedControls=useRef<HTMLUListElement>(null);
  const savedScroll=useRef(0);
  const rawParams=new URLSearchParams(params.toString());
  // Default tab is a view choice. The shared query parser and data classifications are unchanged.
  if(category==='youth_space'&&!rawParams.getAll('space').some(value=>value==='introduction'||value==='news')) rawParams.set('space','introduction');
  const parsed=readExplorationQuery(rawParams,category);
  const query=parsed;
  // A legacy URL with both values retains its OR result until a tab is selected.
  const spaceKind=query.spaceKinds.length===1?query.spaceKinds[0]:null;
  const multipleSpaces=category==='youth_space'&&query.spaceKinds.length>1;
  const regionAvailable=category!=='youth_space'||query.spaceKinds.includes('introduction');
  const multipleAudiences=query.audiences.length>1;
  const [now,setNow]=useState(()=>Date.parse(nowIso));
  useEffect(()=>{
    const refresh=()=>setNow(Date.now());
    refresh();
    window.addEventListener('focus',refresh);
    document.addEventListener('visibilitychange',refresh);
    return()=>{window.removeEventListener('focus',refresh);document.removeEventListener('visibilitychange',refresh);};
  },[]);
  useEffect(()=>{
    const transition=nextExplorationTransition(items,now);
    if(transition===null) return;
    const timer=setTimeout(()=>setNow(Date.now()),Math.min(Math.max(0,transition-Date.now()),2147483647));
    return()=>clearTimeout(timer);
  },[items,now]);

  const results=category?exploreCurations(items,category,query,now):items;
  function update(next:ExplorationQuery) {
    const search=writeExplorationQuery(new URLSearchParams(window.location.search),next,category).toString();
    window.history.pushState(null,'',window.location.pathname+(search?'?'+search:'')+window.location.hash);
  }
  function toggle(key:MultiKey,value:string) {
    const values=query[key] as string[];
    const next={...query,[key]:values.includes(value)?values.filter(v=>v!==value):[...values,value]};
    if(key==='provinces') next.districts=query.districts.filter(d=>next.provinces.some(p=>d.startsWith(`${p}:`)));
    update(next);
  }
  function closePopover(restore=true) {
    if(restore&&openGroup) triggers.current[openGroup]?.focus({preventScroll:true});
    setOpenGroup(null);
  }
  function focusAfterRemoval() {
    requestAnimationFrame(()=>{
      const next=selectedControls.current?.querySelector<HTMLButtonElement>('button')||filterTrigger.current||Object.values(triggers.current)[0];
      next?.focus({preventScroll:true});
    });
  }
  function reset() {
    const empty=readExplorationQuery(new URLSearchParams(),category);
    update({...empty,sort:query.sort,spaceKinds:query.spaceKinds});
    if(panelOpen) panelClose.current?.focus({preventScroll:true});
    else focusAfterRemoval();
  }
  function chooseSpace(value:string) {
    if(value===spaceKind) return;
    closePopover(false);
    update({...query,spaceKinds:[value]});
  }
  function optionLabel(key:MultiKey,value:string):string {
    if(key==='topics') return t(`${category==='event'?'eventTopics':'programTopics'}.${value}`);
    if(key==='provinces') return t(`provinces.${value}`);
    if(key==='districts') {const [province,district]=value.split(':');return `${t(`provinces.${province}`)} ${locale==='ja'?t(`districts.${province}.${district}`):district}`;}
    if(key==='audiences') return t(value==='children'?'childrenIncluded':'childrenExcluded');
    return t(`${key}.${value}`);
  }
  const selected:Choice[]=regionAvailable?[
    ...(['topics','states','deliveries'] as const).flatMap(key=>query[key].map(value=>({key,value,label:optionLabel(key,value)}))),
    ...(multipleAudiences?[{key:'audiences' as const,value:'both',label:t('audienceBoth')}]:query.audiences.map(value=>({key:'audiences' as const,value,label:optionLabel('audiences',value)}))),
    ...query.provinces.filter(province=>!query.districts.some(d=>d.startsWith(`${province}:`))).map(value=>({key:'provinces' as const,value,label:t('provinceWhole',{province:optionLabel('provinces',value)})})),
    ...query.districts.map(value=>({key:'districts' as const,value,label:optionLabel('districts',value)})),
    ...(query.date?[{key:'date' as const,value:query.date,label:`${t('date')} ${query.date.replaceAll('-','.')}`}]:[]),
  ]:[];
  const count=selected.length;
  const groups:{key:GroupKey;label:string}[]=category==='program'?[{key:'topics',label:t('programTopic')},{key:'region',label:t('region')},{key:'states',label:t('applicationState')},{key:'additional',label:t('additional')}]:category==='event'?[{key:'topics',label:t('eventTopic')},{key:'region',label:t('region')},{key:'date',label:t('date')}]:[{key:'region',label:t('spaceRegion')}];
  function groupCount(key:GroupKey) {
    if(key==='region') return selected.filter(c=>c.key==='provinces'||c.key==='districts').length;
    if(key==='additional') return query.deliveries.length+(multipleAudiences?1:query.audiences.length);
    if(key==='date') return Number(Boolean(query.date));
    return query[key].length;
  }
  function summary(key:GroupKey) {
    if(key==='date') return query.date.replaceAll('-','.')||t('unrestricted');
    if(key==='region') return selected.filter(c=>c.key==='provinces'||c.key==='districts').map(c=>c.label).join(' · ')||t('unrestricted');
    return groupCount(key)?t('selectionCount',{count:groupCount(key)}):t('unrestricted');
  }
  useLayoutEffect(()=>{
    if(!openGroup) return;
    const place=()=>{
      const trigger=triggers.current[openGroup];
      if(!trigger) return;
      const rect=trigger.getBoundingClientRect(), width=Math.min(openGroup==='region'?440:360,window.innerWidth-24);
      const height=popover.current?.scrollHeight||360, below=window.innerHeight-rect.bottom-20;
      const top=below<220&&rect.top>below?Math.max(12,rect.top-Math.min(height,rect.top-20)-8):Math.min(rect.bottom+8,window.innerHeight-156);
      const next={left:Math.max(12,Math.min(rect.left,window.innerWidth-width-12)),top,width,maxHeight:Math.max(144,window.innerHeight-top-12)};
      setPosition(previous=>Object.keys(next).every(key=>previous[key as keyof typeof previous]===next[key as keyof typeof next])?previous:next);
    };
    place();
    const observer=new ResizeObserver(place);
    if(popover.current) observer.observe(popover.current);
    window.addEventListener('resize',place);
    window.addEventListener('scroll',place,true);
    return()=>{observer.disconnect();window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);};
  },[openGroup]);
  useEffect(()=>{
    if(!openGroup) return;
    popover.current?.querySelector<HTMLElement>('input,button[data-date][tabindex="0"]')?.focus({preventScroll:true});
    const outside=(event:PointerEvent)=>{
      const target=event.target as Node;
      if(!popover.current?.contains(target)&&!Object.values(triggers.current).some(trigger=>trigger?.contains(target))) {
        triggers.current[openGroup]?.focus({preventScroll:true});setOpenGroup(null);
      }
    };
    const keyboard=(event:globalThis.KeyboardEvent)=>{
      if(event.key==='Escape'){event.preventDefault();triggers.current[openGroup]?.focus({preventScroll:true});setOpenGroup(null);}
    };
    const leave=(event:FocusEvent)=>{
      const target=event.target as Node;
      if(!popover.current?.contains(target)&&!Object.values(triggers.current).some(trigger=>trigger?.contains(target))) setOpenGroup(null);
    };
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',keyboard);document.addEventListener('focusin',leave);
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',keyboard);document.removeEventListener('focusin',leave);};
  },[openGroup]);
  useEffect(()=>{
    if(!panelOpen) return;
    const panel=dialog.current;
    if(!panel) return;
    savedScroll.current=window.scrollY;
    const previousOverflow=document.body.style.overflow;
    const returnTrigger=filterTrigger.current;
    document.body.style.setProperty('overflow','hidden');
    panel.showModal();panelClose.current?.focus({preventScroll:true});
    return()=>{
      panel.close();document.body.style.setProperty('overflow',previousOverflow);
      window.scrollTo({top:savedScroll.current,behavior:'instant'});
      returnTrigger?.focus({preventScroll:true});
    };
  },[panelOpen]);
  useEffect(()=>{
    const media=window.matchMedia('(max-width:767px)');
    const resize=()=>{setOpenGroup(null);setPanelOpen(false);};
    media.addEventListener('change',resize);
    return()=>media.removeEventListener('change',resize);
  },[]);
  function options(key:MultiKey,values:readonly string[],label:string,compact=false) {
    return <fieldset className={styles.fieldset}><legend className="sr-only">{label}</legend><div className={`${styles.options} ${compact?styles.compactOptions:''}`}>{values.map(value=><label key={value} className={`${styles.option} ${(query[key] as string[]).includes(value)?styles.optionSelected:''}`}>
      <input type="checkbox" checked={(query[key] as string[]).includes(value)} onChange={()=>toggle(key,value)}/><span>{key==='districts'?(locale==='ja'?t(`districts.${value.split(':')[0]}.${value.split(':')[1]}`):value.split(':')[1]):optionLabel(key,value)}</span>
    </label>)}</div></fieldset>;
  }
  function fields(key:GroupKey,scope:string) {
    if(key==='region') return <>
      {options('provinces',(['11','41','28'] as const).filter(value=>value in provinceLabels),t(category==='youth_space'?'spaceRegion':'region'),true)}
      <p className={styles.note}>{t('regionScopeNote')}</p>
      {query.provinces.map(province=><div key={province} className={styles.districtGroup}>
        <h3>{t('districtFor',{province:t(`provinces.${province}`)})}</h3>
        <div className={styles.districtScroll}>{options('districts',districtChoices[province].map(d=>`${province}:${d}`),t('district'))}</div>
      </div>)}
    </>;
    if(key==='additional') return <div className={styles.additional}>
      <div><h3>{t('delivery')}</h3>{options('deliveries',deliveries,t('delivery'),true)}</div>
      <fieldset className={styles.fieldset} aria-describedby={multipleAudiences?`${id}-${scope}-audience-compat`:undefined}><legend>{t('audience')}</legend><div className={styles.compactOptions}>
        {(['children','other'] as const).map(value=><label key={value} className={`${styles.option} ${query.audiences.length===1&&query.audiences.includes(value)?styles.optionSelected:''}`}><input type="radio" name={`${id}-${scope}-audience`} checked={query.audiences.length===1&&query.audiences.includes(value)} onChange={()=>update({...query,audiences:[value]})}/><span>{t(value==='children'?'include':'exclude')}</span></label>)}
      </div>{multipleAudiences&&<p id={`${id}-${scope}-audience-compat`} className={styles.note}>{t('audienceBothHint')}</p>}</fieldset>
    </div>;
    if(key==='date') return <PublicFilterCalendar value={query.date} today={todayKst} onChange={date=>update({...query,date})}/>;
    return key==='states'?options('states',applicationStates,t('applicationState'),true):options('topics',Object.keys(category==='program'?programTopics:eventTopics),t(category==='program'?'programTopic':'eventTopic'));
  }
  function resetButton(scope:string) {
    return <span className={styles.resetControl}><button type="button" className={`${styles.iconButton} ${styles.resetButton}`} aria-label={t('resetAll')} aria-describedby={`${id}-${scope}-reset-hint`} onClick={reset}><RotateCcw size={16} aria-hidden="true"/></button><span id={`${id}-${scope}-reset-hint`} className={styles.resetHint} role="tooltip">{t('resetHint')}</span></span>;
  }
  function formatEndpoint(value:FilterEndpoint) {
    if(value.precision==='day')return value.value.replaceAll('-','.');
    return new Intl.DateTimeFormat(locale==='ja'?'ja-JP':'ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',...(value.precision==='second'?{second:'2-digit'}:{}),hourCycle:'h23'}).format(new Date(value.value));
  }
  function period(item:PublicCurationItem) {
    if(category==='program') {
      const timing=programTiming(item,now);
      return <span className="text-info-status">{t(`states.${timing.state}`)}{timing.deadline?<>{' · '}{t('deadline')} <time className="whitespace-nowrap" dateTime={timing.deadline.value}>{formatEndpoint(timing.deadline)}</time></>:<>{' · '}{t(timing.deadlineKind==='none'?'noDeadline':'unknownDeadline')}</>}</span>;
    }
    if(category==='event') {
      const timing=eventTiming(item,now), occurrence=timing.occurrence;
      return <span className="text-info-status">{t(`eventStates.${timing.state}`)}{occurrence&&<>{' · '}<time className="whitespace-nowrap" dateTime={occurrence.start.value}>{formatEndpoint(occurrence.start)}</time>{occurrence.start.value!==occurrence.end.value&&<>{' – '}<time className="whitespace-nowrap" dateTime={occurrence.end.value}>{formatEndpoint(occurrence.end)}</time></>}</>}</span>;
    }
    return undefined;
  }

  const filteredEmpty=items.length>0&&(count>0||(category==='youth_space'&&query.spaceKinds.length>0));
  return <>
    {category==='youth_space'&&<div className={styles.spaceTabs} role="tablist" aria-label={t('spaceKind')}>
      {(['introduction','news'] as const).map(value=><button key={value} id={`${id}-tab-${value}`} type="button" role="tab" aria-selected={spaceKind===value} aria-controls={`${id}-space-content`} tabIndex={spaceKind===value||(multipleSpaces&&value==='introduction')?0:-1} onClick={()=>chooseSpace(value)} onKeyDown={event=>{
        if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const target=event.key==='Home'?'introduction':event.key==='End'?'news':value==='introduction'?'news':'introduction';document.getElementById(`${id}-tab-${target}`)?.focus();}
      }}>{t(`spaceKinds.${value}`)}</button>)}
    </div>}
    {multipleSpaces&&<p className={styles.note}>{t('spaceBothHint')}</p>}
    <div id={category==='youth_space'?`${id}-space-content`:undefined} role={category==='youth_space'?'tabpanel':undefined} aria-labelledby={category==='youth_space'&&spaceKind?`${id}-tab-${spaceKind}`:undefined} aria-label={multipleSpaces?t('spaceBoth'):undefined}>
      {category&&<>
        {regionAvailable&&<>
          <div className={styles.desktopFilters}>
            {groups.map(group=><button key={group.key} ref={element=>{if(element)triggers.current[group.key]=element;}} type="button" className={`${styles.filterTrigger} ${groupCount(group.key)?styles.hasSelection:''}`} aria-expanded={openGroup===group.key} aria-controls={openGroup===group.key?`${id}-popover`:undefined} onClick={()=>openGroup===group.key?closePopover():setOpenGroup(group.key)}>
              <span className={styles.triggerTop}>{group.label}<ChevronDown size={16} aria-hidden="true"/></span><span className={styles.triggerValue}>{summary(group.key)}</span>
            </button>)}
          </div>
          <button ref={filterTrigger} type="button" className={styles.mobileFilter} aria-haspopup="dialog" aria-expanded={panelOpen} aria-controls={`${id}-panel`} onClick={()=>{closePopover(false);setPanelOpen(true);}}><SlidersHorizontal size={18} aria-hidden="true"/>{count?t('filterWithCount',{count}):t('filterButton')}</button>
          {count>0&&<div className={styles.selection}>
            <div className={styles.selectionHeader}><h2>{t('selected')} ({count})</h2>{resetButton('summary')}</div>
            <ul ref={selectedControls} className={styles.selected} aria-label={t('selected')}>{selected.map(choice=><li key={`${choice.key}:${choice.value}`}><button type="button" className={styles.selectedButton} aria-label={t('remove',{label:choice.label})} onClick={()=>{if(choice.key==='date')update({...query,date:''});else if(choice.key==='audiences'&&choice.value==='both')update({...query,audiences:[]});else toggle(choice.key,choice.value);focusAfterRemoval();}}>{choice.label}<X size={16} aria-hidden="true"/></button></li>)}</ul>
          </div>}
        </>}
        <div className={styles.toolbar}>
          <p tabIndex={-1} id="curation-results-title" role="status" aria-live="polite" aria-atomic="true" className={styles.resultTitle}>{infoT('resultCount',{count:results.length})}</p>
          {category!=='youth_space'?<label className={styles.sort} htmlFor={`${id}-sort`}><span>{t('sort')}</span><select id={`${id}-sort`} value={query.sort} onChange={event=>update({...query,sort:event.target.value==='latest'?'latest':'default'})}><option value="default">{t(category==='program'?'deadlineSort':'eventSort')}</option><option value="latest">{t('latestSort')}</option></select></label>:spaceKind==='news'&&<p className={styles.note}>{t('latestSort')}</p>}
        </div>
      </>}
      {!category&&<p tabIndex={-1} id="curation-results-title" role="status" aria-live="polite" className={`${styles.resultTitle} mb-4`}>{infoT('resultCount',{count:results.length})}</p>}
      <div id="curation-results" className="flex min-w-0 flex-col border-t border-info-rule">
        {results.length?results.map(item=><CurationCard key={item.id} slug={item.slug} category={item.userCategory} categoryLabel={item.userCategory?categoriesT(item.userCategory):null} title={item.title} summary={item.summary} imageUrl={item.source_image_url} summaryLabel={infoT('atAGlance')} locale={locale} deadlineKind={item.application_deadline_kind} deadlineOn={item.application_deadline_on} eventStartOn={item.event_start_on} eventEndOn={item.event_end_on} todayKst={todayKst} periodOverride={period(item)}/>):<InfoStatePanel title={infoT(filteredEmpty?'searchEmptyTitle':'emptyTitle')} description={infoT(filteredEmpty?'searchEmptyDescription':'emptyDescription')} role="status" headingLevel={2}>
          {count>0?<button type="button" onClick={reset} className="min-h-11 rounded-full bg-ink px-5 py-2.5 text-sm font-bold text-canvas-white hover:bg-action-hover">{t('reset')}</button>:<Link href="/info" className="inline-flex min-h-11 items-center rounded-full bg-ink px-5 py-2.5 text-sm font-bold text-canvas-white">{t('allCategories')}</Link>}
        </InfoStatePanel>}
      </div>
      {category&&regionAvailable&&<details className={styles.help}><summary>{t('help')}</summary><div><p>{t('combinationNote')}</p><p>{t('unknownNote')}</p><p>{t(category==='program'?'programRegionNote':category==='youth_space'?'spaceRegionNote':'regionNote')}</p>{category!=='youth_space'&&<p>{t(category==='program'?'programSortNote':'eventSortNote')}</p>}</div></details>}
    </div>
    {openGroup&&createPortal(<div ref={popover} id={`${id}-popover`} className={styles.popover} style={position} role="region" aria-labelledby={`${id}-popover-title`}>
      <div className={styles.popoverHeading}><h2 id={`${id}-popover-title`}>{groups.find(group=>group.key===openGroup)?.label}</h2><button type="button" className={styles.iconButton} aria-label={t('closeFilters')} onClick={()=>closePopover()}><X size={16} aria-hidden="true"/></button></div>
      {fields(openGroup,'popover')}
    </div>,document.body)}
    <dialog ref={dialog} id={`${id}-panel`} className={styles.mobilePanel} aria-labelledby={`${id}-panel-title`} onCancel={event=>{event.preventDefault();setPanelOpen(false);}} onClose={()=>setPanelOpen(false)} onKeyDown={event=>{
      if(event.key!=='Tab') return;
      const controls=Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),a[href],[tabindex]')).filter(element=>element.tabIndex>=0&&element.getClientRects().length>0);
      const first=controls[0],last=controls[controls.length-1];
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus({preventScroll:true});}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus({preventScroll:true});}
    }}>
      {panelOpen&&<>
        <div className={styles.panelHeader}><div><h2 id={`${id}-panel-title`}>{t('conditions')}</h2><p role="status" aria-live="polite" aria-atomic="true">{infoT('resultCount',{count:results.length})}</p></div><button ref={panelClose} type="button" className={styles.iconButton} aria-label={t('closeFilters')} onClick={()=>setPanelOpen(false)}><X size={18} aria-hidden="true"/></button></div>
        <div className={styles.panelBody}>{groups.map(group=><section key={group.key} className={styles.panelGroup}><h3>{group.label}</h3>{fields(group.key,'panel')}</section>)}</div>
        <div className={styles.panelFooter}>{count>0&&resetButton('panel')}<button type="button" className={styles.primary} onClick={()=>setPanelOpen(false)}>{t('viewResultCount',{count:results.length})}</button></div>
      </>}
    </dialog>
  </>;
}
