import { Link } from "@/i18n/navigation";

export interface CurationCardProps {
  slug: string;
  category: string;
  title: string;
  summary: string;
}

// 서버/클라이언트 무관하게 재사용 가능한 프레젠테이션 컴포넌트
export default function CurationCard({
  slug,
  category,
  title,
  summary,
}: CurationCardProps) {
  return (
    <Link
      href={`/info/${slug}`}
      className="block transition-transform hover:-translate-y-1"
    >
      <article className="rounded-2xl border border-stone bg-canvas-white p-5 shadow-premium-sm">
        <span className="mb-3 inline-block rounded-md border border-stone px-2 py-1 text-xs font-extrabold text-ink">
          {category}
        </span>
        <h3 className="mb-2 text-xl font-extrabold leading-snug tracking-tight text-ink">
          {title}
        </h3>
        <p className="text-sm leading-relaxed text-ink-sub">{summary}</p>
      </article>
    </Link>
  );
}
