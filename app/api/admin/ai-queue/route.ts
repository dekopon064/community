import { requireAdmin } from "@/app/lib/auth/admin";
import { readAiQueue } from "@/app/lib/review/ai-handlers";
import { getAiQueueStore } from "@/app/lib/review/ai-server";
export async function GET(request:Request){return readAiQueue(request,{authorize:requireAdmin,store:getAiQueueStore});}

