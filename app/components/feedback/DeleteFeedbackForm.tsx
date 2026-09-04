"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { deleteFeedback, type FeedbackErrorCode } from "@/app/lib/feedback-client";
import TurnstileField, {
  type TurnstileWidgetState,
} from "@/app/components/feedback/TurnstileField";

const controlClass =
  "w-full min-h-11 rounded-xl border border-stone bg-canvas-white px-4 py-3 font-mono text-ink placeholder:text-ink-sub transition-colors focus:border-ink focus:outline-none focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-focus disabled:opacity-60";

type DeleteFeedbackFormProps = {
  turnstileSiteKey: string;
  turnstileAction: string;
  language: "ko" | "ja";
};

export default function DeleteFeedbackForm({
  turnstileSiteKey,
  turnstileAction,
  language,
}: DeleteFeedbackFormProps) {
  const t = useTranslations("FeedbackDelete");
  const errorRef = useRef<HTMLDivElement>(null);
  const processedRef = useRef<HTMLHeadingElement>(null);
  const [receiptCode, setReceiptCode] = useState("");
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const [widgetState, setWidgetState] = useState<TurnstileWidgetState>("loading");
  const [resetSignal, setResetSignal] = useState(0);
  const [status, setStatus] = useState<"idle" | "submitting" | "processed">("idle");
  const [clientErrors, setClientErrors] = useState<string[]>([]);
  const [serverError, setServerError] = useState<FeedbackErrorCode | null>(null);

  const ids = {
    title: useId(),
    receipt: useId(),
    receiptHelp: useId(),
    turnstile: useId(),
    turnstileHelp: useId(),
    errorTitle: useId(),
  };

  const submitting = status === "submitting";

  useEffect(() => {
    if (status === "processed") {
      processedRef.current?.focus();
    }
  }, [status]);

  function discardTurnstile() {
    setTurnstileToken(null);
    setResetSignal((value) => value + 1);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || status === "processed") return;

    const trimmed = receiptCode.trim();
    const nextErrors: string[] = [];
    if (trimmed.length === 0 || trimmed.length > 64) {
      nextErrors.push("receiptInvalid");
    }
    if (!turnstileToken) nextErrors.push("turnstileRequired");

    setClientErrors(nextErrors);
    setServerError(null);

    if (nextErrors.length > 0) {
      requestAnimationFrame(() => errorRef.current?.focus());
      return;
    }

    setStatus("submitting");
    const result = await deleteFeedback({
      receipt_code: trimmed,
      turnstile_token: turnstileToken ?? "",
    });

    if (result.ok) {
      discardTurnstile();
      setReceiptCode("");
      setStatus("processed");
      return;
    }

    discardTurnstile();
    setStatus("idle");
    setServerError(result.error);
    requestAnimationFrame(() => errorRef.current?.focus());
  }

  if (status === "processed") {
    return (
      <section className="rounded-[1.5rem] border border-stone bg-canvas-white px-5 py-8 md:px-8 md:py-10">
        <h1
          ref={processedRef}
          tabIndex={-1}
          className="text-2xl font-bold tracking-[-0.035em] text-ink md:text-3xl"
        >
          {t("processedTitle")}
        </h1>
        <p className="mt-5 text-base leading-7 text-ink-sub">{t("processedBody")}</p>
        <p className="mt-8">
          <Link
            href="/privacy"
            className="inline-flex min-h-11 items-center text-sm font-semibold underline underline-offset-2"
          >
            {t("privacyLink")}
          </Link>
        </p>
      </section>
    );
  }

  const errorMessages = [
    ...clientErrors.map((key) => t(`errors.${key}`)),
    ...(serverError ? [t(`errors.${serverError}`)] : []),
  ];

  return (
    <form
      onSubmit={onSubmit}
      className="relative space-y-8"
      noValidate
      aria-busy={submitting}
      aria-labelledby={ids.title}
    >
      <h1
        id={ids.title}
        className="text-2xl font-bold tracking-[-0.035em] text-ink md:text-3xl"
      >
        {t("title")}
      </h1>

      {errorMessages.length > 0 && (
        <div
          ref={errorRef}
          tabIndex={-1}
          role="alert"
          aria-labelledby={ids.errorTitle}
          className="rounded-[1.25rem] border border-coral bg-canvas-white px-4 py-4"
        >
          <h2 id={ids.errorTitle} className="text-base font-bold text-ink">
            {t("errorTitle")}
          </h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-ink">
            {errorMessages.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-base leading-7 text-ink-sub">{t("intro")}</p>
      <p className="text-sm leading-6 text-ink-sub">{t("existenceNote")}</p>

      <div>
        <label htmlFor={ids.receipt} className="text-sm font-bold text-ink">
          {t("receiptLabel")}
        </label>
        <p id={ids.receiptHelp} className="mt-2 text-sm leading-6 text-ink-sub">
          {t("receiptHelp")}
        </p>
        <input
          id={ids.receipt}
          type="text"
          inputMode="text"
          autoComplete="off"
          spellCheck={false}
          value={receiptCode}
          onChange={(event) => setReceiptCode(event.target.value.toUpperCase())}
          disabled={submitting}
          aria-describedby={ids.receiptHelp}
          aria-invalid={clientErrors.includes("receiptInvalid")}
          className={`${controlClass} mt-3`}
        />
      </div>

      <div>
        <p id={ids.turnstile} className="text-sm font-bold text-ink">
          {t("turnstileLegend")}
        </p>
        <p id={ids.turnstileHelp} className="mt-2 text-sm leading-6 text-ink-sub">
          {t("turnstileHelp")}
        </p>
        <div className="mt-3">
          <TurnstileField
            siteKey={turnstileSiteKey}
            action={turnstileAction}
            language={language}
            resetSignal={resetSignal}
            labelledBy={ids.turnstile}
            describedBy={ids.turnstileHelp}
            statusLabel={t("turnstileStatus")}
            loadingLabel={t("turnstileLoading")}
            readyLabel={t("turnstileReady")}
            expiredLabel={t("turnstileExpired")}
            failedLabel={t("turnstileFailed")}
            widgetState={widgetState}
            onWidgetStateChange={setWidgetState}
            onTokenChange={setTurnstileToken}
          />
        </div>
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="inline-flex min-h-11 w-full items-center justify-center rounded-xl bg-ink px-6 text-sm font-bold text-canvas-white disabled:opacity-60 md:w-auto"
      >
        {submitting ? t("submitting") : t("submit")}
      </button>
    </form>
  );
}
