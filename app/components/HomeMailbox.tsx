"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import MailboxIllustration from "@/app/components/mailbox/MailboxIllustration";
import styles from "@/app/components/mailbox/mailbox-widget.module.css";

function asStringList(value: unknown): readonly string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function LineBreakText({ lines }: { lines: readonly string[] }) {
  return (
    <>
      {lines.map((line, index) => (
        <span key={`${index}-${line}`}>
          {index > 0 ? <br /> : null}
          {line}
        </span>
      ))}
    </>
  );
}

export default function HomeMailbox() {
  const t = useTranslations("Mailbox");
  const [open, setOpen] = useState(false);
  const letterId = useId();
  const promptLines = asStringList(t.raw("promptLines"));
  const titleLines = asStringList(t.raw("letterTitleLines"));
  const descriptionLines = asStringList(t.raw("letterDescriptionLines"));

  return (
    <div className={styles.widget} data-open={open ? "true" : "false"}>
      <button
        type="button"
        className={styles.toggle}
        aria-expanded={open}
        aria-controls={letterId}
        aria-label={open ? t("collapseLabel") : t("expandLabel")}
        onClick={() => setOpen((current) => !current)}
      >
        <MailboxIllustration className={styles.illustration} />
        <span className={styles.prompt}>
          <LineBreakText lines={promptLines} />
        </span>
      </button>

      <div
        id={letterId}
        className={styles.reveal}
        inert={!open || undefined}
        aria-hidden={open ? undefined : true}
      >
        <div className={styles.revealInner}>
          <article className={styles.paper}>
            <h2 className={styles.title}>
              <LineBreakText lines={titleLines} />
            </h2>
            <p className={styles.description}>
              <LineBreakText lines={descriptionLines} />
            </p>
            <Link href="/feedback" className={styles.cta}>
              {t("cta")}
            </Link>
          </article>
        </div>
      </div>
    </div>
  );
}
