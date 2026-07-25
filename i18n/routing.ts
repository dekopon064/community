import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  // 지원 언어: 한국어, 일본어
  locales: ["ko", "ja"],
  // 기본 언어
  defaultLocale: "ko",
});
