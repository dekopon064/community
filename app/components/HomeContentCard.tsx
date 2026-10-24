"use client";

import Image from 'next/image';
import { useState, type CSSProperties } from 'react';
import Link from './PublicNavigationLink';
import { sourceImageUrl } from '../lib/sourceImages';
import { homeWords, type HomeItem } from '../lib/homePresentation';
import { homeCardColors } from '../lib/homeCardPalette';
import styles from './HomeExperience.module.css';

export default function HomeContentCard({ item, locale, featured = false }: { item: HomeItem; locale: string; featured?: boolean }) {
  const [failed, setFailed] = useState<string | null>(null);
  const src = sourceImageUrl(item.imageUrl);
  const image = src && failed !== src ? src : null;
  const colors = homeCardColors(item.tone, !!image || item.toneManual === true);
  const words = homeWords(locale);
  const parts = item.title.match(/^(\([^)]*\)|（[^）]*）|\[[^\]]*\])([\s\S]+)$/);
  return <Link feedback="card" href={`/info/${item.slug}`} className={`${styles.contentCard} ${featured ? styles.featuredCard : styles.listCard}`}
    data-image={image ? 'true' : 'false'} data-tone={featured ? colors.tone : undefined}
    style={featured ? colors.style as CSSProperties : undefined} draggable={false}>
    <article className={styles.cardGrid}>
      <h3>{parts ? <><span className={styles.titleContext}>{parts[1]}</span><span>{parts[2]}</span></> : item.title}</h3>
      {image && <div className={styles.poster}><Image src={image} alt="" width={280} height={320} unoptimized
        draggable={false} referrerPolicy="no-referrer" onError={() => setFailed(image)} /></div>}
      <p className={styles.summary}>{item.summary}</p>
      <p className={styles.meta}><span>{item.categoryLabel}</span>{item.period && <span className={styles.period}>{item.period}</span>}</p>
      <span className={styles.detail}>{words.detail}<HomeArrow /></span>
    </article>
  </Link>;
}

export function HomeArrow({ back = false }: { back?: boolean }) {
  return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" className={back ? styles.backArrow : undefined}>
    <path d="M4 12h15m-6-6 6 6-6 6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>;
}
