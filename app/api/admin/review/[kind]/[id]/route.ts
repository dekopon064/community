import { requireAdmin } from "@/app/lib/auth/admin";
import { reviewDetail } from "@/app/lib/review/handlers";
import { getReviewStore } from "@/app/lib/review/server";

type Context = { params: Promise<{ kind: string; id: string }> };
async function handle(request: Request, context: Context) {
  const { kind, id } = await context.params;
  return reviewDetail(request, kind, id, { authorize: requireAdmin, store: getReviewStore });
}
export const GET = handle;
export const POST = handle;
