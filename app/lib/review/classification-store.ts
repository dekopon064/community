import { classificationCommand, classificationDetail, classificationApplyCommand } from './classification';
import { ReviewFailure } from './contracts';
import type { RpcClient } from './database-store';

export class ClassificationStore {
  constructor(private client: RpcClient) {}
  private async invoke(name: string, args: Record<string, unknown>, id: string) {
    try {
      const { data, error } = await this.client.rpc(name,args);
      if (error) throw new ReviewFailure(error.code === 'PT409' ? 'conflict' : error.code === 'PT422' ? 'invalid_input' : error.code === 'PT404' ? 'not_found' : 'unavailable');
      return classificationDetail(data,id);
    } catch(e) { if(e instanceof ReviewFailure) throw e; throw new ReviewFailure('unavailable'); }
  }
  get(id: string) { return this.invoke('admin_review_classification_detail',{p_id:id},id); }
  save(id: string, c: ReturnType<typeof classificationCommand>, actor: string) {
    return this.invoke('admin_review_reclassify',{p_id:id,p_revision:c.revision,p_version:c.version,p_classification_version:c.classificationVersion,p_facts:c.facts,p_filters:c.filters,p_note:c.note,p_actor:actor},id);
  }
  apply(id:string,c:ReturnType<typeof classificationApplyCommand>,actor:string){return this.invoke('admin_review_apply_public_classification',{p_id:id,p_revision:c.revision,p_version:c.version,p_classification_version:c.classificationVersion,p_publication_version:c.publicationVersion,p_content:c.content,p_body_reviewed:c.bodyReviewed,p_note:c.note,p_actor:actor},id);}
}
