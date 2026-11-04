import { requireAdmin } from '@/app/lib/auth/admin';
import { getReviewRpcClient } from '@/app/lib/review/server';
import { seoulCorrectionRequest } from '@/app/lib/review/seoul-correction-handler';

async function handle(request: Request, context: { params: Promise<{ id: string }> }) {
  return seoulCorrectionRequest(request, (await context.params).id, {
    authorize: requireAdmin,
    invoke: async (name, args) => {
      const { data, error } = await getReviewRpcClient().rpc(name, args);
      if (error) throw Object.assign(new Error(), { code: error.code });
      return data;
    },
  });
}

export const GET = handle;
export const POST = handle;

