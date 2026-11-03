import type { ReactElement } from "react";
import { sourceLink } from "@/app/lib/review/presentation";

export function ReviewReasonList({ children }: { children: ReactElement[] }) {
  if (children.length === 0) return null;

  return (
    <section className="my-6" aria-label="이번에 확인할 사항">
      <h3 className="text-lg font-bold">이번에 확인할 사항</h3>
      <ul className="mt-3 divide-y divide-info-rule border-y border-info-rule">{children}</ul>
    </section>
  );
}

export function ReviewSourceReference({
  url,
  body,
  confirmedUrl,
  emptyBody = "저장된 본문이 없습니다.",
}: {
  url?: string | null;
  body?: string | null;
  confirmedUrl?: string | null;
  emptyBody?: string;
}) {
  const collectedLink = url ? sourceLink(url) : null;
  const officialLink = confirmedUrl ? sourceLink(confirmedUrl) : null;
  const distinctOfficialLink = officialLink !== collectedLink ? officialLink : null;
  const linkClass = "inline-flex min-h-11 items-center underline underline-offset-4";

  return (
    <div className="my-6 border-b border-info-rule pb-5">
      <details>
        <summary className="cursor-pointer py-3 font-semibold">원문 확인 · 읽기 전용</summary>
        <p className="mt-3 whitespace-pre-wrap break-words leading-7 text-info-body">{body || emptyBody}</p>
      </details>
      {(collectedLink || distinctOfficialLink) && (
        <div className="flex flex-wrap gap-x-4">
          {collectedLink && <a className={linkClass} href={collectedLink} target="_blank" rel="noopener noreferrer">수집된 원문 열기 (새 창)</a>}
          {distinctOfficialLink && <a className={linkClass} href={distinctOfficialLink} target="_blank" rel="noopener noreferrer">확인한 공식 상세 링크 (새 창)</a>}
        </div>
      )}
    </div>
  );
}
