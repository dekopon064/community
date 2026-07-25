"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { supabase } from "@/app/lib/supabase";
import type { QnaEntry } from "@/app/lib/types";

const inputClass =
  "w-full bg-canvas-white border border-stone rounded-xl px-4 py-3 text-ink placeholder:text-ink-sub focus:outline-none focus:border-ink transition-colors";

export default function QnaPage() {
  const t = useTranslations("Qna");
  const locale = useLocale();

  const [entries, setEntries] = useState<QnaEntry[]>([]);
  const [nickname, setNickname] = useState("");
  const [content, setContent] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isFetching, setIsFetching] = useState(true);

  const fetchEntries = useCallback(async () => {
    const { data, error } = await supabase
      .from("qna_entries")
      .select("*")
      .order("created_at", { ascending: false });

    if (!error && data) {
      setEntries(data as QnaEntry[]);
    }
    setIsFetching(false);
  }, []);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!nickname.trim() || !content.trim() || isLoading) return;

    setIsLoading(true);
    const { error } = await supabase.from("qna_entries").insert({
      nickname: nickname.trim(),
      content: content.trim(),
    });

    if (!error) {
      setNickname("");
      setContent("");
      // 삽입 직후 최신 목록을 다시 가져와 화면 갱신
      await fetchEntries();
    }
    setIsLoading(false);
  }

  function formatTime(iso: string) {
    return new Intl.DateTimeFormat(locale, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  }

  return (
    // pt-6: 헤더(sticky) 여유 여백, pb-24: 고정 바텀 네비(h-16) 가림 방지
    <div className="min-h-[60vh] bg-canvas px-5 pt-6 pb-24">
      <h2 className="mb-6 text-lg font-bold text-ink">{t("title")}</h2>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <input
          type="text"
          value={nickname}
          onChange={(e) => setNickname(e.target.value)}
          placeholder={t("nicknamePlaceholder")}
          className={inputClass}
        />
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder={t("contentPlaceholder")}
          rows={3}
          className={`${inputClass} resize-none`}
        />
        <button
          type="submit"
          disabled={isLoading}
          className="mt-2 w-full rounded-xl bg-ink px-6 py-3 font-bold text-canvas-white transition-opacity disabled:opacity-60"
        >
          {isLoading ? t("submitting") : t("submit")}
        </button>
      </form>

      {/* 방명록 리스트: 카드가 아닌, 여백이 넓고 밑줄만 있는 플랫 뷰 */}
      {isFetching ? (
        <p className="mt-8 text-center text-sm text-ink-sub">{t("loading")}</p>
      ) : entries.length === 0 ? (
        <p className="mt-8 text-center text-sm text-ink-sub">{t("empty")}</p>
      ) : (
        <ul className="mt-8">
          {entries.map((entry) => (
            <li key={entry.id} className="border-b border-stone py-5">
              <div className="flex items-baseline">
                <span className="text-sm font-bold text-ink">
                  {entry.nickname}
                </span>
                <span className="ml-2 text-xs text-ink-sub">
                  {formatTime(entry.created_at)}
                </span>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-ink">
                {entry.content}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
