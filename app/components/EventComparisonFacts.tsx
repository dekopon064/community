'use client';

import { CalendarDays, Layers, MapPin } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import type { ContentFilters, FilterEndpoint, FilterOccurrence } from '@/app/lib/contentFilters';
import listStyles from './ProgramListLayout.module.css';
import styles from './EventListLayout.module.css';

// Endpoints are validated KST dates/times; never fill missing times or infer a venue.
export default function EventComparisonFacts({ filters, occurrence }: {
  filters?: ContentFilters | null; occurrence: FilterOccurrence | null;
}) {
  const locale = useLocale(), t = useTranslations('PublicFilters');
  const japanese = locale === 'ja';
  const dateFormatter = new Intl.DateTimeFormat(japanese ? 'ja-JP' : 'ko-KR', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short',
  });
  const date = (endpoint: FilterEndpoint) => endpoint.value.slice(0, 10);
  const displayDate = (endpoint: FilterEndpoint) => dateFormatter.format(new Date(`${date(endpoint)}T12:00:00+09:00`));
  const displayTime = (endpoint: FilterEndpoint) => new Intl.DateTimeFormat(japanese ? 'ja-JP' : 'ko-KR', {
    timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    ...(endpoint.precision === 'second' ? { second: '2-digit' } : {}),
  }).format(new Date(endpoint.value));
  const sameDay = occurrence && date(occurrence.start) === date(occurrence.end);
  const location = filters?.location;
  const regions = location?.status === 'known'
    ? location.value.scope === 'nationwide' ? [japanese ? '全国' : '전국']
      : [...new Set(location.value.venues.map(venue => {
        const province = t(`provinces.${venue.province}`);
        const district = venue.district ? japanese ? t(`districts.${venue.province}.${venue.district}`) : venue.district : null;
        return district ? `${province} ${district}` : province;
      }))]
    : [];
  const topic = filters?.topic.status === 'known' ? filters.topic.value : null;

  return <>
    <div className={styles.date}>
      <CalendarDays aria-hidden="true"/>
      <div className={styles.dateContent}>
        <span className={styles.dateLabel}>{japanese ? '開催日' : '행사일'}</span>
        {occurrence ? <div className={styles.dateValue}>
          <span className={styles.days}>
            <time dateTime={date(occurrence.start)}>{displayDate(occurrence.start)}</time>
            {!sameDay && <>–<time dateTime={date(occurrence.end)}>{displayDate(occurrence.end)}</time></>}
          </span>
          {sameDay && occurrence.start.precision !== 'day' && occurrence.end.precision !== 'day'
            && <span className={styles.hours}><time dateTime={occurrence.start.value}>{displayTime(occurrence.start)}</time>
              {occurrence.end.value !== occurrence.start.value && <>–<time dateTime={occurrence.end.value}>{displayTime(occurrence.end)}</time></>}
            </span>}
          {!sameDay && (occurrence.start.precision !== 'day' || occurrence.end.precision !== 'day')
            && <span className={styles.hours}>{japanese ? '時刻は詳細で確認' : '시간은 상세에서 확인'}</span>}
        </div> : <span>{japanese ? '日程情報未確認' : '일정 정보 미확인'}</span>}
      </div>
    </div>
    {(regions.length > 0 || location?.status === 'unknown' || topic) && <ul className={listStyles.facts} data-event-facts>
      {regions.length > 0 ? <li><MapPin aria-hidden="true"/><span>{regions.join(' · ')}</span></li>
        : location?.status === 'unknown' ? <li className={listStyles.unknown}><MapPin aria-hidden="true"/><span>{japanese ? '地域情報未確認' : '지역 정보 미확인'}</span></li> : null}
      {topic && <li><Layers aria-hidden="true"/><span>{t(`eventTopics.${topic}`)}</span></li>}
    </ul>}
  </>;
}
