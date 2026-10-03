"use client";

import Image from "next/image";
import { X } from "lucide-react";
import { useEffect, useId, useRef, useState, type PointerEvent } from "react";
import { createPortal } from "react-dom";
import styles from "./SourceImageLayout.module.css";

export default function SourceImageDialog({ src, title, locale, trigger }: {
  src: string; title: string; locale: string;
  trigger: React.RefObject<HTMLButtonElement | null>;
}) {
  const id = useId(), dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const owner = useRef<string | null>(null);
  const closing = useRef(false);
  const scrollArea = useRef<HTMLDivElement>(null);
  const gesture = useRef({ pointers: new Set<number>(), x: 0, y: 0, scroll: 0, blocked: false, clickAllowed: false });
  const marker = `source-image:${id}`;
  const japanese = locale === "ja";

  useEffect(() => {
    const button = trigger.current;
    if (!button) return;
    const show = () => {
      closing.current = false;
      // A Back/Esc dismissal can unmount the image before its pointer release.
      gesture.current.pointers.clear();
      gesture.current.blocked = false;
      gesture.current.clickAllowed = false;
      owner.current = location.pathname;
      if (history.state?.machimoaImage !== marker) {
        // Keep Next and save-resume state intact; no route or query change.
        history.pushState({ ...history.state, machimoaImage: marker }, "", location.href);
      }
      setOpen(true);
    };
    const pop = (event: PopStateEvent) => {
      closing.current = false;
      setOpen(event.state?.machimoaImage === marker && location.pathname === owner.current);
    };
    button.addEventListener("click", show);
    window.addEventListener("popstate", pop);
    return () => {
      button.removeEventListener("click", show);
      window.removeEventListener("popstate", pop);
      if (history.state?.machimoaImage === marker && location.pathname === owner.current) {
        const state = { ...history.state }; delete state.machimoaImage;
        history.replaceState(state, "", location.href);
      }
    };
  }, [marker, trigger]);

  useEffect(() => {
    if (!open || !dialog.current) return;
    const element = dialog.current, origin = trigger.current, position = { x: scrollX, y: scrollY };
    const previous = { overflow: document.body.style.overflow, padding: document.body.style.paddingRight };
    const scrollbar = innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = "hidden";
    if (scrollbar) document.body.style.paddingRight = `${scrollbar}px`;
    element.showModal();
    element.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });
    return () => {
      element.close();
      document.body.style.overflow = previous.overflow;
      document.body.style.paddingRight = previous.padding;
      origin?.focus({ preventScroll: true });
      window.scrollTo(position.x, position.y);
    };
  }, [open, trigger]);

  function close() {
    if (closing.current) return;
    if (history.state?.machimoaImage === marker) { closing.current = true; history.back(); }
    else setOpen(false);
  }

  function beginGesture(event: PointerEvent<HTMLButtonElement>) {
    const current = gesture.current;
    if (current.pointers.size === 0) {
      current.x = event.clientX;
      current.y = event.clientY;
      current.scroll = scrollArea.current?.scrollTop ?? 0;
      current.blocked = event.button !== 0;
      current.clickAllowed = false;
    }
    current.pointers.add(event.pointerId);
    if (current.pointers.size > 1) current.blocked = true;
    // Capture a release outside the image without preventing native scrolling/pinch.
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveGesture(event: PointerEvent<HTMLButtonElement>) {
    const current = gesture.current;
    if (current.pointers.has(event.pointerId) && Math.hypot(event.clientX - current.x, event.clientY - current.y) > 8) {
      current.blocked = true;
    }
  }

  function endGesture(event: PointerEvent<HTMLButtonElement>, cancelled = false) {
    const current = gesture.current;
    if (!current.pointers.has(event.pointerId)) return;
    moveGesture(event);
    if (cancelled || (scrollArea.current?.scrollTop ?? 0) !== current.scroll) current.blocked = true;
    current.pointers.delete(event.pointerId);
    current.clickAllowed = !current.blocked && current.pointers.size === 0;
  }
  if (!open) return null;
  return createPortal(
    <dialog ref={dialog} className={styles.dialog} aria-labelledby={id} onCancel={event => { event.preventDefault(); close(); }}
      onClick={event => {
        if (event.target !== event.currentTarget) return;
        const b = event.currentTarget.getBoundingClientRect();
        if (event.clientX < b.left || event.clientX > b.right || event.clientY < b.top || event.clientY > b.bottom) close();
      }} onKeyDown={event => {
        if (event.key !== "Tab") return;
        const targets = [...event.currentTarget.querySelectorAll<HTMLElement>('button,a[href],[tabindex="0"]')];
        const index = targets.indexOf(document.activeElement as HTMLElement);
        const next = index < 0 ? (event.shiftKey ? targets.length - 1 : 0) : (index + (event.shiftKey ? -1 : 1) + targets.length) % targets.length;
        event.preventDefault(); targets[next]?.focus({ preventScroll: true });
      }}>
      <h2 id={id} className="sr-only">{japanese ? "提供元の画像を拡大" : "수집원 이미지 크게 보기"}</h2>
      <button type="button" onClick={close} className={styles.close} aria-label={japanese ? "画像の拡大表示を閉じる" : "이미지 확대 보기 닫기"}><X size={16} aria-hidden="true" /></button>
      <div ref={scrollArea} className={styles.dialogScroll} tabIndex={0}
        aria-label={japanese ? "長い画像はスクロールして確認できます" : "긴 이미지는 스크롤해서 확인할 수 있습니다"}
        onScroll={() => { gesture.current.blocked = true; gesture.current.clickAllowed = false; }}>
        <button type="button" className={styles.dismissImage} aria-label={japanese ? "画像を選択して拡大表示を閉じる" : "이미지를 선택해 확대 보기 닫기"}
          onPointerDown={beginGesture} onPointerMove={moveGesture} onPointerUp={event => endGesture(event)}
          onPointerCancel={event => endGesture(event, true)} onLostPointerCapture={event => endGesture(event, true)}
          onClick={event => {
            // Keyboard/assistive clicks are intentional; pointer clicks must be clean taps.
            if (event.detail === 0 || gesture.current.clickAllowed) close();
            gesture.current.clickAllowed = false;
          }}>
          <Image src={src} alt={`${japanese ? "提供元の画像" : "수집원 제공 이미지"}: ${title}`} width={600} height={800} unoptimized referrerPolicy="no-referrer" draggable={false} className={styles.fullImage} />
        </button>
      </div>
    </dialog>, document.body,
  );
}
