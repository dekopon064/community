"use client";

import Image from "next/image";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import CategoryIcon from "@/app/components/CategoryIcon";
import CurationPeriodText from "@/app/components/CurationPeriodText";
import { sourceImageUrl } from "@/app/lib/sourceImages";
import Link from "@/app/components/PublicNavigationLink";
import type { UserCategory } from "@/app/lib/userCategories";
import styles from "./SourceImageLayout.module.css";

export interface CurationCardProps {
  slug: string; category: UserCategory | null; categoryLabel: string | null;
  title: string; summary: string; imageUrl?: string | null; summaryLabel?: string;
  locale: string; deadlineKind: string | null; deadlineOn: string | null;
  eventStartOn: string | null; eventEndOn: string | null; todayKst: string;
}

export default function CurationCard({ slug, category, categoryLabel, title, summary, imageUrl,
  summaryLabel, locale, deadlineKind, deadlineOn, eventStartOn, eventEndOn, todayKst }: CurationCardProps) {
  const src = sourceImageUrl(imageUrl), [failed, setFailed] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ left: number; top: number; imageMaxHeight: number } | null>(null);
  const thumb = useRef<HTMLAnchorElement>(null), panel = useRef<HTMLDivElement>(null);
  const showTimer = useRef<ReturnType<typeof setTimeout> | null>(null), closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const suppressed = useRef(false), id = useId();
  const japanese = locale === "ja", href = `/info/${slug}`;
  const hasImage = !!src && src !== failed;
  function clearTimers() { if (showTimer.current) clearTimeout(showTimer.current); if (closeTimer.current) clearTimeout(closeTimer.current); }
  function show(keyboard = false) {
    if (suppressed.current || !window.matchMedia("(min-width: 768px)").matches || (!keyboard && !window.matchMedia("(hover: hover)").matches) || !thumb.current) return;
    clearTimers(); const b = thumb.current.getBoundingClientRect(), width = 280;
    const row = thumb.current.closest("[data-source-card]")?.getBoundingClientRect();
    const right = (row?.right ?? b.right) + 12;
    const left = right + width <= innerWidth - 12 ? right : b.left - width - 12 >= 12 ? b.left - width - 12 : Math.min(innerWidth - width - 12, b.right + 12);
    const headerBottom = Math.max(12, document.querySelector("header")?.getBoundingClientRect().bottom ?? 12);
    const imageMaxHeight = Math.max(40, Math.min(380, innerHeight - headerBottom - 100));
    const image = thumb.current.querySelector("img");
    const ratio = image?.naturalWidth ? image.naturalHeight / image.naturalWidth : 4 / 3;
    const height = Math.min(254 * ratio, imageMaxHeight) + 74;
    const top = Math.max(headerBottom + 12, Math.min(b.top, innerHeight - height - 12));
    setPreview({ left: Math.max(12, left), top, imageMaxHeight });
  }
  function close() { clearTimers(); setPreview(null); }
  function scheduleClose() {
    if (showTimer.current) clearTimeout(showTimer.current);
    closeTimer.current = setTimeout(() => {
      if (!thumb.current?.matches(":hover") && !panel.current?.matches(":hover") &&
        document.activeElement !== thumb.current && !panel.current?.contains(document.activeElement)) close();
    }, 180);
  }
  useEffect(() => () => clearTimers(), []);
  useEffect(() => {
    if (!preview) return;
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        suppressed.current = true;
        if (panel.current?.contains(document.activeElement)) thumb.current?.focus({ preventScroll: true });
        close();
      }
    };
    const outside = (event: PointerEvent) => { if (!panel.current?.contains(event.target as Node) && !thumb.current?.contains(event.target as Node)) close(); };
    window.addEventListener("keydown", dismiss); window.addEventListener("resize", close); window.addEventListener("scroll", close, true);
    window.addEventListener("pointerdown", outside);
    return () => { window.removeEventListener("keydown", dismiss); window.removeEventListener("resize", close); window.removeEventListener("scroll", close, true); window.removeEventListener("pointerdown", outside); };
    // Handlers read DOM/ref values; only the open/closed state needs subscription.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!preview]);

  const meta = <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1 text-sm leading-6">
    {categoryLabel && <span className="font-semibold text-primary-text">{categoryLabel}</span>}
    <CurationPeriodText category={category} deadlineKind={deadlineKind} deadlineOn={deadlineOn} eventStartOn={eventStartOn}
      eventEndOn={eventEndOn} todayKst={todayKst} locale={locale} />
  </div>;
  const text = <><h2 className="public-readable break-words text-xl font-bold leading-[1.35] tracking-[-0.025em] text-primary-text md:text-[1.45rem]">{title}</h2>
    <p className="public-readable mt-2 line-clamp-2 break-words text-sm leading-6 text-info-body md:text-[0.95rem] md:leading-7">
      {summaryLabel && <span className="sr-only">{summaryLabel}: </span>}{summary}
    </p></>;

  if (!hasImage) return <Link feedback="card" href={href} data-source-card className="group block border-b border-info-rule bg-info-surface px-4 py-5 transition-colors hover:bg-info-hover focus-visible:bg-info-hover md:px-6 md:py-6">
    <article className={`grid min-w-0 gap-x-3 ${category ? "grid-cols-[24px_minmax(0,1fr)]" : "grid-cols-1"}`}>
      <div className={category ? "col-start-2" : "col-start-1"}>{meta}</div>
      {category && <CategoryIcon category={category} size={24} className="col-start-1 row-start-2 mt-3 h-6 w-6 shrink-0" />}
      <div className={`${category ? "col-start-2" : "col-start-1"} row-start-2 min-w-0 pt-2`}>{text}</div>
    </article>
  </Link>;

  return <>
    <article data-source-card className={styles.card}>
      <div className={styles.cardGrid}>
        <Link feedback="card" href={href} ref={thumb} className={styles.thumbnail} aria-controls={preview ? id : undefined} aria-expanded={!!preview}
          aria-label={`${japanese ? "画像のある情報" : "이미지가 있는 정보"}: ${title}`}
          onMouseEnter={() => { suppressed.current = false; clearTimers(); showTimer.current = setTimeout(() => show(), 250); }}
          onMouseLeave={() => { suppressed.current = false; scheduleClose(); }}
          onFocus={() => show(true)} onBlur={() => { suppressed.current = false; scheduleClose(); }}
          onKeyDown={event => { if (event.key === "ArrowRight" && preview) { event.preventDefault(); panel.current?.querySelector("a")?.focus(); } }}
          onClick={event => {
            if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && matchMedia("(min-width: 768px) and (hover: hover)").matches) {
              event.preventDefault(); suppressed.current = false; show();
            }
          }}>
          <Image src={src} alt="" fill unoptimized referrerPolicy="no-referrer" loading="lazy" className={styles.image}
            onError={() => { close(); setFailed(src); }} />
        </Link>
        <Link feedback="card" href={href} className={styles.textLink}>{meta}<div className="pt-2">{text}</div></Link>
      </div>
    </article>
    {preview && createPortal(<div ref={panel} id={id} role="region" aria-label={japanese ? "画像の拡大プレビュー" : "이미지 확대 미리보기"}
      className={styles.preview} style={{ left: preview.left, top: preview.top }} onMouseEnter={clearTimers} onMouseLeave={scheduleClose} onFocus={clearTimers} onBlur={scheduleClose}>
      <a href={src} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">
        <Image src={src} width={600} height={800} unoptimized referrerPolicy="no-referrer" className={styles.previewImage} style={{ maxHeight: preview.imageMaxHeight }}
          alt={`${japanese ? "提供元の画像" : "수집원 제공 이미지"}: ${title}`} />
      </a>
      <p>{japanese ? "Escで閉じる · 元の画像は別のタブで開けます" : "Esc로 닫기 · 원본 이미지는 새 탭에서 볼 수 있습니다"}</p>
    </div>, document.body)}
  </>;
}
