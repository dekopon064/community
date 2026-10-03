import { requireAdmin } from "@/app/lib/auth/admin";
import { myseoulRequest } from "@/app/lib/review/myseoul-handlers";
import { MySeoulReviewStore } from "@/app/lib/review/myseoul-store";
import { getReviewRpcClient } from "@/app/lib/review/server";

type Context = { params: Promise<{ id: string }> };
async function handle(request: Request, context: Context) {
  const { id } = await context.params;
  return myseoulRequest(request, id, { authorize: requireAdmin, store: () => new MySeoulReviewStore(getReviewRpcClient()) });
}
export const GET = handle;
export const POST = handle;
