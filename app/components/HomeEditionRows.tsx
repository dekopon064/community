'use client';

import Image from 'next/image';
import { useState } from 'react';
import Link from './PublicNavigationLink';
import PublicPosterLink from './PublicPosterLink';
import { HomeArrow } from './HomeContentCard';
import type { WeeklyEntry, settlementArticles } from '../lib/homeEditions';
import css from './HomeEditions.module.css';

export function SettlementRow({ item }: { item: ReturnType<typeof settlementArticles>[number] }) {
  const [failed,setFailed] = useState<string | null>(null);
  const image = item.imageUrl && item.imageUrl !== failed ? item.imageUrl : null;
  const letters = Array.from(item.label);
  const last = letters.pop();
  return <Link feedback="card" className={css.guide} href={`/info/${item.slug}`}>
    {image && <span className={css.guideImage}><Image width={72} height={90} unoptimized alt="" src={image} referrerPolicy="no-referrer" onError={() => setFailed(image)} /></span>}
    <div><h3>{letters.join('')}<span>{last}<HomeArrow /></span></h3><p>{item.title}</p></div>
  </Link>;
}

export function WeeklyRow({ item, locale }: { item: WeeklyEntry; locale: string }) {
  const [failed,setFailed] = useState<string | null>(null);
  const image = item.imageUrl && failed !== item.imageUrl ? item.imageUrl : null;
  const href = `/info/${item.slug}`;
  return <article className={css.weekRow} data-source-card data-image={Boolean(image)}>
    <div className={css.date}><b>{item.date}</b>{item.dayLabel && <small>{item.dayLabel}</small>}</div>
    <h3><Link feedback="card" href={href}>{item.title}</Link></h3>
    {item.details && <p className={css.times}>{item.details}</p>}
    {item.summary && <p className={css.description}>{item.summary}</p>}
    {image && <PublicPosterLink src={image} href={href} title={item.title} locale={locale} navigateOnClick
      className={css.poster} imageClassName={css.posterImage} onFailure={() => setFailed(image)} />}
  </article>;
}
