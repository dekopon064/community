import { requireAdmin } from "@/app/lib/auth/admin";
import { listReviews } from "@/app/lib/review/handlers";
import { getReviewStore } from "@/app/lib/review/server";

export async function GET(request: Request) {
  return listReviews(request, { authorize: requireAdmin, store: getReviewStore });
}
