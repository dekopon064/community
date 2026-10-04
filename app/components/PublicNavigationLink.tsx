"use client";

import { forwardRef, type ComponentProps } from "react";
import { useLinkStatus } from "next/link";
import { useLocale } from "next-intl";
import { Link } from "@/i18n/navigation";
import styles from "./PublicNavigationFeedback.module.css";

function NavigationHint() {
  const { pending } = useLinkStatus();
  const locale = useLocale();
  return <span className={styles.hint} data-pending={pending} role="status">
    {locale === "ja" ? "移動中" : "이동 중"}
  </span>;
}

type Props = ComponentProps<typeof Link> & { feedback?: "inline" | "card" | "navigation" };

// Keep next-intl/Next Link's prefetch, interception and browser navigation intact.
const PublicNavigationLink = forwardRef<HTMLAnchorElement, Props>(function PublicNavigationLink(
  { children, className, feedback = "inline", ...props }, ref,
) {
  return <Link {...props} ref={ref} className={`${className ?? ""} ${styles.link}`} data-navigation-feedback={feedback}>
    {children}<NavigationHint />
  </Link>;
});

export default PublicNavigationLink;
