"use client";

import Image from "next/image";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from './PublicNavigationLink';
import styles from './SourceImageLayout.module.css';

export default function PublicPosterLink({ src, href, title, locale, className, imageClassName, onFailure, navigateOnClick = false }: {
  src: string; href: string; title: string; locale: string; className: string; imageClassName: string;
  onFailure: () => void; navigateOnClick?: boolean;
}) {
  const [preview, setPreview] = useState<{ left: number; top: number; imageMaxHeight: number } | null>(null);
  const thumb = useRef<HTMLAnchorElement>(null), panel = useRef<HTMLDivElement>(null);
  const showTimer = useRef<ReturnType<typeof setTimeout> | null>(null), closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const suppressed = useRef(false), id = useId();
  const japanese = locale === "ja";
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

  return <>
        <Link feedback="card" href={href} ref={thumb} data-list-poster className={className} aria-controls={preview ? id : undefined} aria-expanded={!!preview}
          aria-label={`${japanese ? "画像のある情報" : "이미지가 있는 정보"}: ${title}`}
          onMouseEnter={() => { suppressed.current = false; clearTimers(); showTimer.current = setTimeout(() => show(), 250); }}
          onMouseLeave={() => { suppressed.current = false; scheduleClose(); }}
          onFocus={() => show(true)} onBlur={() => { suppressed.current = false; scheduleClose(); }}
          onKeyDown={event => { if (event.key === "ArrowRight" && preview) { event.preventDefault(); panel.current?.querySelector("a")?.focus(); } }}
          onClick={event => {
            if (!navigateOnClick && event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && matchMedia("(min-width: 768px) and (hover: hover)").matches) {
              event.preventDefault(); suppressed.current = false; show();
            }
          }}>
          <Image src={src} alt="" fill unoptimized referrerPolicy="no-referrer" loading="lazy" className={imageClassName}
            onError={() => { close(); onFailure(); }} />
        </Link>
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
