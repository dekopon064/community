import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { notFound } from "next/navigation";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { setRequestLocale } from "next-intl/server";
import { routing } from "@/i18n/routing";
import { themeColors } from "@/app/lib/theme";
import "@/app/globals.css";
import Header from "@/app/components/Header";
import BottomNav from "@/app/components/BottomNav";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "마치모아(Machimoa)",
  description: "마치모아(Machimoa)는 사람이 검수한 한국 생활정보를 한국어와 일본어로 제공합니다.",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Machimoa",
  },
  icons: {
    icon: [
      { url: "/icons/icon-192x192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512x512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: "/icons/icon-192x192.png",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // 앱 전역 배경(bg-canvas)과 동일한 토큰 값
  themeColor: themeColors.canvas,
};

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export default async function LocaleLayout({
  children,
  params,
}: Readonly<{
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}>) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) {
    notFound();
  }

  // 정적 렌더링을 위해 요청 locale을 활성화
  setRequestLocale(locale);

  return (
    <html
      lang={locale}
      className={`${geistSans.variable} ${geistMono.variable} antialiased`}
    >
      <body className="bg-canvas">
        <NextIntlClientProvider>
          <div className="relative flex min-h-screen w-full flex-col bg-canvas text-ink">
            <Header />
            <main className="flex-1 pb-[calc(4.5rem+env(safe-area-inset-bottom))] md:pb-0">{children}</main>
            <BottomNav />
          </div>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
