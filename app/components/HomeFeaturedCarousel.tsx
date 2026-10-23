"use client";

import { useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react';
import Image from 'next/image';
import { sourceImageUrl } from '../lib/sourceImages';
import Link from './PublicNavigationLink';
import HomeContentCard, { HomeArrow } from './HomeContentCard';
import { homeWords, type HomeItem } from '../lib/homePresentation';
import { homeCardColors } from '../lib/homeCardPalette';
import styles from './HomeExperience.module.css';

function FeaturedPeek({ item, className, label, onSelect }: {
  item: HomeItem; className: string; label: string; onSelect: () => void;
}) {
  const [failed, setFailed] = useState<string | null>(null), src = sourceImageUrl(item.imageUrl);
  const image = src && failed !== src ? src : null;
  const colors = homeCardColors(item.tone, !!image);
  return <button className={`${styles.peek} ${className}`} onClick={onSelect} aria-label={label}
    data-tone={colors.tone} data-image={image ? 'true' : 'false'} style={colors.style as CSSProperties}>
    <span className={styles.peekInner} aria-hidden="true">{image &&
      <Image src={image} alt="" width={240} height={128} unoptimized draggable={false} referrerPolicy="no-referrer" onError={() => setFailed(image)} />}
      <span>{item.title}</span></span>
  </button>;
}

export default function HomeFeaturedCarousel({ items, locale }: { items: readonly HomeItem[]; locale: string }) {
  const words = homeWords(locale), heading = useId(), overview = useId(), overviewTitle = useId();
  const [selected, setSelected] = useState(0), [expanded, setExpanded] = useState(false);
  const active = items.length ? Math.min(selected, items.length - 1) : 0;
  const dialog = useRef<HTMLDialogElement>(null), openButton = useRef<HTMLButtonElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const pendingFocus = useRef<'card' | 'dot' | null>(null);
  const gesture = useRef<{ id: number; x: number; y: number; axis: 'x' | 'y' | null } | null>(null);
  const suppressClick = useRef(false), scroll = useRef({ x: 0, y: 0 });
  useEffect(() => {
    const target = pendingFocus.current; pendingFocus.current = null;
    if (!target) return;
    // Let the browser finish making the old slide inert before restoring focus.
    const timer = window.setTimeout(() => {
      if (target === 'card') stage.current?.querySelector<HTMLAnchorElement>(`[data-home-slide="${active}"] a`)?.focus({ preventScroll: true });
      if (target === 'dot') stage.current?.parentElement?.querySelector<HTMLButtonElement>(`[data-dot="${active}"]`)?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [active]);
  function move(delta: number) { if (items.length > 1) setSelected((active + delta + items.length) % items.length); }
  function close() { dialog.current?.close(); setExpanded(false); }
  useEffect(() => {
    if (!expanded || !dialog.current) return;
    const modal = dialog.current;
    const opener = openButton.current;
    scroll.current = { x: window.scrollX, y: window.scrollY };
    const body = document.body;
    const previous = { overflow: body.style.overflow, position: body.style.position, top: body.style.top,
      left: body.style.left, width: body.style.width, paddingRight: body.style.paddingRight };
    const gap = window.innerWidth - document.documentElement.clientWidth;
    Object.assign(body.style, { overflow: 'hidden', position: 'fixed', top: `-${scroll.current.y}px`,
      left: `-${scroll.current.x}px`, width: '100%', paddingRight: `${gap}px` });
    modal.showModal();
    modal.querySelector<HTMLButtonElement>('button')?.focus();
    return () => {
      modal.close(); Object.assign(body.style, previous);
      window.scrollTo(scroll.current.x, scroll.current.y);
      opener?.focus({ preventScroll: true });
    };
  }, [expanded]);
  function keyboard(event: KeyboardEvent<HTMLElement>) {
    if (expanded || items.length < 2 || event.altKey || event.ctrlKey || event.metaKey) return;
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (active + (event.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length;
    const cardFocused = !!(event.target as HTMLElement).closest('[data-home-slide]');
    const dotFocused = (event.target as HTMLElement).dataset.dot !== undefined;
    pendingFocus.current = next === active ? null : cardFocused ? 'card' : dotFocused ? 'dot' : null;
    setSelected(next);
  }
  function pointerDown(event: PointerEvent<HTMLDivElement>) {
    suppressClick.current = false;
    if (items.length < 2 || !event.isPrimary || event.button !== 0) return;
    gesture.current = { id: event.pointerId, x: event.clientX, y: event.clientY, axis: null };
  }
  function pointerMove(event: PointerEvent<HTMLDivElement>) {
    const g = gesture.current; if (!g || g.id !== event.pointerId) return;
    const dx = event.clientX - g.x, dy = event.clientY - g.y;
    if (!g.axis && Math.max(Math.abs(dx), Math.abs(dy)) >= 10) g.axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
    if (g.axis === 'x') {
      suppressClick.current = true;
      event.currentTarget.setPointerCapture(event.pointerId);
      event.currentTarget.style.setProperty('--home-drag', `${Math.max(-48, Math.min(48, dx * .25))}px`);
    }
  }
  function pointerUp(event: PointerEvent<HTMLDivElement>, cancelled = false) {
    const g = gesture.current; gesture.current = null;
    event.currentTarget.style.removeProperty('--home-drag');
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (!cancelled && g?.axis === 'x' && Math.abs(event.clientX - g.x) >= 48) move(event.clientX < g.x ? 1 : -1);
  }
  function trapFocus(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key !== 'Tab') return;
    const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),a[href]')).filter(e => e.getClientRects().length);
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
  const previous = items.length ? (active + items.length - 1) % items.length : 0, next = items.length ? (active + 1) % items.length : 0;
  return <section className={styles.featured} aria-labelledby={heading}
    aria-roledescription={items.length > 1 ? words.carousel : undefined} onKeyDown={keyboard}>
    <h2 id={heading}>{words.discover}</h2>
    <div ref={stage} className={styles.stage} data-count={Math.min(items.length, 3)}
      onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp}
      onPointerCancel={event => pointerUp(event, true)} onLostPointerCapture={() => { gesture.current = null; stage.current?.style.removeProperty('--home-drag'); }}
      onDragStart={event => event.preventDefault()}
      onClickCapture={event => { if (suppressClick.current && event.detail !== 0) { event.preventDefault(); event.stopPropagation(); suppressClick.current = false; } }}>
      {items.length > 2 && <FeaturedPeek item={items[previous]} className={styles.previousPeek}
        onSelect={() => move(-1)} label={`${words.previous}: ${items[previous].title}`} />}
      <div className={styles.deck}>
        {!items.length && <div className={styles.emptyFeatured}><h3>{words.emptyTitle}</h3><p>{words.emptyBody}</p>
          <div><Link href="/info/category/program">{words.programList}<HomeArrow /></Link><Link href="/info/category/event">{words.eventList}<HomeArrow /></Link></div></div>}
        {items.map(item => <div key={item.id} className={styles.slide} data-home-measure aria-hidden="true" inert>
          <HomeContentCard item={item} locale={locale} featured />
        </div>)}
        {items.length > 0 && <div className={styles.slide} data-home-slide={active} data-active="true">
          <HomeContentCard item={items[active]} locale={locale} featured />
        </div>}
      </div>
      {items.length > 1 && <FeaturedPeek item={items[next]} className={styles.nextPeek}
        onSelect={() => move(1)} label={`${words.next}: ${items[next].title}`} />}
    </div>
    {items.length > 1 && <div className={styles.carouselFooter}>
      <div className={styles.controls}>
        <button onClick={() => move(-1)} aria-label={words.previous}><HomeArrow back /></button>
        <div className={styles.dots} role="group" aria-label={words.positions}>{items.map((item, index) =>
          <button key={item.id} data-dot={index} aria-current={index === active ? 'true' : undefined}
            aria-label={`${index + 1}: ${item.title}`} onClick={() => setSelected(index)}><span /></button>)}</div>
        <button onClick={() => move(1)} aria-label={words.next}><HomeArrow /></button>
      </div>
      <div className={styles.expandControls}><span aria-hidden="true">{active + 1} / {items.length}</span>
        <button ref={openButton} onClick={() => setExpanded(true)} aria-haspopup="dialog" aria-controls={overview} aria-expanded={expanded}
          aria-label={locale === 'ja' ? `${items.length}件のピックアップをすべて見る` : `대표 콘텐츠 ${items.length}개 모두 보기`}>
          {words.expand}<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 4h6v6H4ZM14 4h6v6h-6ZM4 14h6v6H4ZM14 14h6v6h-6Z" stroke="currentColor" strokeWidth="1.5" /></svg>
        </button></div>
    </div>}
    <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">{items.length ? `${active + 1} / ${items.length} · ${items[active].title}` : words.emptyTitle}</p>
    <dialog ref={dialog} id={overview} className={styles.overview} aria-labelledby={overviewTitle}
      onCancel={() => setExpanded(false)} onClose={() => setExpanded(false)} onKeyDown={trapFocus}
      onClick={event => { if (event.target === event.currentTarget) { const b = event.currentTarget.getBoundingClientRect(); if (event.clientX < b.left || event.clientX > b.right || event.clientY < b.top || event.clientY > b.bottom) close(); } }}>
      <div className={styles.overviewHeader}><h2 id={overviewTitle}>{words.featured} {items.length}{locale === 'ja' ? '件' : '개'}</h2>
        <button onClick={close} aria-label={words.close}><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" stroke="currentColor" strokeWidth="1.8" /></svg></button></div>
      <div className={styles.overviewBody}>{items.map(item => <HomeContentCard key={item.id} item={item} locale={locale} />)}</div>
      <div className={styles.overviewBottom}><Link href="/info/category/program">{words.allPrograms}<HomeArrow /></Link></div>
    </dialog>
  </section>;
}
