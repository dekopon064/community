import type { CandidateNotice } from "../../lib/review/contracts";

export function CandidateContentNotices({ notices }: { notices: CandidateNotice[] }) {
  if (!notices.length) return null;
  return <section aria-label="생성 내용 대조 안내" className="my-5 border-y border-info-rule py-4 text-sm leading-7 text-info-body">
    <h3 className="font-semibold text-ink">생성 내용 대조 안내</h3>
    <p className="mt-2 text-info-muted">생성 당시 입력과 저장된 후보를 대조한 참고 안내입니다. 자동 대조는 정확성을 보장하지 않으며, 안내가 남아도 저장·승인·게시 조건을 추가하지 않습니다.</p>
    <ul className="mt-4 space-y-4">
      {notices.map((notice, index) => <li key={index} className="break-words">
        <p className="font-medium">{notice.language === "ko" ? "한국어" : notice.language === "ja" ? "일본어" : "한·일"} · {notice.section} · {notice.item} · {notice.kind === "difference" ? "표기 차이" : "자동 판단 불가"}</p>
        <p>입력: {notice.expected}</p><p>{notice.result}</p>
      </li>)}
    </ul>
  </section>;
}
