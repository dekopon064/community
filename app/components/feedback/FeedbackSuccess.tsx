"use client";

import { useEffect, useRef, useState } from "react";
import { Link } from "@/i18n/navigation";

type FeedbackSuccessProps = {
  receiptCode: string;
  title: string;
  warning: string;
  unrecoverable: string;
  copyLabel: string;
  copiedLabel: string;
  copyFailedLabel: string;
  deleteLabel: string;
  privacyLabel: string;
};

export default function FeedbackSuccess({
  receiptCode,
  title,
  warning,
  unrecoverable,
  copyLabel,
  copiedLabel,
  copyFailedLabel,
  deleteLabel,
  privacyLabel,
}: FeedbackSuccessProps) {
  const titleRef = useRef<HTMLHeadingElement>(null);
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  useEffect(() => {
    function onBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

  async function copyReceipt() {
    try {
      await navigator.clipboard.writeText(receiptCode);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("failed");
    }
  }

  const liveMessage =
    copyStatus === "copied"
      ? copiedLabel
      : copyStatus === "failed"
        ? copyFailedLabel
        : "";

  return (
    <section className="rounded-[1.5rem] border border-stone bg-canvas-white px-5 py-8 md:px-8 md:py-10">
      <h1
        ref={titleRef}
        tabIndex={-1}
        className="text-2xl font-bold tracking-[-0.035em] text-ink md:text-3xl"
      >
        {title}
      </h1>
      <p className="mt-5 text-sm font-semibold leading-7 text-coral md:text-base">
        {warning}
      </p>
      <p className="mt-3 text-sm leading-7 text-ink-sub md:text-base">{unrecoverable}</p>
      <p className="mt-6 break-all font-mono text-lg font-bold tracking-[0.04em] text-ink">
        {receiptCode}
      </p>
      <button
        type="button"
        onClick={() => {
          void copyReceipt();
        }}
        className="mt-5 inline-flex min-h-11 items-center rounded-xl bg-ink px-5 text-sm font-bold text-canvas-white"
      >
        {copyLabel}
      </button>
      <p className="mt-3 min-h-6 text-sm text-ink-sub" aria-live="polite">
        {liveMessage}
      </p>
      <div className="mt-8 flex flex-col gap-3 text-sm font-semibold">
        <Link href="/feedback/delete" className="inline-flex min-h-11 items-center underline underline-offset-2">
          {deleteLabel}
        </Link>
        <Link href="/privacy" className="inline-flex min-h-11 items-center underline underline-offset-2">
          {privacyLabel}
        </Link>
      </div>
    </section>
  );
}
