const PRODUCTION_SUBMIT_ACTION = "feedback_submit";
const PRODUCTION_DELETE_ACTION = "feedback_delete";

export type TurnstileWidgetKind = "submit" | "delete";

export type TurnstilePublicConfig = {
  siteKey: string;
  action: string;
};

function requirePublicEnv(name: string, value: string | undefined): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${name} is not configured`);
  }
  return value;
}

function isVercelProduction(): boolean {
  return process.env.VERCEL_ENV === "production";
}

export function getTurnstilePublicConfig(
  kind: TurnstileWidgetKind,
): TurnstilePublicConfig {
  const siteKey = requirePublicEnv(
    "NEXT_PUBLIC_TURNSTILE_SITE_KEY",
    process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY,
  );
  const submitAction = requirePublicEnv(
    "NEXT_PUBLIC_TURNSTILE_SUBMIT_ACTION",
    process.env.NEXT_PUBLIC_TURNSTILE_SUBMIT_ACTION,
  );
  const deleteAction = requirePublicEnv(
    "NEXT_PUBLIC_TURNSTILE_DELETE_ACTION",
    process.env.NEXT_PUBLIC_TURNSTILE_DELETE_ACTION,
  );

  if (isVercelProduction()) {
    if (submitAction !== PRODUCTION_SUBMIT_ACTION) {
      throw new Error("Production Turnstile submit action mismatch");
    }
    if (deleteAction !== PRODUCTION_DELETE_ACTION) {
      throw new Error("Production Turnstile delete action mismatch");
    }
  }

  return {
    siteKey,
    action: kind === "submit" ? submitAction : deleteAction,
  };
}
