"use client";

import styles from "./AuthSurfaces.module.css";
import Image from "next/image";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import type { AuthLocale } from "@/app/lib/auth/urls";
import { providerErrorNotice } from "@/app/lib/auth/urls";

type LoginProvider = "google" | "kakao" | "line";
const loginLabels = { google: "googleLogin", kakao: "kakaoLogin", line: "lineLogin" } as const;
const connectingLabels = { google: "connecting", kakao: "kakaoConnecting", line: "lineConnecting" } as const;

export default function LoginForm({ locale, next, ready, kakaoEnabled, lineEnabled = false, saveIntent }: { locale: AuthLocale; next: string; ready: boolean; kakaoEnabled: boolean; lineEnabled?: boolean; saveIntent?: string }) {
  const t = useTranslations("Auth");
  const [pending, setPending] = useState<LoginProvider | null>(null);
  useEffect(() => {
    if (new URL(window.location.href).searchParams.get("notice") === "signed_out") {
      window.dispatchEvent(new Event("machimoa-account-change"));
      if (typeof BroadcastChannel !== "undefined") { const channel = new BroadcastChannel("machimoa-account"); channel.postMessage("logout-confirmed"); channel.close(); }
    }
    const notice = providerErrorNotice(window.location.hash);
    if (notice) {
      const url = new URL(window.location.href);
      url.hash = "";
      url.searchParams.set("notice", notice);
      url.searchParams.delete("saveIntent");
      void fetch("/api/saved/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}", cache: "no-store" }).finally(() => window.location.replace(url.pathname + url.search));
      return;
    }
    const reset = () => setPending(null);
    window.addEventListener("pageshow", reset);
    return () => window.removeEventListener("pageshow", reset);
  }, []);
  return (
    <div className={styles.providers} aria-busy={pending !== null}>
      <p className={styles.external} role="status">{pending ? t("connectingHint") : t("externalHint")}</p>
      <div className="space-y-3">
        {(["google", ...(kakaoEnabled ? ["kakao"] : []), ...(lineEnabled ? ["line"] : [])] as LoginProvider[]).map((provider) => (
          <form key={provider} action="/api/auth/start" method="post" onSubmit={(event) => {
            if (pending) { event.preventDefault(); return; }
            setPending(provider);
          }}>
            <input type="hidden" name="locale" value={locale} />
            <input type="hidden" name="next" value={next} />
            <input type="hidden" name="provider" value={provider} />
            {saveIntent && <input type="hidden" name="saveIntent" value={saveIntent} />}
            <button type="submit" disabled={!ready || pending !== null} className={`${styles.provider} ${styles[provider]}`}>
              {provider === "google" && <span className={styles.googleMark} aria-hidden="true"><Image unoptimized className={styles.lightMark} src="/auth/google-light.png" alt="" width={40} height={40} /><Image unoptimized className={styles.neutralMark} src="/auth/google-neutral.png" alt="" width={40} height={40} /></span>}
              {provider === "kakao" && <svg aria-hidden="true" viewBox="61.5 16.5 13 13" className="h-5 w-5 shrink-0" fill="#000000">
                {/* Unmodified symbol geometry from Kakao's official login SVG. */}
                <path d="M68.001 16.5225C64.4222 16.5225 61.5225 19.0037 61.5225 22.0641C61.5225 24.0312 62.7219 25.7596 64.5292 26.7423L63.9181 29.2113C63.8954 29.285 63.9132 29.364 63.9619 29.4184C63.9975 29.457 64.0461 29.478 64.0931 29.478C64.1337 29.478 64.1742 29.464 64.2082 29.4341L66.834 27.5144C67.2117 27.5723 67.6007 27.6039 67.9994 27.6039C71.5767 27.6039 74.478 25.1226 74.478 22.0623C74.478 19.002 71.5783 16.5225 68.001 16.5225Z" />
              </svg>}
              {provider === "line" && <span className={styles.lineMark} aria-hidden="true" />}
              <span className={provider === "line" ? styles.lineLabel : undefined}>
                {pending === provider ? t(connectingLabels[provider]) : t(loginLabels[provider])}
              </span>
            </button>
          </form>
        ))}
      </div>
    </div>
  );
}
