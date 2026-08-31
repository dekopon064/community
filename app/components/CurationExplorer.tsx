"use client";

import { useMemo, useState } from "react";
import CurationCard from "@/app/components/CurationCard";
import type { LocalizedCuration } from "@/app/lib/types";

const ALL = "전체";

export default function CurationExplorer({
  curations,
}: {
  curations: LocalizedCuration[];
}) {
  // 카테고리 칩 목록을 실제 DB 데이터에서 동적으로 도출
  const categories = useMemo(
    () => [ALL, ...Array.from(new Set(curations.map((c) => c.category)))],
    [curations],
  );

  const [active, setActive] = useState<string>(ALL);

  const filtered =
    active === ALL
      ? curations
      : curations.filter((item) => item.category === active);

  return (
    <>
      {/* 가로 스크롤 카테고리 필터 칩 (양 끝까지 스크롤되도록 -mx-5 px-5) */}
      <div className="-mx-5 mb-6 overflow-x-auto px-5 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="flex gap-2">
          {categories.map((category) => {
            const isActive = active === category;
            return (
              <button
                key={category}
                type="button"
                onClick={() => setActive(category)}
                aria-pressed={isActive}
                className={`min-h-11 shrink-0 rounded-full px-4 py-2 text-sm font-bold transition-colors ${
                  isActive
                    ? "bg-ink text-canvas-white"
                    : "border border-stone bg-transparent text-ink-sub hover:text-ink"
                }`}
              >
                {category}
              </button>
            );
          })}
        </div>
      </div>

      {/* 큐레이션 리스트 */}
      <div className="flex flex-col gap-4">
        {filtered.map((item) => (
          <CurationCard
            key={item.id}
            slug={item.slug}
            category={item.category}
            title={item.title}
            summary={item.summary}
          />
        ))}
      </div>
    </>
  );
}
