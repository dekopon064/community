import { requireAdmin } from '@/app/lib/auth/admin';
import { getReviewRpcClient } from '@/app/lib/review/server';
import { FeaturedStore } from '@/app/lib/home-featured/admin';
import { featuredRequest } from '@/app/lib/home-featured/admin-handler';

async function handle(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  return featuredRequest(request, id, { authorize: requireAdmin, store: () => new FeaturedStore(getReviewRpcClient()) });
}
export const GET = handle;
export const POST = handle;
