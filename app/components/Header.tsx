"use client";

import { useTranslations } from "next-intl";
import LocaleSwitcher from "@/app/components/LocaleSwitcher";
import { USER_CATEGORIES } from "@/app/lib/userCategories";
import { Link, usePathname } from "@/i18n/navigation";

const ITEMS = [
  { id: "home", href: "/" },
  { id: "info", href: "/info" },
  ...USER_CATEGORIES.map((category) => ({
    id: category,
    href: `/info/category/${category}`,
  })),
] as const;

export default function Header() {
  const t = useTranslations("Header");
  const nav = useTranslations("Nav");
  const pathname = usePathname();
  const isInfoDetail = /^\/info\/[^/]+$/.test(pathname);

  return (
    <header className="sticky top-0 z-50 border-b border-stone/90 bg-canvas-white">
      <div className="mx-auto flex h-16 max-w-7xl items-center px-5 lg:h-[4.5rem] lg:px-8">
        <Link
          href="/"
          lang="en"
          className="font-brand text-[1.65rem] font-black tracking-[-0.055em] text-ink md:text-[1.8rem]"
        >
          {t("title")}
        </Link>

        <nav className="ml-8 hidden items-center gap-5 lg:flex" aria-label={nav("label")}>
          {ITEMS.map(({ id, href }) => {
            const isActive =
              pathname === href ||
              (id === "info" && isInfoDetail);
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
      <nav
        aria-label={nav("categoryLabel")}
        className="overflow-x-auto border-t border-stone/70 px-5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden lg:hidden"
      >
        <div className="flex min-w-max items-center gap-5">
          {ITEMS.slice(1).map(({ id, href }) => {
            const isActive = pathname === href || (id === "info" && isInfoDetail);
            return (
              <Link
                key={id}
                href={href}
                aria-current={isActive ? "page" : undefined}
                className={`inline-flex min-h-11 items-center border-b-2 text-sm font-semibold ${
                  isActive ? "border-focus text-ink" : "border-transparent text-ink-sub"
                }`}
              >
                {nav(id)}
              </Link>
            );
          })}
        </div>
      </nav>
    </header>
  );
}
