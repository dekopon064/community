"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useLayoutEffect, useSyncExternalStore } from "react";
import { useLocale, useTranslations } from "next-intl";
import { usePathname } from "@/i18n/navigation";

type Theme = "light" | "dark";

function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function subscribeTheme(onStoreChange: () => void) {
  const observer = new MutationObserver(onStoreChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}

function updateBrowserThemeColor(theme: Theme) {
  document.querySelector('meta[name="theme-color"]')?.setAttribute(
    "content",
    theme === "dark" ? "#171717" : "#eef6fb",
  );
}

export default function ThemeToggle() {
  const t = useTranslations("ThemeToggle");
  const locale = useLocale();
  const pathname = usePathname();
  const theme = useSyncExternalStore<Theme>(subscribeTheme, currentTheme, () => "light");

  useLayoutEffect(() => {
    let saved: Theme = "light";
    try {
      if (localStorage.getItem("machimoa-theme") === "dark") saved = "dark";
    } catch {
      // An unavailable store always falls back to light.
    }
    document.documentElement.dataset.theme = saved;
    updateBrowserThemeColor(saved);
  }, [locale]);

  useEffect(() => {
    updateBrowserThemeColor(theme);
  }, [theme, pathname]);

  function toggleTheme() {
    const next: Theme = currentTheme() === "dark" ? "light" : "dark";
    try {
      localStorage.setItem("machimoa-theme", next);
      document.documentElement.dataset.theme = next;
    } catch {
      document.documentElement.dataset.theme = "light";
    }
  }

  return (
    <button
      type="button"
      onClick={toggleTheme}
      className="theme-toggle grid h-11 w-11 shrink-0 place-items-center rounded-full bg-transparent text-ink transition-colors focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-focus"
      aria-label={theme === "light" ? t("lightToDark") : t("darkToLight")}
      title={theme === "light" ? t("lightToDark") : t("darkToLight")}
    >
      <Sun className="theme-sun h-5 w-5" strokeWidth={1.9} aria-hidden="true" />
      <Moon className="theme-moon h-5 w-5" strokeWidth={1.9} aria-hidden="true" />
    </button>
  );
}
