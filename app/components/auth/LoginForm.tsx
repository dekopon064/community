"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import type { AuthLocale } from "@/app/lib/auth/urls";
import { providerErrorNotice } from "@/app/lib/auth/urls";

type LoginProvider = "google" | "kakao";

export default function LoginForm({ locale, next, ready, kakaoEnabled }: { locale: AuthLocale; next: string; ready: boolean; kakaoEnabled: boolean }) {
  const t = useTranslations("Auth");
  const [pending, setPending] = useState<LoginProvider | null>(null);
  useEffect(() => {
    const notice = providerErrorNotice(window.location.hash);
    if (notice) {
      const url = new URL(window.location.href);
      url.hash = "";
      url.searchParams.set("notice", notice);
      window.location.replace(url.pathname + url.search);
      return;
    }
    const reset = () => setPending(null);
    window.addEventListener("pageshow", reset);
    return () => window.removeEventListener("pageshow", reset);
  }, []);
  return (
    <div className="mt-8" aria-busy={pending !== null}>
      <div className="space-y-3">
        {(["google", ...(kakaoEnabled ? ["kakao"] : [])] as LoginProvider[]).map((provider) => (
          <form key={provider} action="/api/auth/start" method="post" onSubmit={(event) => {
            if (pending) { event.preventDefault(); return; }
            setPending(provider);
          }}>
            <input type="hidden" name="locale" value={locale} />
            <input type="hidden" name="next" value={next} />
            <input type="hidden" name="provider" value={provider} />
            <button type="submit" disabled={!ready || pending !== null} className={`inline-flex min-h-12 w-full items-center justify-center gap-3 rounded-xl px-6 py-3 font-semibold transition-opacity hover:opacity-85 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ink disabled:cursor-not-allowed disabled:opacity-50 ${provider === "kakao" ? "bg-[#FEE500] text-black/85" : "bg-ink text-canvas-white"}`}>
              {provider === "kakao" && <svg aria-hidden="true" viewBox="61.5 16.5 13 13" className="h-5 w-5 shrink-0" fill="#000000">
                {/* Unmodified symbol geometry from Kakao's official login SVG. */}
                <path d="M68.001 16.5225C64.4222 16.5225 61.5225 19.0037 61.5225 22.0641C61.5225 24.0312 62.7219 25.7596 64.5292 26.7423L63.9181 29.2113C63.8954 29.285 63.9132 29.364 63.9619 29.4184C63.9975 29.457 64.0461 29.478 64.0931 29.478C64.1337 29.478 64.1742 29.464 64.2082 29.4341L66.834 27.5144C67.2117 27.5723 67.6007 27.6039 67.9994 27.6039C71.5767 27.6039 74.478 25.1226 74.478 22.0623C74.478 19.002 71.5783 16.5225 68.001 16.5225Z" />
              </svg>}
              {pending === provider ? t(provider === "kakao" ? "kakaoConnecting" : "connecting") : t(provider === "kakao" ? "kakaoLogin" : "googleLogin")}
            </button>
          </form>
        ))}
      </div>
      <p className="mt-3 text-sm leading-6 text-info-muted" role="status">{pending ? t("connectingHint") : t(kakaoEnabled ? "socialHint" : "googleHint")}</p>
    </div>
  );
}
