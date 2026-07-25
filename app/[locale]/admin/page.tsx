"use client";

import { useState } from "react";
import Markdown from "@/app/components/Markdown";
import { supabase } from "@/app/lib/supabase";

type Status = { type: "success" | "error"; message: string } | null;

const inputClass =
  "w-full bg-canvas-white border border-stone rounded-xl px-4 py-3 text-ink placeholder:text-ink-sub focus:outline-none focus:border-ink transition-colors";

const labelClass = "mb-1.5 block text-xs font-bold text-ink-sub";

export default function AdminPage() {
  const [slug, setSlug] = useState("");
  const [category, setCategory] = useState("");
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [content, setContent] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [status, setStatus] = useState<Status>(null);

  function reset() {
    setSlug("");
    setCategory("");
    setTitle("");
    setSummary("");
    setContent("");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (
      !slug.trim() ||
      !category.trim() ||
      !title.trim() ||
      !summary.trim() ||
      !content.trim() ||
      isSubmitting
    ) {
      return;
    }

    setIsSubmitting(true);
    setStatus(null);

    const { error } = await supabase.from("curations").insert({
      slug: slug.trim(),
      category: category.trim(),
      title: title.trim(),
      summary: summary.trim(),
      content: content.trim(),
    });

    if (error) {
      setStatus({ type: "error", message: `등록 실패: ${error.message}` });
    } else {
      setStatus({ type: "success", message: "큐레이션이 등록되었습니다." });
      reset();
    }
    setIsSubmitting(false);
  }

  return (
    <div className="min-h-[60vh] bg-canvas px-5 pt-6 pb-24">
      <h2 className="mb-1 text-lg font-bold text-ink">큐레이션 관리</h2>
      <p className="mb-6 text-sm text-ink-sub">
        관리자 전용 · 새 큐레이션 글 작성
      </p>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div>
          <label className={labelClass} htmlFor="slug">
            Slug (영문 ID)
          </label>
          <input
            id="slug"
            type="text"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="visa-03"
            className={inputClass}
          />
        </div>

        <div>
          <label className={labelClass} htmlFor="category">
            Category (카테고리)
          </label>
          <input
            id="category"
            type="text"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="비자"
            className={inputClass}
          />
        </div>

        <div>
          <label className={labelClass} htmlFor="title">
            Title (제목)
          </label>
          <input
            id="title"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="제목을 입력하세요"
            className={inputClass}
          />
        </div>

        <div>
          <label className={labelClass} htmlFor="summary">
            Summary (요약)
          </label>
          <textarea
            id="summary"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="한 줄 요약을 입력하세요"
            rows={2}
            className={`${inputClass} resize-none`}
          />
        </div>

        <div>
          <label className={labelClass} htmlFor="content">
            Content (본문 · 마크다운 지원)
          </label>
          <textarea
            id="content"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={"## 소제목\n\n- 리스트 항목\n- **볼드** 텍스트\n\n[링크](https://example.com)"}
            rows={10}
            className={`${inputClass} resize-y font-mono text-xs`}
          />
        </div>

        {/* 실시간 마크다운 프리뷰 */}
        <div>
          <span className={labelClass}>미리보기</span>
          <div className="min-h-24 rounded-xl border border-stone bg-canvas-white p-4">
            {content.trim() ? (
              <Markdown>{content}</Markdown>
            ) : (
              <p className="text-sm text-ink-sub">
                본문을 입력하면 여기에 미리보기가 표시됩니다.
              </p>
            )}
          </div>
        </div>

        {status && (
          <p
            className={`text-sm ${
              status.type === "success" ? "text-ink" : "text-ink-sub"
            }`}
          >
            {status.message}
          </p>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="mt-2 w-full rounded-xl bg-ink px-6 py-3 font-bold text-canvas-white transition-opacity disabled:opacity-60"
        >
          {isSubmitting ? "등록 중..." : "큐레이션 등록"}
        </button>
      </form>
    </div>
  );
}
