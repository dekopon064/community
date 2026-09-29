import type { UserCategory } from "@/app/lib/userCategories";

const ICONS: Record<UserCategory, string> = {
  policy: "/category-icons/policy-layered-sheets.svg",
  program: "/category-icons/program-overlapping-pair.svg",
  event: "/category-icons/event-ticket.svg",
  youth_space: "/category-icons/youth-space-house-v4.svg",
  living: "/category-icons/living-b-sunrise-v3.svg",
};

export default function CategoryIcon({
  category,
  size = 24,
  className,
}: {
  category: UserCategory;
  size?: number;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block bg-ink ${className ?? ""}`}
      style={{
        ...(className ? {} : { width: size, height: size }),
        maskImage: `url(${ICONS[category]})`,
        WebkitMaskImage: `url(${ICONS[category]})`,
        maskSize: "contain",
        WebkitMaskSize: "contain",
        maskRepeat: "no-repeat",
        WebkitMaskRepeat: "no-repeat",
        maskPosition: "center",
        WebkitMaskPosition: "center",
      }}
    />
  );
}
