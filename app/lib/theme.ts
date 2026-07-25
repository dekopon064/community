/**
 * 디자인 토큰 HEX 단일 출처.
 * globals.css의 `@theme` 값과 동기화하며, PWA 매니페스트/뷰포트 등
 * CSS 변수(var(--color-*))를 사용할 수 없는 곳에서 참조한다.
 */
export const themeColors = {
  canvas: "#f5f4f1",
  canvasWhite: "#ffffff",
  ink: "#1c1c1a",
} as const;
