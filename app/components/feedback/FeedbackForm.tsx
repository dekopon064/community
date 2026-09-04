"use client";

import { useId, useRef, useState, type FormEvent } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import {
  isFeedbackBodyLengthValid,
  normalizeFeedbackBody,
  FEEDBACK_BODY_MAX,
  FEEDBACK_BODY_MIN,
} from "@/app/lib/feedback-body";
import { submitFeedback, type FeedbackErrorCode } from "@/app/lib/feedback-client";
import { FEEDBACK_PRIVACY_NOTICE_VERSION } from "@/app/lib/feedback-privacy";
import type { CurationCategoryKey } from "@/app/lib/categories";
import FeedbackPrivacyNotice from "@/app/components/feedback/FeedbackPrivacyNotice";
import FeedbackSuccess from "@/app/components/feedback/FeedbackSuccess";
import TurnstileField, {
  type TurnstileWidgetState,
} from "@/app/components/feedback/TurnstileField";

const FEEDBACK_TYPES = [
  "hard_to_find_life_info",
  "product_opinion",
  "other_inquiry",
] as const;

const TOPICS: readonly CurationCategoryKey[] = [
  "housing",
  "identity",
  "work",
  "education",
  "welfare",
  "participation",
  "other",
];

const controlClass =
  "w-full min-h-11 rounded-xl border bg-canvas-white px-4 py-3 text-ink placeholder:text-ink-sub transition-colors focus:outline-none focus-visible:outline-3 focus-visible:outline-offset-3 disabled:opacity-60";
const validControlClass = "border-stone focus:border-ink focus-visible:outline-focus";
const invalidControlClass = "border-coral focus:border-coral focus-visible:outline-coral";

function asStringList(value: unknown): readonly string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

type FeedbackFormProps = {
  turnstileSiteKey: string;
  turnstileAction: string;
};

export default function FeedbackForm({
  turnstileSiteKey,
  turnstileAction,
}: FeedbackFormProps) {
  const t = useTranslations("Feedback");
  const categoriesT = useTranslations("Categories");
  const locale = useLocale();
  const language = locale === "ja" ? "ja" : "ko";

  const errorRef = useRef<HTMLDivElement>(null);
  const [feedbackType, setFeedbackType] = useState<(typeof FEEDBACK_TYPES)[number] | "">("");
  const [topic, setTopic] = useState<CurationCategoryKey | "">("");
  const [body, setBody] = useState("");
  const [privacyConsent, setPrivacyConsent] = useState(false);
  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [honeypot, setHoneypot] = useState("");
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const [widgetState, setWidgetState] = useState<TurnstileWidgetState>("loading");
  const [resetSignal, setResetSignal] = useState(0);
  const [status, setStatus] = useState<"idle" | "submitting" | "success">("idle");
  const [receiptCode, setReceiptCode] = useState<string | null>(null);
  const [clientErrors, setClientErrors] = useState<string[]>([]);
  const [serverError, setServerError] = useState<FeedbackErrorCode | null>(null);

  const ids = {
    title: useId(),
    typeError: useId(),
    body: useId(),
    bodyHelp: useId(),
    bodyError: useId(),
    requiredNotice: useId(),
    privacyError: useId(),
    ageHelp: useId(),
    ageError: useId(),
    turnstile: useId(),
    turnstileHelp: useId(),
    turnstileError: useId(),
    error: useId(),
    errorTitle: useId(),
  };

  const normalizedBody = normalizeFeedbackBody(body);
  const submitting = status === "submitting";

  function discardTurnstile() {
    setTurnstileToken(null);
    setResetSignal((value) => value + 1);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || status === "success") return;

    const nextErrors: string[] = [];
    if (!feedbackType) nextErrors.push("typeRequired");
    if (!isFeedbackBodyLengthValid(normalizedBody)) nextErrors.push("bodyLength");
    if (!privacyConsent) nextErrors.push("privacyRequired");
    if (!ageConfirmed) nextErrors.push("ageRequired");
    if (!turnstileToken) nextErrors.push("turnstileRequired");

    setClientErrors(nextErrors);
    setServerError(null);

    if (nextErrors.length > 0) {
      requestAnimationFrame(() => errorRef.current?.focus());
      return;
    }

    if (
      feedbackType !== "hard_to_find_life_info" &&
      feedbackType !== "product_opinion" &&
      feedbackType !== "other_inquiry"
    ) {
      return;
    }

    setStatus("submitting");

    const result = await submitFeedback({
      feedback_type: feedbackType,
      body: normalizedBody,
      locale: language,
      privacy_consent: true,
      age_confirmed: true,
      privacy_notice_version: FEEDBACK_PRIVACY_NOTICE_VERSION,
      turnstile_token: turnstileToken ?? "",
      topic: topic === "" ? undefined : topic,
      honeypot: honeypot.length > 0 ? honeypot : undefined,
    });

    if (result.ok) {
      discardTurnstile();
      setReceiptCode(result.receiptCode);
      setStatus("success");
      return;
    }

    discardTurnstile();
    setStatus("idle");
    setServerError(result.error);
    requestAnimationFrame(() => errorRef.current?.focus());
  }

  if (status === "success" && receiptCode) {
    return (
      <FeedbackSuccess
        receiptCode={receiptCode}
        title={t("successTitle")}
        warning={t("receiptWarning")}
        unrecoverable={t("receiptUnrecoverable")}
        copyLabel={t("copy")}
        copiedLabel={t("copied")}
        copyFailedLabel={t("copyFailed")}
        deleteLabel={t("deleteLink")}
        privacyLabel={t("privacyLink")}
      />
    );
  }

  const errorMessages = [
    ...clientErrors.map((key) => t(`errors.${key}`)),
    ...(serverError ? [t(`errors.${serverError}`)] : []),
  ];
  const typeInvalid = clientErrors.includes("typeRequired");
  const bodyInvalid = clientErrors.includes("bodyLength");
  const privacyInvalid = clientErrors.includes("privacyRequired");
  const ageInvalid = clientErrors.includes("ageRequired");
  const turnstileInvalid = clientErrors.includes("turnstileRequired");

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
          id={ids.error}
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
      <p className="text-sm leading-6 text-ink-sub">{t("anonymousNote")}</p>

      <fieldset
        className="space-y-3"
        aria-describedby={typeInvalid ? ids.typeError : undefined}
      >
        <legend className="text-sm font-bold text-ink">{t("typeLegend")}</legend>
        {FEEDBACK_TYPES.map((value) => (
          <label key={value} className="flex min-h-11 items-center gap-3">
            <input
              type="radio"
              name="feedback_type"
              value={value}
              checked={feedbackType === value}
              onChange={() => setFeedbackType(value)}
              disabled={submitting}
              className={`h-5 w-5 accent-focus ${typeInvalid ? "outline outline-2 outline-offset-2 outline-coral" : ""}`}
            />
            <span className="text-sm leading-6 text-ink">{t(`types.${value}`)}</span>
          </label>
        ))}
        {typeInvalid && (
          <p id={ids.typeError} className="text-sm leading-6 text-coral">
            {t("errors.typeRequired")}
          </p>
        )}
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-sm font-bold text-ink">{t("topicLegend")}</legend>
        <label className="flex min-h-11 items-center gap-3">
          <input
            type="radio"
            name="topic"
            value=""
            checked={topic === ""}
            onChange={() => setTopic("")}
            disabled={submitting}
            className="h-5 w-5 accent-focus"
          />
          <span className="text-sm leading-6 text-ink">{t("topicNone")}</span>
        </label>
        {TOPICS.map((value) => (
          <label key={value} className="flex min-h-11 items-center gap-3">
            <input
              type="radio"
              name="topic"
              value={value}
              checked={topic === value}
              onChange={() => setTopic(value)}
              disabled={submitting}
              className="h-5 w-5 accent-focus"
            />
            <span className="text-sm leading-6 text-ink">{categoriesT(value)}</span>
          </label>
        ))}
      </fieldset>

      <div>
        <label htmlFor={ids.body} className="text-sm font-bold text-ink">
          {t("bodyLabel")}
        </label>
        <p id={ids.bodyHelp} className="mt-2 text-sm leading-6 text-ink-sub">
          {t("bodyHelp")}
        </p>
        <textarea
          id={ids.body}
          value={body}
          onChange={(event) => setBody(event.target.value)}
          disabled={submitting}
          rows={8}
          aria-describedby={
            bodyInvalid ? `${ids.bodyHelp} ${ids.bodyError}` : ids.bodyHelp
          }
          aria-invalid={bodyInvalid}
          className={`${controlClass} ${bodyInvalid ? invalidControlClass : validControlClass} mt-3 resize-y`}
        />
        {bodyInvalid && (
          <p id={ids.bodyError} className="mt-2 text-sm leading-6 text-coral">
            {t("errors.bodyLength")}
          </p>
        )}
        <p className="mt-2 text-sm tabular-nums text-ink-sub">
          {t("bodyCount", {
            count: normalizedBody.length,
            min: FEEDBACK_BODY_MIN,
            max: FEEDBACK_BODY_MAX,
          })}
        </p>
      </div>

      <div className="sr-only" aria-hidden="true">
        <label>
          {t("honeypotLabel")}
          <input
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={honeypot}
            onChange={(event) => setHoneypot(event.target.value)}
          />
        </label>
      </div>

      <fieldset className="space-y-4">
        <legend className="sr-only">{t("requiredNoticeLegend")}</legend>
        <FeedbackPrivacyNotice
          legendId={ids.requiredNotice}
          copy={{
            title: t("requiredNotice.title"),
            purposeLabel: t("requiredNotice.purposeLabel"),
            purposes: asStringList(t.raw("requiredNotice.purposes")),
            itemsLabel: t("requiredNotice.itemsLabel"),
            items: asStringList(t.raw("requiredNotice.items")),
            retentionLabel: t("requiredNotice.retentionLabel"),
            retention: asStringList(t.raw("requiredNotice.retention")),
            refusalLabel: t("requiredNotice.refusalLabel"),
            refusal: asStringList(t.raw("requiredNotice.refusal")),
          }}
        />
        <label className="flex min-h-11 items-start gap-3">
          <input
            type="checkbox"
            checked={privacyConsent}
            onChange={(event) => setPrivacyConsent(event.target.checked)}
            disabled={submitting}
            aria-describedby={privacyInvalid ? ids.privacyError : undefined}
            aria-invalid={privacyInvalid}
            className={`mt-1 h-5 w-5 accent-focus ${privacyInvalid ? "outline outline-2 outline-offset-2 outline-coral" : ""}`}
          />
          <span className="text-sm leading-6 text-ink">{t("privacyConsent")}</span>
        </label>
        {privacyInvalid && (
          <p id={ids.privacyError} className="text-sm leading-6 text-coral">
            {t("errors.privacyRequired")}
          </p>
        )}
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-sm font-bold text-ink">{t("ageLegend")}</legend>
        <p id={ids.ageHelp} className="text-sm leading-6 text-ink-sub">
          {t("ageHelp")}
        </p>
        <label className="flex min-h-11 items-start gap-3">
          <input
            type="checkbox"
            checked={ageConfirmed}
            onChange={(event) => setAgeConfirmed(event.target.checked)}
            disabled={submitting}
            aria-describedby={
              ageInvalid ? `${ids.ageHelp} ${ids.ageError}` : ids.ageHelp
            }
            aria-invalid={ageInvalid}
            className={`mt-1 h-5 w-5 accent-focus ${ageInvalid ? "outline outline-2 outline-offset-2 outline-coral" : ""}`}
          />
          <span className="text-sm leading-6 text-ink">{t("ageConsent")}</span>
        </label>
        {ageInvalid && (
          <p id={ids.ageError} className="text-sm leading-6 text-coral">
            {t("errors.ageRequired")}
          </p>
        )}
      </fieldset>

      <div>
        <p id={ids.turnstile} className="text-sm font-bold text-ink">
          {t("turnstileLegend")}
        </p>
        <p id={ids.turnstileHelp} className="mt-2 text-sm leading-6 text-ink-sub">
          {t("turnstileHelp")}
        </p>
        <div className={`mt-3 ${turnstileInvalid ? "rounded-xl outline outline-2 outline-offset-2 outline-coral" : ""}`}>
          <TurnstileField
            siteKey={turnstileSiteKey}
            action={turnstileAction}
            language={language}
            resetSignal={resetSignal}
            labelledBy={ids.turnstile}
            describedBy={
              turnstileInvalid
                ? `${ids.turnstileHelp} ${ids.turnstileError}`
                : ids.turnstileHelp
            }
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
        {turnstileInvalid && (
          <p id={ids.turnstileError} className="mt-2 text-sm leading-6 text-coral">
            {t("errors.turnstileRequired")}
          </p>
        )}
      </div>

      <p className="text-sm leading-6 text-ink-sub">{t("legalReviewNote")}</p>
      <p className="text-sm leading-6 text-ink-sub">{t("receiptBeforeSubmit")}</p>

      <button
        type="submit"
        disabled={submitting}
        className="inline-flex min-h-11 w-full items-center justify-center rounded-xl bg-ink px-6 text-sm font-bold text-canvas-white disabled:opacity-60 md:w-auto"
      >
        {submitting ? t("submitting") : t("submit")}
      </button>

      <p className="flex flex-col gap-3">
        <Link
          href="/privacy"
          className="inline-flex min-h-11 items-center text-sm font-semibold underline underline-offset-2"
        >
          {t("privacyLink")}
        </Link>
        <Link
          href="/feedback/delete"
          className="inline-flex min-h-11 items-center text-sm font-semibold underline underline-offset-2"
        >
          {t("deleteLink")}
        </Link>
      </p>
    </form>
  );
}
