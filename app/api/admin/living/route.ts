import { requireAdmin } from '@/app/lib/auth/admin';
import { livingHandler } from '@/app/lib/living/handler';
import { getLivingStore } from '@/app/lib/living/server';
export async function GET(request:Request){return livingHandler(request,{authorize:requireAdmin,store:getLivingStore});}
export async function POST(request:Request){return livingHandler(request,{authorize:requireAdmin,store:getLivingStore});}
