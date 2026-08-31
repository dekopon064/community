"use client";

import { useTranslations } from "next-intl";
import { Home, Info, type LucideIcon } from "lucide-react";
import { Link, usePathname } from "@/i18n/navigation";

type TabId = "home" | "info";

interface Tab {
  id: TabId;
  href: string;
  icon: LucideIcon;
}

const TABS: Tab[] = [
  { id: "home", href: "/", icon: Home },
  { id: "info", href: "/info", icon: Info },
];

export default function BottomNav() {
  const t = useTranslations("Nav");
  // next-intl의 usePathname은 locale 프리픽스가 제거된 경로를 반환 (예: "/info")
  const pathname = usePathname();

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 border-t border-stone/90 bg-canvas-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-sm md:hidden">
      <ul className="mx-auto flex h-[4.5rem] max-w-md items-center justify-around px-7">
        {TABS.map(({ id, href, icon: Icon }) => {
          const isActive =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <li key={id} className="flex-1">
              <Link
                href={href}
                aria-current={isActive ? "page" : undefined}
                className={`flex w-full flex-col items-center justify-center gap-1 py-2 transition-colors ${
                  isActive
                    ? "font-bold text-ink"
                    : "font-medium text-ink-sub hover:text-ink"
                }`}
              >
                <Icon
                  className="h-5 w-5"
                  strokeWidth={isActive ? 2.4 : 1.9}
                  aria-hidden="true"
                />
                <span className="text-xs tracking-tight">{t(id)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
