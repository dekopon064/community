import type { MetadataRoute } from "next";
import { themeColors } from "@/app/lib/theme";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "한일 청년 교류 플랫폼",
    short_name: "한일교류",
    description: "한일 2030 청년들을 위한 정보 큐레이션 및 소통 앱",
    start_url: "/",
    display: "standalone",
    orientation: "portrait",
    // 앱 전역 배경(bg-canvas)과 일치시켜 설치 시 테마/스플래시 색상 통일
    theme_color: themeColors.canvas,
    background_color: themeColors.canvas,
    icons: [
      {
        src: "/icons/icon-192x192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/icon-512x512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/icon-192x192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "maskable",
      },
      {
        src: "/icons/icon-512x512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
