import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  // 내부 경로/정적 파일(_next, manifest.webmanifest, sw.js, 아이콘 등, 즉 '.'이 포함된 파일)은 제외
  matcher: ["/((?!api|_next|_vercel|.*\\..*).*)"],
};
