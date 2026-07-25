import type { NextConfig } from "next";
import withSerwistInit from "@serwist/next";
import createNextIntlPlugin from "next-intl/plugin";

// next-intl 요청 설정(i18n/request.ts)을 연결
const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

const withSerwist = withSerwistInit({
  swSrc: "app/sw.ts",
  swDest: "public/sw.js",
  cacheOnNavigation: true,
  reloadOnOnline: true,
  // 개발 환경에서는 서비스 워커 캐싱이 성가신 문제를 일으키므로 비활성화
  disable: process.env.NODE_ENV === "development",
});

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Serwist가 webpack 설정을 주입하므로, Turbopack(dev 기본) 충돌 경고를 없애기 위한 빈 설정
  turbopack: {},
};

// 플러그인 래퍼 체이닝: next-intl → Serwist 순으로 안전하게 감싼다
export default withSerwist(withNextIntl(nextConfig));
