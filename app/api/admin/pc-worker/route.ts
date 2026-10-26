import { requireAdmin } from '@/app/lib/auth/admin';
import { databaseReviewConfig } from '@/app/lib/review/database-config';
import { workerGrantRequest } from '@/app/lib/pc-worker/handler';
import { issueWorkerGrant } from '@/app/lib/pc-worker/grants';
export const runtime = 'nodejs';
export async function POST(request:Request) {
  return workerGrantRequest(request,{authorize:requireAdmin,issue:(input,actor,origin)=>{
    const config=databaseReviewConfig(process.env);
    if(!config)throw Error('worker_configuration');
    const project=new URL(config.url).hostname.split('.')[0];
    return issueWorkerGrant(input,actor,origin,{project,key:config.key});
  }});
}
