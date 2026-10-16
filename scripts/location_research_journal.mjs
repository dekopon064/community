// Local research evidence only. No SDK objects, auth storage or HTTP metadata.
export class ResearchRecordError extends Error {
  constructor(){super('research_record_error');this.code='research_record_error';}
}
export function redactResearch(value,depth=0){
  if(depth>30)throw new ResearchRecordError();
  if(value===null||typeof value==='boolean'||typeof value==='number')return value;
  if(typeof value==='string'){
    if(value.length>600000)throw new ResearchRecordError();
    return value.replace(/Bearer\s+[^\s"'<>]+/gi,'Bearer [REDACTED]')
      .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b|\bsk-[A-Za-z0-9_-]+/g,'[REDACTED]')
      .replace(/((?:access[_-]?token|refresh[_-]?token|id[_-]?token|api[_-]?key|client[_-]?secret|authorization|password|cookie|token|secret|code)["']?\s*[:=]\s*["']?)[^\s"'&,;}<>]+/gi,'$1[REDACTED]');
  }
  if(Array.isArray(value)){if(value.length>10000)throw new ResearchRecordError();return value.map(x=>redactResearch(x,depth+1));}
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,v])=>[key,
    /^(access[_-]?token|refresh[_-]?token|id[_-]?token|api[_-]?key|client[_-]?secret|authorization|password|cookies?|headers?|token|secret)$/i.test(key)?'[REDACTED]':redactResearch(v,depth+1)]));
  throw new ResearchRecordError();
}
export function researchJournal(file){
  let broken=false,sequence=0;
  return async event=>{
    if(broken)throw new ResearchRecordError();
    try{
      const line=JSON.stringify(redactResearch({sequence:++sequence,at:new Date().toISOString(),...event}))+'\n';
      if(Buffer.byteLength(line)>3*1024*1024)throw new ResearchRecordError();
      await file.writeFile(line);await file.sync();
    }catch{broken=true;throw new ResearchRecordError();}
  };
}
