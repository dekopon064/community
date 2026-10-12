import "server-only";
import { getReviewRpcClient } from "./server";
import { localFixtureEnabled } from "./config";
import { ReviewFailure } from "./contracts";
import { DatabaseAiQueueStore } from "./ai-queue";
import type { AiQueueStore } from "./ai-queue";
import { DatabaseAiReviewStore } from './ai-review';
import type { AiReviewStore } from './ai-review';
import { LocalAiReviewStore } from './ai-review-fixture';
const fixtureState=globalThis as typeof globalThis & {machimoaLocalAiReviewStore?:LocalAiReviewStore};
function fixture(){return fixtureState.machimoaLocalAiReviewStore??=new LocalAiReviewStore();}
export function getAiQueueStore():AiQueueStore{
 if(process.env.MACHIMOA_REVIEW_MODE==="database")return new DatabaseAiQueueStore(getReviewRpcClient());
 if(localFixtureEnabled(process.env))return fixture();
 throw new ReviewFailure("not_connected");
}
export function getAiReviewStore():AiReviewStore{
 if(process.env.MACHIMOA_REVIEW_MODE==='database')return new DatabaseAiReviewStore(getReviewRpcClient());
 if(localFixtureEnabled(process.env))return fixture();
 throw new ReviewFailure('not_connected');
}

