// Parses actual isolated PostgreSQL projections, with no database/network client.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e;}}});
const {aiReview,aiReviewView}=await import('../app/lib/review/ai-review.ts');
const {aiSnapshot}=await import('../app/lib/review/ai-queue.ts');
let input='';for await(const chunk of process.stdin)input+=chunk;
const data=JSON.parse(input);let checks=0;
for(const raw of data.details){
 const v=aiReview(raw,raw.jobId);assert.deepEqual(aiReviewView(v,v.jobId),v);checks++;
 assert.equal(JSON.stringify(v).includes('SYNTHETIC_PRIVATE_SENTINEL'),false);checks++;
 assert.ok(v.values.length>0);checks++;
}
for(const raw of data.queues){assert.doesNotThrow(()=>aiSnapshot(raw));checks++;}
console.log(JSON.stringify({checks,networkCalls:0,result:'passed'}));
