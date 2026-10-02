import { requireAdmin } from "@/app/lib/auth/admin";
import { getReviewRpcClient } from "@/app/lib/review/server";
import { trashRequest } from "@/app/lib/review/trash-handlers";
import { TrashStore } from "@/app/lib/review/trash";
const dependencies = { authorize: requireAdmin, store: () => new TrashStore(getReviewRpcClient()) };
export async function GET(request: Request) { return trashRequest(request, dependencies); }
export async function POST(request: Request) { return trashRequest(request, dependencies); }
