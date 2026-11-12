"use client";

import { useEffect, useId, useRef, useState, type ComponentPropsWithoutRef } from "react";
import { useTranslations } from "next-intl";
import { ArrowLeftRight } from "lucide-react";
import styles from "./ReadableTable.module.css";

export default function ReadableTable({ children, ...props }: ComponentPropsWithoutRef<"table">) {
  const t = useTranslations("Accessibility");
  const hintId = useId();
  const viewport = useRef<HTMLDivElement>(null);
  const table = useRef<HTMLTableElement>(null);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    const area = viewport.current;
    const content = table.current;
    if (!area || !content) return;
    const measure = () => setOverflows(area.scrollWidth > area.clientWidth + 1);
    const observer = new ResizeObserver(measure);
    observer.observe(area);
    observer.observe(content);
    return () => observer.disconnect();
  }, [children]);

  return (
    <div className={styles.container}>
      {overflows && <p id={hintId} className={styles.hint}><ArrowLeftRight size={16} aria-hidden="true" />{t("tableScroll")}</p>}
      <div ref={viewport} className={styles.viewport} role={overflows ? "region" : undefined}
        aria-label={overflows ? t("tableRegion") : undefined}
        aria-describedby={overflows ? hintId : undefined} tabIndex={overflows ? 0 : undefined}>
        <table {...props} ref={table} className={styles.table}>{children}</table>
      </div>
    </div>
  );
}
