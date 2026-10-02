import { requireAdmin } from "@/app/lib/auth/admin";
import { programRequest } from "@/app/lib/review/program-handlers";
import { ProgramReviewStore } from "@/app/lib/review/program-store";
import { getReviewRpcClient } from "@/app/lib/review/server";
type Context = { params: Promise<{ id: string }> };
async function handle(request: Request, context: Context) {
  const { id } = await context.params;
  return programRequest(request, id, { authorize: requireAdmin, store: () => new ProgramReviewStore(getReviewRpcClient()) });
}
export const GET = handle;
export const POST = handle;
