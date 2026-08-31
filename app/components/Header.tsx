"use client";

import { useTranslations } from "next-intl";
import LocaleSwitcher from "@/app/components/LocaleSwitcher";
import { Link, usePathname } from "@/i18n/navigation";

export default function Header() {
  const t = useTranslations("Header");
  const nav = useTranslations("Nav");
  const pathname = usePathname();

  const items = [
    { id: "home", href: "/" },
    { id: "info", href: "/info" },
  ] as const;

  return (
    <header className="sticky top-0 z-50 border-b border-stone/90 bg-canvas-white/95 backdrop-blur-sm">
      <div className="mx-auto flex h-16 max-w-7xl items-center px-5 md:h-[4.5rem] md:px-8">
        <Link
          href="/"
          className="text-[1.65rem] font-black tracking-[-0.055em] text-ink md:text-[1.8rem]"
        >
          {t("title")}
        </Link>

        <nav className="ml-14 hidden items-center gap-8 md:flex" aria-label={nav("label")}>
          {items.map(({ id, href }) => {
            const isActive = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={id}
                href={href}
                aria-current={isActive ? "page" : undefined}
                className={`relative inline-flex min-h-11 items-center py-2 text-sm font-semibold transition-colors after:absolute after:bottom-0 after:left-0 after:h-0.5 after:rounded-full after:bg-focus after:transition-transform ${
                  isActive
                    ? "text-ink after:w-full"
                    : "text-ink-sub after:w-full after:scale-x-0 hover:text-ink hover:after:scale-x-100"
                }`}
              >
                {nav(id)}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto">
          <LocaleSwitcher />
        </div>
      </div>
    </header>
  );
}
