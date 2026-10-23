"use client";

import { useId, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import Link from './PublicNavigationLink';
import { eventTopics, programTopics, provinceLabels } from '../lib/contentFilters';
import { homeDistricts, homeFinderHref, homeWords } from '../lib/homePresentation';
import styles from './HomeExperience.module.css';

export default function HomeFinder({ locale }: { locale: string }) {
  const words = homeWords(locale), t = useTranslations('PublicFilters'), id = useId();
  const [category, setCategory] = useState<'program' | 'event'>('program');
  const [topic, setTopic] = useState(''), [region, setRegion] = useState('');
  const tabs = useRef<Partial<Record<'program' | 'event', HTMLButtonElement | null>>>({});
  function changeCategory(value: 'program' | 'event') { setCategory(value); setTopic(''); }
  return <aside className={styles.finder} aria-labelledby={`${id}-heading`}>
    <h2 id={`${id}-heading`}>{words.finder}</h2>
    <div role="tablist" aria-label={words.finder} className={styles.tabs}>
      {(['program', 'event'] as const).map(value => <button key={value} ref={node => { tabs.current[value] = node; }}
        id={`${id}-${value}`} type="button" role="tab" aria-selected={category === value}
        tabIndex={category === value ? 0 : -1} aria-controls={`${id}-fields`} onClick={() => changeCategory(value)}
        onKeyDown={event => {
          if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          const next = event.key === 'Home' ? 'program' : event.key === 'End' ? 'event' : category === 'program' ? 'event' : 'program';
          changeCategory(next); tabs.current[next]?.focus();
        }}>{words[value]}</button>)}
    </div>
    <div role="tabpanel" id={`${id}-fields`} aria-labelledby={`${id}-${category}`}>
      <label className={styles.field}>{category === 'program' ? words.topic : words.eventTopic}
        <select value={topic} onChange={event => setTopic(event.target.value)}>
          <option value="">{words.all}</option>
          {Object.keys(category === 'program' ? programTopics : eventTopics).map(value =>
            <option key={value} value={value}>{t(`${category === 'program' ? 'programTopics' : 'eventTopics'}.${value}`)}</option>)}
        </select>
      </label>
      <label className={styles.field}>{words.region}
        <select value={region} onChange={event => setRegion(event.target.value)}>
          <option value="">{words.all}</option>
          {(Object.keys(provinceLabels) as (keyof typeof provinceLabels)[]).map(province =>
            <optgroup key={province} label={t(`provinces.${province}`)}>
              <option value={province}>{t(`provinces.${province}`)} {words.whole}</option>
              {homeDistricts(province, locale).map(district => <option key={district} value={`${province}:${district}`}>
                {t(`provinces.${province}`)} {locale === 'ja' ? t(`districts.${province}.${district}`) : district}
              </option>)}
            </optgroup>)}
        </select>
      </label>
      <Link href={homeFinderHref(category, topic, region)} className={styles.findAction}>{category === 'program' ? words.findProgram : words.findEvent}</Link>
      <p className={styles.finderNote}>{words.finderNote}</p>
    </div>
  </aside>;
}
