import { useTranslations } from "next-intl";
import LocaleSwitcher from "@/app/components/LocaleSwitcher";

export default function Header() {
  const t = useTranslations("Header");

  return (
    <header className="sticky top-0 z-50 border-b border-stone bg-canvas-white">
      <div className="relative flex h-14 items-center justify-center">
        <h1 className="text-lg font-black tracking-tight text-ink">
          {t("title")}
        </h1>
        <LocaleSwitcher />
      </div>
    </header>
  );
}
