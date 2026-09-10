"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";

type NoticeCopy = {
  title: string;
  purposeLabel: string;
  purposes: readonly string[];
  itemsLabel: string;
  items: readonly string[];
  retentionLabel: string;
  retention: readonly string[];
  refusalLabel: string;
  refusal: readonly string[];
};

type SummaryItem = {
  label: string;
  text: string;
};

function NoticeSection({
  title,
  items,
}: {
  title: string;
  items: readonly string[];
}) {
  return (
    <section className="min-w-0">
      <h4 className="text-sm font-bold text-ink">{title}</h4>
      <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm leading-6 text-ink-sub">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function asSummaryList(value: unknown): readonly SummaryItem[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is SummaryItem => {
    if (item === null || typeof item !== "object") return false;
    const candidate = item as Partial<SummaryItem>;
    return typeof candidate.label === "string" && typeof candidate.text === "string";
  });
}

export default function FeedbackPrivacyNotice({
  legendId,
  copy,
  consentInvalid = false,
  children,
}: {
  legendId: string;
  copy: NoticeCopy;
  consentInvalid?: boolean;
  children: ReactNode;
}) {
  const t = useTranslations("Feedback");
  const summary = asSummaryList(t.raw("requiredNotice.summary"));

  return (
    <div className="overflow-hidden rounded-[1.25rem] border border-stone bg-canvas-white shadow-premium-sm">
      <h3
        id={legendId}
        className="px-4 pt-5 text-base font-bold tracking-[-0.02em] text-ink md:px-6 md:pt-6 md:text-lg"
      >
        {copy.title}
      </h3>
      <div className="mt-4 px-4 pb-5 md:hidden">
        <ul className="space-y-2 text-sm leading-6" aria-labelledby={legendId}>
          {summary.map((item) => (
            <li key={item.label}>
              <span className="font-bold text-ink">{item.label}</span>
              <span className="text-ink-sub"> · {item.text}</span>
            </li>
          ))}
        </ul>
        <Link
          href="/privacy"
          target="_blank"
          rel="noopener noreferrer"
          className="mt-4 inline-flex min-h-11 items-center text-sm font-semibold underline underline-offset-2"
        >
          {t("requiredNotice.fullNoticeLink")}
          <span className="sr-only"> {t("requiredNotice.fullNoticeNewWindow")}</span>
        </Link>
      </div>
      <div className="relative hidden md:block">
        <div
          className="mt-4 space-y-5 px-4 pb-5 md:max-h-[18rem] md:overflow-y-auto md:overscroll-contain md:px-6 md:pb-10 md:pr-5 focus:outline-none focus-visible:outline-3 focus-visible:outline-offset-[-3px] focus-visible:outline-focus"
          tabIndex={0}
          role="region"
          aria-labelledby={legendId}
        >
          <NoticeSection title={copy.purposeLabel} items={copy.purposes} />
          <NoticeSection title={copy.itemsLabel} items={copy.items} />
          <NoticeSection title={copy.retentionLabel} items={copy.retention} />
          <NoticeSection title={copy.refusalLabel} items={copy.refusal} />
        </div>
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 bottom-0 hidden h-12 bg-gradient-to-t from-canvas-white to-transparent md:block"
        />
      </div>
      <div
        className={`border-t px-4 py-4 md:px-6 ${
          consentInvalid
            ? "border-coral bg-coral/5"
            : "border-stone bg-mineral/70"
        }`}
      >
        {children}
      </div>
    </div>
  );
}
