"use client";

import Image from "next/image";
import { ZoomIn } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { sourceImageDisplayUrl as sourceImageUrl } from "@/app/lib/sourceImages";
import SourceImageDialog from "./SourceImageDialog";
import styles from "./SourceImageLayout.module.css";

export default function CurationDetailHeading({ url, title, locale, back, category, period, save }: {
  url?: string | null; title: string; locale: string; back: ReactNode; category: ReactNode; period: ReactNode; save: ReactNode;
}) {
  const src = sourceImageUrl(url), [failed, setFailed] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const hasImage = !!src && src !== failed;
  const hasPeriod = !!period;
  return <header className={`${styles.heading} ${hasPeriod ? styles.withPeriod : ""} ${hasImage ? "" : styles.noImage}`} data-source-heading>
    <div className={styles.back}>{back}</div>
    <div className={styles.headingText}>
      <div className={styles.categoryRow}>
        <div className={styles.category}>{category}</div>
        {save && <div className={styles.saveSlot}>{save}</div>}
      </div>
      <h1 className="public-readable">{title}</h1>
    </div>
    {(hasPeriod || hasImage) && <div className={styles.lower}>
      {period && <div className={styles.period}>{period}</div>}
      {hasImage && <button type="button" ref={trigger} className={styles.headerPoster} aria-haspopup="dialog"
        aria-label={`${locale === "ja" ? "提供元の画像を拡大" : "수집원 이미지 크게 보기"}: ${title}`}>
        <Image src={src} alt="" fill unoptimized referrerPolicy="no-referrer" className={styles.image} onError={() => setFailed(src)} />
        <span className={styles.zoomCue}><ZoomIn size={16} aria-hidden="true" /></span>
      </button>}
    </div>}
    {hasImage && <SourceImageDialog src={src} title={title} locale={locale} trigger={trigger} />}
  </header>;
}
