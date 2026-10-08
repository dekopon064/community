import type { SupabaseClient } from "@supabase/supabase-js";
import { isUuid } from "./intent";

// Anonymous aggregate only. Never create a session client or return personal rows.
export async function savedCountRequest(request: Request, factory: () => SupabaseClient | null) {
  const reply = (body: object, status = 200) => Response.json(body, {
    status, headers: { "Cache-Control": "no-store, max-age=0" },
  });
  if (request.method !== "GET") return reply({ error: "method_not_allowed" }, 405);
  const url = new URL(request.url), id = url.searchParams.get("id");
  if (!isUuid(id) || url.searchParams.getAll("id").length !== 1 || [...url.searchParams.keys()].some(key => key !== "id")) {
    return reply({ error: "invalid_request" }, 400);
  }
  try {
    const canonicalId = id.toLowerCase();
    const client = factory();
    if (!client) return reply({ error: "unavailable" }, 503);
    const { data, error } = await client.rpc("saved_information_count", { p_curation_id: canonicalId });
    if (error) return reply({ error: error.code === "PT404" ? "information_unavailable" : "unavailable" }, error.code === "PT404" ? 404 : 503);
    if (data?.id !== canonicalId || !Number.isSafeInteger(data.savedCount) || data.savedCount < 0) return reply({ error: "unavailable" }, 503);
    return reply({ id: canonicalId, savedCount: data.savedCount });
  } catch { return reply({ error: "unavailable" }, 503); }
}
