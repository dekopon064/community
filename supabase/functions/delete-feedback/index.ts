import { getDeno, loadConfig } from "../_shared/env.ts";
import {
  errorResponse,
  gateRequest,
  jsonResponse,
  logRequest,
  newRequestId,
} from "../_shared/http.ts";
import {
  rateHmac,
  rateIdentity,
  receiptHmac,
  toByteaLiteral,
  verifyTurnstile,
} from "../_shared/security.ts";
import { deleteFeedbackRpc } from "../_shared/services.ts";
import { parseDeleteBody } from "../_shared/validation.ts";

const runtime = getDeno();
if (runtime !== null) {
  runtime.serve(async (req) => {
  const requestId = newRequestId();
  const fn = "delete-feedback" as const;
  let responseOrigin: string | null = null;

  try {
    const config = loadConfig();
    if (config === null) {
      logRequest({
        request_id: requestId,
        at: new Date().toISOString(),
        fn,
        ok: false,
        error: "temporary_error",
      });
      return errorResponse(503, "temporary_error", null);
    }

    const gated = await gateRequest(req, config, fn, requestId);
    if (!gated.ok) {
      return gated.response;
    }
    responseOrigin = gated.origin;

    const parsed = parseDeleteBody(gated.body);
    if (!parsed.ok) {
      logRequest({
        request_id: requestId,
        at: new Date().toISOString(),
        fn,
        ok: false,
        error: parsed.error,
      });
      return errorResponse(400, parsed.error, gated.origin);
    }

    const identity = rateIdentity(req, config);
    if (identity === null) {
      logRequest({
        request_id: requestId,
        at: new Date().toISOString(),
        fn,
        ok: false,
        error: "temporary_error",
      });
      return errorResponse(503, "temporary_error", gated.origin);
    }

    const turnstile = await verifyTurnstile({
      secret: config.turnstileSecret,
      token: parsed.value.turnstileToken,
      expectedHostname: config.turnstileHostname,
      expectedAction: config.turnstileDeleteAction,
      remoteip: config.hosted ? identity : null,
    });
    if (!turnstile.ok) {
      logRequest({
        request_id: requestId,
        at: new Date().toISOString(),
        fn,
        ok: false,
        error: turnstile.error,
      });
      const status = turnstile.error === "turnstile_unavailable" ? 503 : 400;
      return errorResponse(status, turnstile.error, gated.origin);
    }

    if (parsed.value.receiptCanonical === null) {
      logRequest({
        request_id: requestId,
        at: new Date().toISOString(),
        fn,
        ok: true,
      });
      return jsonResponse(200, { ok: true, outcome: "processed" }, gated.origin);
    }

    const receiptMac = await receiptHmac(
      config.receiptHmacSecret,
      parsed.value.receiptCanonical,
    );
    const rateMac = await rateHmac(config.rateHmacSecret, "delete", identity);
    if (receiptMac === null || rateMac === null) {
      logRequest({
        request_id: requestId,
        at: new Date().toISOString(),
        fn,
        ok: false,
        error: "temporary_error",
      });
      return errorResponse(503, "temporary_error", gated.origin);
    }

    const rpc = await deleteFeedbackRpc(
      config,
      toByteaLiteral(receiptMac),
      toByteaLiteral(rateMac),
    );
    if (!rpc.ok) {
      logRequest({
        request_id: requestId,
        at: new Date().toISOString(),
        fn,
        ok: false,
        error: "temporary_error",
      });
      return errorResponse(503, "temporary_error", gated.origin);
    }

    if (rpc.outcome === "rate_limited") {
      logRequest({
        request_id: requestId,
        at: new Date().toISOString(),
        fn,
        ok: false,
        error: "rate_limited",
      });
      return errorResponse(429, "rate_limited", gated.origin);
    }

    logRequest({
      request_id: requestId,
      at: new Date().toISOString(),
      fn,
      ok: true,
    });
    return jsonResponse(200, { ok: true, outcome: "processed" }, gated.origin);
  } catch {
    logRequest({
      request_id: requestId,
      at: new Date().toISOString(),
      fn,
      ok: false,
      error: "temporary_error",
    });
    return errorResponse(503, "temporary_error", responseOrigin);
  }
  });
}
