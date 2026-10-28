import 'server-only';
import { createClient } from '@supabase/supabase-js';
import { databaseReviewConfig } from '../review/database-config';
import { ReviewFailure } from '../review/contracts';
import { DatabaseLivingImageStore,type LivingImageStore } from './image-store';

// Public media gateway, separate from the requireAdmin-only RPC client.
// Its SQL readers require a current published row. No mutation capability is exposed.
export function getPublicLivingImageStore():LivingImageStore {
  const config=databaseReviewConfig(process.env);if(!config)throw new ReviewFailure('not_connected');
  const client=createClient(config.url,config.key,{auth:{persistSession:false,autoRefreshToken:false,detectSessionInUrl:false},
    global:{fetch:(url,options)=>fetch(url,{...options,cache:'no-store',signal:AbortSignal.timeout(15000)})}});
  const store=new DatabaseLivingImageStore(client);
  const forbidden=async()=>{throw new ReviewFailure('invalid_input');};
  return {begin:forbidden,finish:forbidden,put:forbidden,read:id=>store.read(id,false),gallery:id=>store.gallery(id),download:path=>store.download(path)};
}
