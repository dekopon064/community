import 'server-only';
import { getReviewRpcClient } from '../review/server';
import { localFixtureEnabled } from '../review/config';
import { ReviewFailure } from '../review/contracts';
import { DatabaseLivingStore,LocalLivingStore,type LivingStore } from './store';
const state=globalThis as typeof globalThis & {machimoaLivingFixture?:LocalLivingStore};
export function getLivingStore():LivingStore {
  if(process.env.MACHIMOA_REVIEW_MODE==='database')return new DatabaseLivingStore(getReviewRpcClient());
  if(localFixtureEnabled(process.env))return state.machimoaLivingFixture??=new LocalLivingStore();
  throw new ReviewFailure('not_connected');
}
