'use client';

import { Layers, MapPin, Monitor, Users } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import type { ContentFilters } from '@/app/lib/contentFilters';
import styles from './ProgramListLayout.module.css';

// Display confirmed public facts only; absent delivery is never inferred as onsite.
export default function ProgramComparisonFacts({ filters }: { filters?: ContentFilters | null }) {
  const t = useTranslations('PublicFilters'), locale = useLocale();
  const location = filters?.location;
  const regions = location?.status === 'known'
    ? location.value.scope === 'nationwide' ? [locale === 'ja' ? '全国' : '전국']
      : [...new Set(location.value.venues.map(venue => {
        const province = t(`provinces.${venue.province}`);
        const district = venue.district
          ? locale === 'ja' ? t(`districts.${venue.province}.${venue.district}`) : venue.district
          : null;
        return district ? `${province} ${district}` : province;
      }))]
    : [];
  const delivery = filters?.delivery.status === 'known' ? filters.delivery.value : null;
  const showDelivery = delivery === 'online' || delivery === 'mixed';
  const topic = filters?.topic.status === 'known' ? filters.topic.value : null;
  const DeliveryIcon = delivery === 'online' ? Monitor : Users;
  if (!regions.length && location?.status !== 'unknown' && !showDelivery && !topic) return null;
  return <ul className={styles.facts}>
    {regions.length > 0 ? <li><MapPin aria-hidden="true"/><span>{regions.join(' · ')}</span></li>
      : location?.status === 'unknown' ? <li className={styles.unknown}><MapPin aria-hidden="true"/><span>{locale === 'ja' ? '地域情報未確認' : '지역 정보 미확인'}</span></li> : null}
    {showDelivery && <li><DeliveryIcon aria-hidden="true"/><span>{t(`deliveries.${delivery}`)}</span></li>}
    {topic && <li><Layers aria-hidden="true"/><span>{t(`programTopics.${topic}`)}</span></li>}
  </ul>;
}
