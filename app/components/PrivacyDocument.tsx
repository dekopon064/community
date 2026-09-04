import { Link } from "@/i18n/navigation";
import { FEEDBACK_CS_EMAIL } from "@/app/lib/feedback-privacy";
import type { PrivacyDoc } from "@/app/content/privacy/types";

type PrivacyDocumentProps = {
  document: PrivacyDoc;
  skipLabel: string;
  contactLabel: string;
  emailLabel: string;
  datesNote: string;
  feedbackLabel: string;
  deleteLabel: string;
};

export default function PrivacyDocument({
  document,
  skipLabel,
  contactLabel,
  emailLabel,
  datesNote,
  feedbackLabel,
  deleteLabel,
}: PrivacyDocumentProps) {
  return (
    <article className="mx-auto max-w-3xl break-words">
      <a
        href="#privacy-body"
        className="sr-only focus:not-sr-only focus:absolute focus:left-5 focus:top-20 focus:z-50 focus:rounded-xl focus:bg-canvas-white focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-ink"
      >
        {skipLabel}
      </a>

      <header className="max-w-3xl">
        <h1 className="text-3xl font-bold leading-[1.16] tracking-[-0.04em] text-ink md:text-4xl">
          {document.title}
        </h1>
        <p className="mt-4 text-sm font-semibold tabular-nums text-ink-sub">
          {document.version}
        </p>
        {document.intro.map((paragraph) => (
          <p key={paragraph} className="mt-5 text-base leading-7 text-ink-sub md:text-lg md:leading-8">
            {paragraph}
          </p>
        ))}
        <p className="mt-5 text-sm leading-6 text-ink-sub">{datesNote}</p>
        <p className="mt-3 text-sm leading-6 text-ink">
          <span className="font-semibold">{contactLabel}</span>
          {" · "}
          <span className="font-semibold">{emailLabel}</span>
          {": "}
          <a className="underline underline-offset-2" href={`mailto:${FEEDBACK_CS_EMAIL}`}>
            {FEEDBACK_CS_EMAIL}
          </a>
        </p>
      </header>

      <div id="privacy-body" className="mt-10 space-y-10">
        {document.sections.map((section) => (
          <section key={section.id} aria-labelledby={`privacy-${section.id}`}>
            <h2
              id={`privacy-${section.id}`}
              className="text-xl font-bold tracking-[-0.03em] text-ink md:text-2xl"
            >
              {section.title}
            </h2>
            {section.blocks.map((block, index) => {
              if (block.type === "p") {
                return (
                  <p
                    key={`${section.id}-p-${index}`}
                    className="mt-4 break-words text-sm leading-7 text-ink md:text-base md:leading-8"
                  >
                    {block.text}
                  </p>
                );
              }
              return (
                <ul
                  key={`${section.id}-ul-${index}`}
                  className="mt-4 list-disc space-y-2 break-words pl-5 text-sm leading-7 text-ink md:text-base md:leading-8"
                >
                  {block.items.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              );
            })}
          </section>
        ))}
      </div>

      <footer className="mt-12 border-t border-stone pt-6">
        <ul className="flex flex-col gap-3 text-sm font-semibold text-ink">
          <li>
            <Link href="/feedback" className="inline-flex min-h-11 items-center underline underline-offset-2">
              {feedbackLabel}
            </Link>
          </li>
          <li>
            <Link
              href="/feedback/delete"
              className="inline-flex min-h-11 items-center underline underline-offset-2"
            >
              {deleteLabel}
            </Link>
          </li>
        </ul>
      </footer>
    </article>
  );
}
