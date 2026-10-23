import { requireAdmin } from "@/app/lib/auth/admin";
import { reviewDetail } from "@/app/lib/review/handlers";
import { getReviewStore, getReviewRpcClient } from "@/app/lib/review/server";
import { preparePublishedHomeColor } from '@/app/lib/home-colors/publication';

export const runtime = 'nodejs';

type Context = { params: Promise<{ kind: string; id: string }> };
async function handle(request: Request, context: Context) {
  const { kind, id } = await context.params;
  return reviewDetail(request, kind, id, { authorize: requireAdmin, store: getReviewStore,
    onPublished: (item, actor) => preparePublishedHomeColor(getReviewRpcClient(), item, actor) });
}
export const GET = handle;
export const POST = handle;
