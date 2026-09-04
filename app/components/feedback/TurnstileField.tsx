"use client";

import Script from "next/script";
import { useEffect, useRef, useState } from "react";

const SCRIPT_ID = "cf-turnstile-explicit";
const SCRIPT_SRC =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

type TurnstileApi = {
  render: (
    container: HTMLElement,
    options: {
      sitekey: string;
      action: string;
      language: string;
      theme: "light";
      size: "flexible";
      appearance: "always";
      callback: (token: string) => void;
      "expired-callback": () => void;
      "error-callback": () => void;
      "timeout-callback": () => void;
    },
  ) => string;
  reset: (widgetId: string) => void;
  remove: (widgetId: string) => void;
};

function getTurnstile(): TurnstileApi | null {
  if (typeof window === "undefined") return null;
  const api = (window as Window & { turnstile?: TurnstileApi }).turnstile;
  return api ?? null;
}

export type TurnstileWidgetState = "loading" | "ready" | "expired" | "failed";

type TurnstileFieldProps = {
  siteKey: string;
  action: string;
  language: "ko" | "ja";
  resetSignal: number;
  labelledBy: string;
  describedBy?: string;
  statusLabel: string;
  loadingLabel: string;
  readyLabel: string;
  expiredLabel: string;
  failedLabel: string;
  widgetState: TurnstileWidgetState;
  onWidgetStateChange: (state: TurnstileWidgetState) => void;
  onTokenChange: (token: string | null) => void;
};

export default function TurnstileField({
  siteKey,
  action,
  language,
  resetSignal,
  labelledBy,
  describedBy,
  statusLabel,
  loadingLabel,
  readyLabel,
  expiredLabel,
  failedLabel,
  widgetState,
  onWidgetStateChange,
  onTokenChange,
}: TurnstileFieldProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const widgetIdRef = useRef<string | null>(null);
  const onTokenChangeRef = useRef(onTokenChange);
  const onWidgetStateChangeRef = useRef(onWidgetStateChange);
  const [scriptReady, setScriptReady] = useState(() => getTurnstile() !== null);

  useEffect(() => {
    onTokenChangeRef.current = onTokenChange;
    onWidgetStateChangeRef.current = onWidgetStateChange;
  });

  useEffect(() => {
    if (!scriptReady) return;

    let cancelled = false;
    const api = getTurnstile();
    const container = containerRef.current;
    if (!api || !container) return;

    if (widgetIdRef.current) {
      api.remove(widgetIdRef.current);
      widgetIdRef.current = null;
    }
    onTokenChangeRef.current(null);
    onWidgetStateChangeRef.current("loading");

    widgetIdRef.current = api.render(container, {
      sitekey: siteKey,
      action,
      language,
      theme: "light",
      size: "flexible",
      appearance: "always",
      callback: (token) => {
        if (cancelled) return;
        onTokenChangeRef.current(token);
        onWidgetStateChangeRef.current("ready");
      },
      "expired-callback": () => {
        if (cancelled) return;
        onTokenChangeRef.current(null);
        onWidgetStateChangeRef.current("expired");
      },
      "error-callback": () => {
        if (cancelled) return;
        onTokenChangeRef.current(null);
        onWidgetStateChangeRef.current("failed");
      },
      "timeout-callback": () => {
        if (cancelled) return;
        onTokenChangeRef.current(null);
        onWidgetStateChangeRef.current("expired");
      },
    });

    return () => {
      cancelled = true;
      const current = getTurnstile();
      if (current && widgetIdRef.current) {
        current.remove(widgetIdRef.current);
      }
      widgetIdRef.current = null;
      onTokenChangeRef.current(null);
    };
  }, [scriptReady, siteKey, action, language, resetSignal]);

  const statusText =
    widgetState === "ready"
      ? readyLabel
      : widgetState === "expired"
        ? expiredLabel
        : widgetState === "failed"
          ? failedLabel
          : loadingLabel;

  return (
    <div>
      <Script
        id={SCRIPT_ID}
        src={SCRIPT_SRC}
        strategy="afterInteractive"
        onReady={() => setScriptReady(true)}
      />
      <div
        ref={containerRef}
        className="min-h-11"
        role="group"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
      />
      <p className="mt-2 text-sm text-ink-sub" aria-live="polite">
        {statusLabel}: {statusText}
      </p>
    </div>
  );
}
