import type { CandidateNotice } from "../../lib/review/contracts";

export function CandidateContentNotices({ notices }: { notices: CandidateNotice[] }) {
  if (!notices.length) return null;
  const groups = new Map<string, { notice: CandidateNotice; expected: Set<string>; results: Set<string> }>();
  for (const notice of notices) {
    const key = JSON.stringify([notice.language, notice.item, notice.section, notice.kind, notice.actual]);
    const group = groups.get(key) ?? { notice, expected: new Set<string>(), results: new Set<string>() };
    group.expected.add(notice.expected); group.results.add(notice.result); groups.set(key, group);
  }
  return <section aria-label="생성 내용 대조 안내" className="my-5 border-y border-info-rule py-4 text-sm leading-7 text-info-body">
    <h3 className="font-semibold text-ink">생성 내용 대조 안내</h3>
    <p className="mt-2 text-info-muted">생성 당시 입력과 현재 저장된 후보 문장을 비교해 주세요. 참고 안내이며 저장·승인·게시를 제한하지 않습니다. 자동 대조만으로 정확성을 보장할 수는 없습니다.</p>
    <ul className="mt-4 space-y-4">
      {[...groups.values()].map(({ notice, expected, results }, index) => <li key={index} className="border-b border-info-rule pb-4 last:border-0 last:pb-0 break-words">
        <h4 className="font-semibold text-ink">{notice.item} · {notice.language === "ko" ? "한국어" : notice.language === "ja" ? "일본어" : "한·일"}</h4>
        <p className="text-info-muted">{notice.section} · {notice.kind === "difference" ? "표기 차이" : notice.kind === "possible_missing" ? "누락 가능성 · 관련 표기를 찾지 못함" : "표현 비교 · 자동 판단 불가"}</p>
        <dl className="mt-2 grid gap-3 sm:grid-cols-2">
          <div><dt className="font-medium">생성 당시 입력</dt><dd className="whitespace-pre-wrap">{[...expected].join("\n")}</dd></div>
          <div><dt className="font-medium">저장된 후보 문장 · 발췌</dt><dd className="whitespace-pre-wrap">{notice.actual || "대조할 문장을 지정하지 못했습니다. 아래 후보 본문을 확인해 주세요."}</dd></div>
        </dl>
        <p className="mt-2 text-info-muted">{[...results].join("\n")}</p>
      </li>)}
    </ul>
  </section>;
}
