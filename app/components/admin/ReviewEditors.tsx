"use client";

import type { ReactNode } from "react";
import type { Facts, CandidateContent } from "@/app/lib/review/contracts";
import { categories } from "@/app/lib/review/presentation";

export const fieldClass = "mt-2 block min-h-11 w-full rounded-lg border border-info-rule bg-info-surface px-3 py-2 text-base text-primary-text disabled:opacity-60";
export const primaryButton = "inline-flex min-h-12 items-center justify-center rounded-xl bg-ink px-5 py-3 font-semibold text-canvas-white hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-45";
export const secondaryButton = "inline-flex min-h-12 items-center justify-center rounded-xl border border-info-rule px-5 py-3 font-semibold text-ink hover:bg-info-surface disabled:cursor-not-allowed disabled:opacity-45";

function Field({ name, label, help, error, children }: { name: string; label: string; help?: string; error?: string; children: ReactNode }) {
  return <div>
    <label htmlFor={name} className="block font-semibold text-primary-text">{label}</label>
    {help && <p id={`${name}-help`} className="mt-1 text-sm leading-6 text-info-muted">{help}</p>}
    {children}
    {error && <p id={`${name}-error`} className="mt-2 text-sm text-info-status">{error}</p>}
  </div>;
}
export function FactsEditor({ value, onChange, errors, disabled, editableFields }: { value: Facts; onChange: (value: Facts) => void; errors: Record<string, string>; disabled: boolean; editableFields?: (keyof Facts)[] }) {
  function set(key: keyof Facts, next: string | string[]) { onChange({ ...value, [key]: next }); }
  const blocked = (name: keyof Facts) => disabled || Boolean(editableFields && !editableFields.includes(name));
  const attrs = (name: keyof Facts) => ({ id: name, className: fieldClass, disabled: blocked(name), "aria-invalid": Boolean(errors[name]), "aria-describedby": `${name}-help ${errors[name] ? `${name}-error` : ""}`.trim() });
  const regional = value.productType !== "living_guide";
  const deadline = value.category === "policy" || value.category === "program";
  return <div className="space-y-8">
    {editableFields && <p className="text-sm leading-6 text-info-muted">현재 열린 확인 사유에 필요한 항목만 입력할 수 있습니다. 이미 확정된 값은 읽기 전용입니다. 정보 성격·카테고리를 저장한 뒤 추가 입력 항목이 열릴 수 있습니다. 지원하지 않는 사유는 별도 확인이 필요합니다.</p>}
    <div className="grid gap-6 sm:grid-cols-2">
      <Field name="productType" label="정보 성격" help="공개 카테고리와 구분되는 검토용 분류입니다." error={errors.productType}>
        <select {...attrs("productType")} value={value.productType} onChange={(e) => set("productType", e.target.value)}>
          <option value="">확인 필요</option><option value="event_program">행사·프로그램</option><option value="policy_reference">정책 참고자료</option><option value="living_guide">생활 안내</option>
        </select>
      </Field>
      <Field name="category" label="공개 카테고리" help="독자가 공개 사이트에서 찾을 분류입니다." error={errors.category}>
        <select {...attrs("category")} value={value.category} onChange={(e) => onChange({ ...value, category: e.target.value as Facts["category"], ...(editableFields ? {} : { deadlineKind: "", deadlineOn: "" }), eventStart: "", eventEnd: "" })}>
          <option value="">확인 필요</option>{Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
      </Field>
    </div>
    {regional && <>
      <Field name="scope" label="신청·이용 대상 지역" help="개최 장소가 아니라 누가 신청하거나 이용할 수 있는지 확인하세요." error={errors.scope}>
        <select {...attrs("scope")} value={value.scope} onChange={(e) => onChange({ ...value, scope: e.target.value as Facts["scope"], regions: [] })}>
          <option value="unknown">확인 필요</option><option value="nationwide">전국</option><option value="specific">특정 지역</option>
        </select>
      </Field>
      {value.scope === "specific" && <fieldset aria-describedby={errors.regions ? "regions-error" : undefined}>
        <legend className="font-semibold">대상 지역 선택</legend>
        <div className="mt-2 grid grid-cols-2 gap-x-4 sm:grid-cols-3">
          {Object.entries({ "11": "서울", "28": "인천", "41": "경기", "26": "부산", "27": "대구", "29": "광주", "30": "대전", "31": "울산", "36": "세종", "42": "강원", "43": "충북", "44": "충남", "45": "전북", "46": "전남", "47": "경북", "48": "경남", "50": "제주" }).map(([code, label]) =>
            <label key={code} className="flex min-h-11 cursor-pointer items-center gap-3 text-info-body"><input type="checkbox" disabled={blocked("regions")} className="size-5 accent-ink" checked={value.regions.includes(code)} onChange={(e) => set("regions", e.target.checked ? [...value.regions, code] : value.regions.filter((r) => r !== code))} />{label}</label>)}
        </div>{errors.regions && <p id="regions-error" className="text-sm text-info-status">{errors.regions}</p>}
      </fieldset>}
      <Field name="evidence" label="대상 지역의 원문 근거" help="공식 원문의 신청 자격 문구를 입력해 주세요. 최대 500자입니다." error={errors.evidence}>
        <textarea {...attrs("evidence")} rows={3} maxLength={500} value={value.evidence} onChange={(e) => set("evidence", e.target.value)} />
      </Field>
    </>}
    {value.productType === "policy_reference" && <Field name="foreignEligibility" label="외국인 거주자의 신청 자격" help="원문이 불명확하면 추측하지 말고 확인 필요로 남겨 주세요." error={errors.foreignEligibility}>
      <select {...attrs("foreignEligibility")} value={value.foreignEligibility} onChange={(e) => set("foreignEligibility", e.target.value)}><option value="unknown">확인 필요</option><option value="eligible">신청 가능</option><option value="ineligible">신청 불가</option></select>
    </Field>}
    <Field name="delivery" label="진행 방식" help="온라인이라는 이유만으로 이용 대상 지역을 전국으로 판단하지 않습니다." error={errors.delivery}>
      <select {...attrs("delivery")} value={value.delivery} onChange={(e) => set("delivery", e.target.value)}><option value="unknown">확인 필요</option><option value="online">온라인</option><option value="offline">오프라인</option><option value="hybrid">온·오프라인 병행</option></select>
    </Field>
    {deadline && <div className="grid gap-6 sm:grid-cols-2">
      <Field name="deadlineKind" label="신청 마감" help="행사 개최일과 구분해 주세요." error={errors.deadlineKind}>
        <select {...attrs("deadlineKind")} value={value.deadlineKind} onChange={(e) => onChange({ ...value, deadlineKind: e.target.value as Facts["deadlineKind"], deadlineOn: "" })}><option value="">확인 필요</option><option value="fixed">마감일 있음</option><option value="none">정해진 마감 없음</option><option value="closed">이미 접수 종료</option></select>
      </Field>
      {value.deadlineKind === "fixed" && <Field name="deadlineOn" label="신청 마감일" help="한국 날짜를 기준으로 입력합니다." error={errors.deadlineOn}><input {...attrs("deadlineOn")} type="date" value={value.deadlineOn} onChange={(e) => set("deadlineOn", e.target.value)} /></Field>}
    </div>}
    {value.category === "event" && <div className="grid gap-6 sm:grid-cols-2">
      <Field name="eventStart" label="행사 시작일" help="접수 기간이 아닌 실제 개최 기간입니다." error={errors.eventStart}><input {...attrs("eventStart")} type="date" value={value.eventStart} onChange={(e) => set("eventStart", e.target.value)} /></Field>
      <Field name="eventEnd" label="행사 종료일" help="하루 행사라면 시작일과 같은 날짜입니다." error={errors.eventEnd}><input {...attrs("eventEnd")} type="date" value={value.eventEnd} onChange={(e) => set("eventEnd", e.target.value)} /></Field>
    </div>}
    <p className="text-sm leading-6 text-info-muted">사실을 저장하면 남은 사유와 AI 대기 여부를 다시 확인합니다. 여기서 AI를 실행하거나 콘텐츠를 게시하지 않습니다.</p>
  </div>;
}

export function CandidateEditor({ value, onChange, errors, disabled }: { value: CandidateContent; onChange: (value: CandidateContent) => void; errors: Record<string, string>; disabled: boolean }) {
  return <div className="grid gap-10 xl:grid-cols-2">
    {([{ name: "한국어", lang: "ko", suffix: "Ko" }, { name: "일본어", lang: "ja", suffix: "Ja" }] as const).map(({ name, lang, suffix }) => <fieldset key={lang} lang={lang} className="min-w-0 space-y-6">
      <legend className="mb-4 border-b border-info-rule pb-3 text-xl font-bold" lang="ko">{name} 내용</legend>
      {([{ prefix: "title", label: "제목", max: 300, rows: 2 }, { prefix: "summary", label: "요약", max: 1000, rows: 4 }, { prefix: "content", label: "상세", max: 200000, rows: 14 }] as const).map(({ prefix, label, max, rows }) => {
        const key = `${prefix}${suffix}` as keyof CandidateContent;
        return <Field key={key} name={key} label={`${name} ${label}`} error={errors[key]}>
          <textarea id={key} aria-invalid={Boolean(errors[key])} aria-describedby={errors[key] ? `${key}-error` : undefined} className={`${fieldClass} resize-y leading-7`} disabled={disabled} maxLength={max} rows={rows} value={value[key]} onChange={(e) => onChange({ ...value, [key]: e.target.value })} />
        </Field>;
      })}
    </fieldset>)}
  </div>;
}
