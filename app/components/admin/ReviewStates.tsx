import {Check,TriangleAlert} from "lucide-react";

export const reviewAttention = "border-l-4 border-[#b45309] bg-[#fff3c4] px-4 py-4 text-[#5c3300] [&_.text-info-muted]:text-[#5c3300]";
export const reviewOverview = "my-5 border-l-4 border-[#b45309] bg-[#fff3c4] px-4 py-4 text-[#5c3300]";
export const reviewError = "mt-4 border-l-4 border-[#b91c1c] bg-[#fee2e2] px-4 py-3 font-semibold text-[#7f1d1d]";
export const reviewDirty = "font-semibold text-[#075985] bg-[#e0f2fe] px-2 py-1";
export function ReviewStatus({needed,confirmed,changed}:{needed:boolean;confirmed:boolean;changed:boolean}) {
  return <span className="ml-2 inline-flex flex-wrap items-center gap-2 align-middle text-sm">
    {needed?<span className="inline-flex items-center gap-1 rounded bg-[#92400e] px-2 py-1 font-bold text-white"><TriangleAlert aria-hidden="true" className="size-4 shrink-0"/> 확인 필요</span>:confirmed&&!changed?<span className="inline-flex items-center gap-1 font-semibold text-[#166534] bg-[#dcfce7] px-2 py-1"><Check aria-hidden="true" className="size-4 shrink-0"/> 확인됨</span>:<span className="font-medium">현재 입력값</span>}
    {changed&&<span className={reviewDirty}>미저장 변경</span>}
  </span>;
}
