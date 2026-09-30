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
    const config = databaseReviewConfig(process.env);
    if (!config) throw new ReviewFailure("not_connected");
    // Separate, request-scoped service client. No cookies, user sessions or SSR client.
    const client = createClient(config.url, config.key, {
      auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
      global: { fetch: (url, options) => fetch(url, { ...options, cache: "no-store", signal: AbortSignal.timeout(15000) }) },
    });
    return new DatabaseReviewStore(client);
  }
  if (localFixtureEnabled(process.env)) {
    fixtureState.machimoaLocalReviewStore ??= new LocalReviewStore();
    return fixtureState.machimoaLocalReviewStore;
  }
  throw new ReviewFailure("not_connected");
}
