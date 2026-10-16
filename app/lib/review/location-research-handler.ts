import { privateResponse } from '../auth/http';
import { isSameOriginPost } from '../auth/urls';
import { ReviewFailure } from './contracts';
import { failure } from './handlers';
import type { FilterDetail, ContentFilterStore } from './content-filter-store';
import { locationIds, locationReport, locationData, locationResearchSchema, proposedLocation } from './location-research';
import type { LocationSnapshot } from './location-research';

export type LocationReview = { id:string; revision:string; version:string; factsVersion:number; source:{name:string;title:string}; facts:{description:string}; status:string; aiStatus:string };
export type LocationDependencies = {
  authorize:()=>Promise<{userId:string}>;
  review:(id:string,source:string)=>Promise<LocationReview>;
  filters:()=>Pick<ContentFilterStore,'get'|'save'>;
  now?:()=>Date;
  allowSynthetic?:boolean;
};
function eligible(d:LocationReview, f:FilterDetail) {
  return d.status==='open' && !['claimed','completed'].includes(d.aiStatus) && f.editable && d.revision===f.revision &&
    f.data.location.status==='unknown' && f.origins.location!=='operator' && Boolean(d.facts.description.trim());
}
function snapshot(d:LocationReview,f:FilterDetail):LocationSnapshot {
  return {id:d.id,source:d.source.name,title:d.source.title,description:d.facts.description,revision:d.revision,
    version:f.version,factsToken:d.version,factsVersion:d.factsVersion,filterVersion:f.filterVersion};
}
async function boundedJson(request:Request) {
  const limit=2*1024*1024;
  if (request.headers.get('content-type')?.split(';')[0].trim()!=='application/json' || Number(request.headers.get('content-length'))>limit) throw new ReviewFailure('invalid_input');
  const reader=request.body?.getReader();if(!reader)throw new ReviewFailure('invalid_input');
  const parts:Uint8Array[]=[];let size=0;
  while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>limit){await reader.cancel();throw new ReviewFailure('invalid_input');}parts.push(value);}
  const bytes=new Uint8Array(size);let offset=0;for(const p of parts){bytes.set(p,offset);offset+=p.length;}
  try{return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{throw new ReviewFailure('invalid_input');}
}
export async function locationResearchRequest(request:Request,deps:LocationDependencies) {
  try {
    const {userId}=await deps.authorize();
    if(request.method!=='POST')throw new ReviewFailure('invalid_input');
    if(!isSameOriginPost(request))return privateResponse(Response.json({code:'wrong_origin'},{status:403}));
    const input=await boundedJson(request);
    if(!input||typeof input!=='object'||Array.isArray(input))throw new ReviewFailure('invalid_input');
    if(input.action==='prepare') {
      if(Object.keys(input).sort().join()!=='action,ids,source' || typeof input.source!=='string' || !/^[a-z_]{1,80}$/.test(input.source))throw new ReviewFailure('invalid_input');
      const ids=locationIds(input.ids),items:LocationSnapshot[]=[],skipped:{id:string;code:string}[]=[];
      for(const id of ids){
        const d=await deps.review(id,input.source),f=await deps.filters().get(id);
        if(d.id!==id||d.source.name!==input.source)throw new ReviewFailure('invalid_input');
        if(!eligible(d,f)){skipped.push({id,code:'not_eligible'});continue;}
        items.push(snapshot(d,f));
      }
      return privateResponse(Response.json({schema:locationResearchSchema,items,skipped}));
    }
    if(input.action!=='apply' || Object.keys(input).sort().join()!=='action,ids,report')throw new ReviewFailure('invalid_input');
    const report=locationReport(input.report),ids=locationIds(input.ids);
    if(report.mode==='synthetic'&&!deps.allowSynthetic)throw new ReviewFailure('invalid_input');
    if(ids.some(id=>!report.items.some(x=>x.snapshot.id===id&&x.status==='suggested')))throw new ReviewFailure('invalid_input');
    // Preserve the frozen report order, never add replacement targets.
    const results:{id:string;status:'saved'|'skipped'|'failed'|'unknown'|'unprocessed';code:string}[]=[];
    let stopped=false;
    for(const proposal of report.items.filter(x=>ids.includes(x.snapshot.id))) {
      const old=proposal.snapshot,id=old.id;
      if(stopped){results.push({id,status:'unprocessed',code:'batch_stopped'});continue;}
      let writing=false;
      try {
        const d=await deps.review(id,old.source),f=await deps.filters().get(id);
        if(d.id!==id||d.source.name!==old.source||!eligible(d,f)||JSON.stringify(snapshot(d,f))!==JSON.stringify(old)){
          results.push({id,status:'skipped',code:'changed_or_not_editable'});continue;
        }
        const data=locationData(f.data,proposal.evidence!);
        writing=true;
        const saved=await deps.filters().save(id,{revision:old.revision,version:old.version,filterVersion:old.filterVersion,fields:['location'],data},userId);
        if(saved.id!==id||saved.revision!==old.revision||saved.filterVersion<=old.filterVersion||JSON.stringify(saved.data.location)!==JSON.stringify(proposedLocation(proposal.evidence!)))throw new ReviewFailure('unavailable');
        results.push({id,status:'saved',code:'saved'});
      } catch(error) {
        const code=error instanceof ReviewFailure?error.code:'unavailable';
        if(['conflict','not_found','already_processed'].includes(code))results.push({id,status:'skipped',code});
        else if(code==='invalid_input')results.push({id,status:'failed',code});
        else {results.push({id,status:writing?'unknown':'failed',code});stopped=true;}
      }
    }
    return privateResponse(Response.json({batchId:report.batchId,at:(deps.now?.()??new Date()).toISOString(),actor:userId,results,stopped}));
  }catch(error){return failure(error);}
}
