import type { MetadataRoute } from "next";
import { themeColors } from "@/app/lib/theme";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "마치모아(Machimoa)",
    short_name: "Machimoa",
    description: "마치모아(Machimoa)는 사람이 검수한 한국 생활정보를 한국어와 일본어로 제공합니다.",
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
