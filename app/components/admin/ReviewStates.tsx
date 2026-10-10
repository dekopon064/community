import {Check,TriangleAlert} from "lucide-react";
import type {ReactNode} from 'react';

export const reviewAttention = "border-l-4 border-[#b45309] bg-[#fff3c4] px-4 py-4 text-[#5c3300] [&_.text-info-muted]:text-[#5c3300]";
export const reviewOverview = "my-5 border-l-4 border-[#b45309] bg-[#fff3c4] px-4 py-4 text-[#5c3300]";
export const reviewError = "mt-4 border-l-4 border-[#b91c1c] bg-[#fee2e2] px-4 py-3 font-semibold text-[#7f1d1d]";
export const reviewDirty = "font-semibold text-[#075985] bg-[#e0f2fe] px-2 py-1";
export function ReviewStatus({needed,confirmed,changed}:{needed:boolean;confirmed:boolean;changed:boolean}) {
  return <span className="ml-2 inline-flex flex-wrap items-center gap-2 align-middle text-sm">
    {needed?<span className="inline-flex items-center gap-1 rounded bg-[#92400e] px-2 py-1 font-bold text-white"><TriangleAlert aria-hidden="true" className="size-4 shrink-0"/> 확인 필요</span>:confirmed&&!changed?<span className="inline-flex items-center gap-1 font-semibold text-[#166534] bg-[#dcfce7] px-2 py-1"><Check aria-hidden="true" className="size-4 shrink-0"/> 확인됨</span>:null}
    {changed&&<span className={reviewDirty}>미저장 변경</span>}
  </span>;
}

export function ReviewValueRow({label,value,origin,changedValue,status,action,children}:{label:string;value:string;origin?:string;changedValue?:string;status:ReactNode;action:ReactNode;children?:ReactNode}) {
  return <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-2 border-t border-info-rule py-4 sm:grid-cols-[10rem_minmax(0,1fr)_10rem_auto] sm:gap-x-4">
    <dt className="break-keep font-semibold sm:col-start-1">{label}</dt>
    <dd className="col-start-1 row-start-2 min-w-0 whitespace-pre-wrap break-words leading-6 sm:col-start-2 sm:row-start-1">{origin&&<span className="mb-1 block text-sm text-info-muted">{origin}</span>}{value}{changedValue!==undefined&&<p className="mt-2 font-semibold">변경할 값 → {changedValue}</p>}</dd>
    {status&&<dd className="col-start-1 row-start-3 min-w-0 sm:col-start-3 sm:row-start-1">{status}</dd>}
    <dd className="col-start-2 row-span-2 row-start-1 sm:col-start-4 sm:row-span-1">{action}</dd>
    {children&&<dd className="col-span-2 mt-2 min-w-0 sm:col-span-4">{children}</dd>}
  </div>;
}
