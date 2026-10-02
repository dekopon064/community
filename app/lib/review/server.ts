import "server-only";
import { ReviewFailure } from "./contracts";
import type { ReviewStore } from "./contracts";
import { LocalReviewStore } from "./local-fixture";
import { localFixtureEnabled } from "./config";
import { databaseReviewConfig } from "./database-config";
import { DatabaseReviewStore } from "./database-store";
import { createClient } from "@supabase/supabase-js";

// Shared only between local development route bundles; never session/identity state.
const fixtureState = globalThis as typeof globalThis & { machimoaLocalReviewStore?: LocalReviewStore };
export function getReviewStore(): ReviewStore {
  if (process.env.MACHIMOA_REVIEW_MODE === "database") {
    return new DatabaseReviewStore(getReviewRpcClient());
  }
  if (localFixtureEnabled(process.env)) {
    fixtureState.machimoaLocalReviewStore ??= new LocalReviewStore();
    return fixtureState.machimoaLocalReviewStore;
  }
  throw new ReviewFailure("not_connected");
}

// Called only after request-level requireAdmin(); never shares a cookie session.
export function getReviewRpcClient() {
  const config = databaseReviewConfig(process.env);
  if (!config) throw new ReviewFailure("not_connected");
  return createClient(config.url, config.key, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
    global: { fetch: (url, options) => fetch(url, { ...options, cache: "no-store", signal: AbortSignal.timeout(15000) }) },
  });
}
