import "server-only";
import { getReviewRpcClient } from "./server";
import { localFixtureEnabled } from "./config";
import { ReviewFailure } from "./contracts";
import { DatabaseAiQueueStore } from "./ai-queue";
import type { AiQueueStore } from "./ai-queue";
export function getAiQueueStore():AiQueueStore{
 if(process.env.MACHIMOA_REVIEW_MODE==="database")return new DatabaseAiQueueStore(getReviewRpcClient());
 if(localFixtureEnabled(process.env))return {mode:"local-fixture",async read(){return {checkedAt:new Date().toISOString(),items:[],observed:[],hasMore:false};}};
 throw new ReviewFailure("not_connected");
}

