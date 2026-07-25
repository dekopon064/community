"use client";

import { useTranslations } from "next-intl";
import { Home, Info, MessageSquare, type LucideIcon } from "lucide-react";
import { Link, usePathname } from "@/i18n/navigation";

type TabId = "home" | "info" | "qna";

interface Tab {
  id: TabId;
  href: string;
  icon: LucideIcon;
}

const TABS: Tab[] = [
  { id: "home", href: "/", icon: Home },
  { id: "info", href: "/info", icon: Info },
  { id: "qna", href: "/qna", icon: MessageSquare },
];

export default function BottomNav() {
  const t = useTranslations("Nav");
  // next-intl의 usePathname은 locale 프리픽스가 제거된 경로를 반환 (예: "/info")
  const pathname = usePathname();

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 mx-auto max-w-md border-t border-stone bg-canvas-white">
      <ul className="flex h-16 items-center justify-around">
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
                    ? "font-black text-ink"
                    : "font-medium text-ink-sub hover:text-ink"
                }`}
              >
                <Icon
                  className="h-6 w-6"
                  strokeWidth={isActive ? 2.5 : 2}
                  aria-hidden="true"
                />
                <span className="text-xs">{t(id)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
