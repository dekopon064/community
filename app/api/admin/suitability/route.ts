import {requireAdmin} from '@/app/lib/auth/admin';
import {getReviewRpcClient} from '@/app/lib/review/server';
import {suitabilityRequest} from '@/app/lib/review/suitability';

const dependencies = {authorize:requireAdmin,client:getReviewRpcClient};
export function GET(request:Request) { return suitabilityRequest(request,dependencies); }
export function POST(request:Request) { return suitabilityRequest(request,dependencies); }
