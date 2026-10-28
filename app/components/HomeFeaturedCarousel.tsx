"use client";

import { useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react';
import Image from 'next/image';
import { sourceImageDisplayUrl as sourceImageUrl } from '../lib/sourceImages';
import Link from './PublicNavigationLink';
import HomeContentCard, { HomeArrow } from './HomeContentCard';
import { homeWords, type HomeItem } from '../lib/homePresentation';
import { homeCardColors } from '../lib/homeCardPalette';
import styles from './HomeExperience.module.css';

const titlePrefix = /^(\([^)]*\)|（[^）]*）|\[[^\]]*\])([\s\S]+)$/;

type FeaturedSelection = { index: number; from: HomeItem | null; direction: 'next' | 'previous'; step: number };
function selectFeatured(current: FeaturedSelection, index: number, items: readonly HomeItem[], direction?: FeaturedSelection['direction']): FeaturedSelection {
  const previous = Math.min(current.index, items.length - 1);
  if (index === previous) return current;
  return { index, from: items[previous] ?? null, direction: direction ?? (index > previous ? 'next' : 'previous'), step: current.step + 1 };
}

function FeaturedPeek({ item, className, label, onSelect }: {
  item: HomeItem; className: string; label: string; onSelect: () => void;
}) {
  const [failed, setFailed] = useState<string | null>(null), src = sourceImageUrl(item.imageUrl);
  const image = src && failed !== src ? src : null;
  const colors = homeCardColors(item.tone, !!image || item.toneManual === true);
  const parts = item.title.match(titlePrefix);
  return <button className={`${styles.peek} ${className}`} onClick={onSelect} aria-label={label}
    title={item.title} data-tone={colors.tone} data-image={image ? 'true' : 'false'} style={colors.style as CSSProperties}>
    <span className={styles.peekInner} aria-hidden="true">{image &&
      <Image src={image} alt="" width={240} height={128} unoptimized draggable={false} referrerPolicy="no-referrer" onError={() => setFailed(image)} />}
      <span className={styles.peekTitle}>{parts ? <><span className={styles.peekContext}>{parts[1]}</span><span className={styles.peekMain}>{parts[2]}</span></> : <span className={styles.peekMain}>{item.title}</span>}</span></span>
  </button>;
}

export default function HomeFeaturedCarousel({ items, locale }: { items: readonly HomeItem[]; locale: string }) {
  const words = homeWords(locale), heading = useId(), overview = useId(), overviewTitle = useId();
  const [selection, setSelection] = useState<FeaturedSelection>({ index: 0, from: null, direction: 'next', step: 0 });
  const [expanded, setExpanded] = useState(false), [reducedMotion, setReducedMotion] = useState(true);
  const [rotationEnabled, setRotationEnabled] = useState(true);
  const [hovered, setHovered] = useState(false), [dragging, setDragging] = useState(false);
  const [pageVisible, setPageVisible] = useState(false), [inView, setInView] = useState(false);
  const [interaction, setInteraction] = useState(0);
  const active = items.length ? Math.min(selection.index, items.length - 1) : 0;
  const transitioning = !reducedMotion && !!selection.from && selection.from.id !== items[active]?.id && items.some(item => item.id === selection.from?.id);
  const dialog = useRef<HTMLDialogElement>(null), openButton = useRef<HTMLButtonElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const pendingFocus = useRef<'card' | 'dot' | null>(null);
  const gesture = useRef<{ id: number; x: number; y: number; axis: 'x' | 'y' | null } | null>(null);
  const suppressClick = useRef(false), scroll = useRef({ x: 0, y: 0 });
  const rotationAction = useRef<boolean | null>(null);
  const itemIds = items.map(item => item.id).join('|');
  const rotating = rotationEnabled && pageVisible && inView && !hovered && !dragging && !expanded && items.length > 1;
  useEffect(() => {
    if (items.length < 2) return;
    const visible = () => setPageVisible(document.visibilityState !== 'hidden');
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const preference = () => {
      setReducedMotion(motion.matches);
      setSelection(value => value.from ? { ...value, from: null } : value);
      if (motion.matches) setRotationEnabled(false);
    };
    visible(); preference();
    document.addEventListener('visibilitychange', visible);
    motion.addEventListener('change', preference);
    const observer = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver(entries => {
      setInView(entries.some(entry => entry.isIntersecting));
    });
    if (observer && stage.current) observer.observe(stage.current);
    else setInView(true);
    return () => { document.removeEventListener('visibilitychange', visible); motion.removeEventListener('change', preference); observer?.disconnect(); };
  }, [items.length]);
  useEffect(() => {
    if (!rotating) return;
    const timer = window.setTimeout(() => {
      setSelection(value => selectFeatured(value, (Math.min(value.index, items.length - 1) + 1) % items.length, items, 'next'));
    }, 5000);
    return () => window.clearTimeout(timer);
  }, [rotating, active, interaction, itemIds, items]);
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
  function select(index: number, direction?: FeaturedSelection['direction']) {
    setSelection(value => selectFeatured(value, index, items, direction));
    setInteraction(value => value + 1);
  }
  function move(delta: number) { if (items.length > 1) select((active + delta + items.length) % items.length, delta > 0 ? 'next' : 'previous'); }
  function toggleRotation() {
    // Pointer focus stops rotation before click. Keep the original button action
    // so clicking Pause cannot accidentally turn it back on.
    setRotationEnabled(rotationAction.current ?? !rotationEnabled);
    rotationAction.current = null; setInteraction(value => value + 1);
  }
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
    setRotationEnabled(false); select(next, event.key === 'ArrowLeft' || event.key === 'Home' ? 'previous' : 'next');
  }
  function pointerDown(event: PointerEvent<HTMLDivElement>) {
    suppressClick.current = false;
    if (items.length < 2 || !event.isPrimary || event.button !== 0) return;
    gesture.current = { id: event.pointerId, x: event.clientX, y: event.clientY, axis: null };
    setDragging(true);
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
    setDragging(false); setInteraction(value => value + 1);
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
    aria-roledescription={items.length > 1 ? words.carousel : undefined} onKeyDown={keyboard}
    onFocusCapture={() => setRotationEnabled(false)}
    onPointerEnter={event => { if (event.pointerType === 'mouse') setHovered(true); }} onPointerLeave={() => setHovered(false)}>
    <h2 id={heading}>{words.discover}</h2>
    {items.length > 1 && <div className={styles.carouselFooter}>
      <div className={styles.expandControls}>
        <button className={styles.playbackButton} data-home-rotation
          aria-label={rotationEnabled ? words.pauseRotation : words.playRotation}
          title={rotationEnabled ? words.pauseRotation : words.playRotation}
          onPointerDown={() => { rotationAction.current = !rotationEnabled; }}
          onPointerCancel={() => { rotationAction.current = null; }} onBlur={() => { rotationAction.current = null; }}
          onClick={toggleRotation}>
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d={rotationEnabled ? 'M8 5v14M16 5v14' : 'm8 5 11 7-11 7Z'} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </button>
        <span aria-hidden="true">{active + 1} / {items.length}</span>
        <button ref={openButton} onClick={() => setExpanded(true)} aria-haspopup="dialog" aria-controls={overview} aria-expanded={expanded}
          aria-label={locale === 'ja' ? `${items.length}件のピックアップをすべて見る` : `대표 콘텐츠 ${items.length}개 모두 보기`}>
          {words.expand}<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 4h6v6H4ZM14 4h6v6h-6ZM4 14h6v6H4ZM14 14h6v6h-6Z" stroke="currentColor" strokeWidth="1.5" /></svg>
        </button></div>
      <div className={styles.controls}>
        <button onClick={() => move(-1)} aria-label={words.previous}><HomeArrow back /></button>
        <div className={styles.dots} role="group" aria-label={words.positions}>{items.map((item, index) =>
          <button key={item.id} data-dot={index} aria-current={index === active ? 'true' : undefined}
            aria-label={`${index + 1}: ${item.title}`} onClick={() => select(index)}><span /></button>)}</div>
        <button onClick={() => move(1)} aria-label={words.next}><HomeArrow /></button>
      </div>
    </div>}
    <div ref={stage} className={styles.stage} data-count={Math.min(items.length, 3)}
      onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp}
      onPointerCancel={event => pointerUp(event, true)} onLostPointerCapture={() => { gesture.current = null; setDragging(false); stage.current?.style.removeProperty('--home-drag'); }}
      onDragStart={event => event.preventDefault()}
      onClickCapture={event => { if (suppressClick.current && event.detail !== 0) { event.preventDefault(); event.stopPropagation(); suppressClick.current = false; } }}>
      {items.length > 2 && <FeaturedPeek item={items[previous]} className={styles.previousPeek}
        onSelect={() => move(-1)} label={`${words.previous}: ${items[previous].title}`} />}
      <div className={styles.deck} style={{ '--home-enter-x': selection.direction === 'next' ? '16px' : '-16px' } as CSSProperties}>
        {!items.length && <div className={styles.emptyFeatured}><h3>{words.emptyTitle}</h3><p>{words.emptyBody}</p>
          <div><Link href="/info/category/program">{words.programList}<HomeArrow /></Link><Link href="/info/category/event">{words.eventList}<HomeArrow /></Link></div></div>}
        {items.map(item => <div key={item.id} className={styles.slide} data-home-measure aria-hidden="true" inert>
          <HomeContentCard item={item} locale={locale} featured />
        </div>)}
        {transitioning && selection.from && <div key={`exit-${selection.step}`} className={styles.slide} data-home-exit aria-hidden="true" inert>
          <HomeContentCard item={selection.from} locale={locale} featured />
        </div>}
        {items.length > 0 && <div key={`active-${items[active].id}`} className={styles.slide} data-home-slide={active} data-active="true"
          data-enter={transitioning ? selection.direction : undefined}
          onAnimationEnd={event => {
            if (event.target !== event.currentTarget) return;
            setSelection(value => value.step === selection.step && value.from ? { ...value, from: null } : value);
          }}>
          <HomeContentCard item={items[active]} locale={locale} featured />
        </div>}
      </div>
      {items.length > 1 && <FeaturedPeek item={items[next]} className={styles.nextPeek}
        onSelect={() => move(1)} label={`${words.next}: ${items[next].title}`} />}
    </div>
    <p className="sr-only" role="status" aria-live={rotationEnabled && items.length > 1 ? 'off' : 'polite'} aria-atomic="true">{items.length ? `${active + 1} / ${items.length} · ${items[active].title}` : words.emptyTitle}</p>
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
