"use client";

import Image from "next/image";
import { ZoomIn } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { sourceImageUrl } from "@/app/lib/sourceImages";
import SourceImageDialog from "./SourceImageDialog";
import styles from "./SourceImageLayout.module.css";

export default function CurationDetailHeading({ url, title, locale, category, period, save }: {
  url?: string | null; title: string; locale: string; category: ReactNode; period: ReactNode; save: ReactNode;
}) {
  const src = sourceImageUrl(url), [failed, setFailed] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null), trigger = useRef<HTMLButtonElement>(null);
  const [multiline, setMultiline] = useState(false);
  const hasImage = !!src && src !== failed;
  const hasMeta = !!period || !!save;
  useEffect(() => {
    const element = heading.current; if (!element) return;
    const observe = () => {
      const lineHeight = parseFloat(getComputedStyle(element).lineHeight);
      setMultiline(element.getBoundingClientRect().height > lineHeight * 1.5);
    };
    const observer = new ResizeObserver(observe);
    observer.observe(element); observe();
    return () => observer.disconnect();
  }, [title]);
  return <header className={`${styles.heading} ${multiline ? styles.multiline : ""} ${hasImage ? "" : styles.noImage}`} data-source-heading>
    <div className={styles.headingText}>
      <div className={styles.category}>{category}</div>
      <h1 ref={heading} className="public-readable">{title}</h1>
    </div>
    {(hasMeta || hasImage) && <div className={`${styles.lower} ${hasMeta ? "" : styles.imageOnly}`}>
      {hasMeta && <div className={styles.meta}>
        {period && <div className={styles.period}>{period}</div>}
        {save && <div className={styles.saveSlot}>{save}</div>}
      </div>}
      {hasImage && <button type="button" ref={trigger} className={styles.headerPoster} aria-haspopup="dialog"
        aria-label={`${locale === "ja" ? "提供元の画像を拡大" : "수집원 이미지 크게 보기"}: ${title}`}>
        <Image src={src} alt="" fill unoptimized referrerPolicy="no-referrer" className={styles.image} onError={() => setFailed(src)} />
        <span className={styles.zoomCue}><ZoomIn size={16} aria-hidden="true" /></span>
      </button>}
    </div>}
    {hasImage && <SourceImageDialog src={src} title={title} locale={locale} trigger={trigger} />}
  </header>;
}
