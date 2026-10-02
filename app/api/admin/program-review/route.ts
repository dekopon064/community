import { requireAdmin } from "@/app/lib/auth/admin";
import { programRequest } from "@/app/lib/review/program-handlers";
import { ProgramReviewStore } from "@/app/lib/review/program-store";
import { getReviewRpcClient } from "@/app/lib/review/server";
export async function GET(request: Request) {
  return programRequest(request, null, { authorize: requireAdmin, store: () => new ProgramReviewStore(getReviewRpcClient()) });
}
