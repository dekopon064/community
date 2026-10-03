"use client";

import Image from "next/image";
import { useRef, useState } from "react";
import type { CandidateImage, CandidateImageSelection } from "@/app/lib/review/contracts";
import { sourceImageUrl } from "@/app/lib/sourceImages";
import SourceImageDialog from "../SourceImageDialog";
import { fieldClass } from "./ReviewEditors";

export function candidateImageError(value: CandidateImageSelection) {
  return value.mode === "override" && !sourceImageUrl(value.url) ? "사용 가능한 HTTPS 이미지 URL을 입력해 주세요." : "";
}

export default function CandidateImageEditor({ saved, value, onChange, disabled, error, title }: {
  saved: CandidateImage; value: CandidateImageSelection; onChange: (value: CandidateImageSelection) => void;
  disabled: boolean; error?: string; title: string;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const [overrideDraft, setOverrideDraft] = useState(saved.url ?? "");
  const invalid = candidateImageError(value) || error;
  const url = value.mode === "source" ? saved.sourceUrl : value.mode === "override" ? sourceImageUrl(value.url) : null;
  const dirty = value.mode !== saved.mode || value.url !== saved.url;
  return <fieldset disabled={disabled} className="my-6 min-w-0 border-y border-info-rule py-5">
    <legend className="px-1 font-bold">게시 이미지</legend>
    <p className="text-sm leading-6 text-info-muted">이 후보에 사용할 이미지를 선택하세요. 원문과 AI 생성 내용은 바뀌지 않습니다.</p>
    <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1">
      {([ ["source", "원문 이미지 사용"], ["override", "이미지 URL 사용"], ["none", "이미지 사용 안 함"] ] as const).map(([mode, label]) =>
        <label key={mode} className="flex min-h-11 cursor-pointer items-center gap-2 text-info-body">
          <input type="radio" name="candidate-image-mode" value={mode} checked={value.mode === mode}
            onChange={() => onChange({ mode, url: mode === "override" ? overrideDraft : null })} />{label}
        </label>)}
    </div>
    {value.mode === "override" && <div className="mt-3">
      <label htmlFor="candidate-image-url" className="font-semibold">이미지 URL</label>
      <input id="candidate-image-url" type="url" inputMode="url" autoComplete="off" maxLength={2048}
        className={fieldClass} value={value.url ?? ""} aria-invalid={Boolean(invalid)} aria-describedby="candidate-image-url-help"
        onChange={e => { setOverrideDraft(e.target.value); onChange({ mode: "override", url: e.target.value }); }} />
      <p id="candidate-image-url-help" className={`mt-2 break-words text-sm leading-6 ${invalid ? "text-info-status" : "text-info-muted"}`}>
        {invalid || "HTTPS 이미지 주소만 사용할 수 있습니다. 주소 형식과 실제 이미지 로딩은 별도로 확인합니다."}
      </p>
    </div>}
    <div className="mt-4 flex min-w-0 items-start gap-4">
      {url && failedUrl !== url && <>
        <button ref={trigger} type="button" aria-label="후보 이미지 크게 보기" disabled={disabled}
          className="relative h-32 w-24 shrink-0 rounded-lg border border-info-rule bg-info-surface focus-visible:outline-2 focus-visible:outline-offset-4">
          <Image src={url} alt={`${title} 게시 이미지 미리보기`} fill sizes="96px" unoptimized
            referrerPolicy="no-referrer" className="object-contain" onError={() => setFailedUrl(url)} />
        </button>
        <SourceImageDialog key={url} src={url} title={title} locale="ko" trigger={trigger} />
      </>}
      <div className="min-w-0 text-sm leading-6 text-info-body" aria-live="polite">
        {invalid ? <p>URL을 수정하면 미리보기를 확인할 수 있습니다.</p> : !url ?
          <p>등록된 이미지가 없습니다. 이미지 없이 게시할 수 있습니다.</p> : failedUrl === url ?
          <p>이미지를 불러오지 못했습니다.</p> : <p>이미지를 누르면 크게 볼 수 있습니다.</p>}
        <p className="mt-2 text-info-muted">{dirty ? "미저장 이미지 선택 · 수정 저장 후 게시에 반영됩니다." : "저장된 이미지 선택"}</p>
      </div>
    </div>
  </fieldset>;
}
