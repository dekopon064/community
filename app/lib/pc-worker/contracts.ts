// Browser-safe control protocol. Credentials and worker implementations stay on the server/PC.
import {failureDetail} from './failure-detail';
import type {FailureDetail} from './failure-detail';
import labels from './failure-labels.json';
import sourceCatalog from './sources.json';
export const pcWorkerSchema = 'machimoa-pc-worker-v3';
export const pcWorkerEndpoint = 'http://127.0.0.1:14621';
export const workerCatalog = sourceCatalog;
export const workerSources:Record<string,string> = Object.fromEntries(sourceCatalog.map(row=>[row.id,row.label]));
export const workerCatalogId=sourceCatalog.map(row=>[row.id,row.collector,row.ai].join(':')).join('|');
export type WorkerCommand = { source: string; kind: 'collect' | 'ai' | 'suitability'; limit: number | 'all' };
export type WorkerHello = { schema: typeof pcWorkerSchema; instance: string; challenge: string; project: string; catalog: string };
export type WorkerResult = { state: 'running' | 'completed' | 'partial' | 'failed' | 'stopped' | 'unknown' | 'auth_required'; code: string; counts: Record<string, number> };
export type WorkerSourceResult = WorkerResult & {source:string};
export type WorkerFailure = {source:string;sourceItemId:string;title?:string;held?:true;response?:{code:keyof typeof labels.response;completedSeen:boolean|null;transport?:keyof typeof labels.transport;httpStatus?:number};sequence:number;terminationConfirmed:boolean;
  flow:'continued'|'last'|'stopped';stopStage:keyof typeof labels.stage|null;detail:FailureDetail};
export type WorkerRun = WorkerResult & { requestId: string; command: WorkerCommand; sourceResults?:WorkerSourceResult[];failures?:WorkerFailure[] };
export type WorkerStatus = { busy: boolean; run: WorkerRun | null };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('invalid_worker_response');
  return value as Record<string, unknown>;
}
export function workerUuid(value: unknown): string { if (typeof value !== 'string' || !uuid.test(value)) throw Error('invalid_worker_input'); return value; }
export function workerCommand(value: unknown): WorkerCommand {
  const v = object(value);
  if (Object.keys(v).sort().join() !== 'kind,limit,source' || typeof v.source !== 'string' || typeof v.kind !== 'string' || !(v.source==='all'||Object.hasOwn(workerSources, v.source)) || !['collect','ai','suitability'].includes(v.kind)
    || (v.kind==='ai'&&v.source!=='all') || (v.kind==='suitability'&&(v.source!=='all'||v.limit!=='all'))
    || !((v.kind==='ai'||v.kind==='suitability')&&v.limit==='all')&&(!Number.isInteger(v.limit)||Number(v.limit)<1||Number(v.limit)>(v.kind==='collect'?1:25))) throw Error('invalid_worker_input');
  return { source: v.source as WorkerCommand['source'], kind: v.kind as WorkerCommand['kind'], limit: v.limit==='all'?'all':Number(v.limit) };
}
export function workerHello(value: unknown): WorkerHello {
  const v = object(value);
  if (v.schema !== pcWorkerSchema || v.catalog!==workerCatalogId || typeof v.project !== 'string' || !/^[a-z0-9]{20}$/.test(v.project)) throw Error('invalid_worker_response');
  return { schema: pcWorkerSchema, instance: workerUuid(v.instance), challenge: workerUuid(v.challenge), project: v.project, catalog:workerCatalogId };
}
export function workerGrantInput(value: unknown) {
  const v = object(value);
  if (Object.keys(v).sort().join() !== 'action,command,hello,requestId' || !['connect','run'].includes(String(v.action))) throw Error('invalid_worker_input');
  if (v.action === 'connect' && v.command !== null) throw Error('invalid_worker_input');
  return { action: v.action as 'connect'|'run', command: v.action === 'run' ? workerCommand(v.command) : null, hello: workerHello(v.hello), requestId: workerUuid(v.requestId) };
}
export function workerStatus(value: unknown): WorkerStatus {
  const v = object(value);
  if (typeof v.busy !== 'boolean') throw Error('invalid_worker_response');
  if (v.run === null) return { busy: v.busy, run: null };
  const r = object(v.run);
  const result=workerResult(r);
  const sources=r.sourceResults??[];
  if(!Array.isArray(sources)||sources.length>sourceCatalog.length)throw Error('invalid_worker_response');
  const seen=new Set<string>();
  const sourceResults=sources.map(value=>{const s=object(value);
    if(typeof s.source!=='string'||!Object.hasOwn(workerSources,s.source)||seen.has(s.source))throw Error('invalid_worker_response');
    seen.add(s.source);return{source:s.source,...workerResult(s)};});
  const command=workerCommand(r.command);
  let failures:WorkerFailure[]|undefined;
  if(r.failures!==undefined){
    if(command.kind!=='ai'||!Array.isArray(r.failures)||r.failures.length>5000)throw Error('invalid_worker_response');
    failures=r.failures.map(raw=>{
      const f=object(raw);
      if(typeof f.source!=='string'||!Object.hasOwn(workerSources,f.source)||typeof f.sourceItemId!=='string'
        || !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(f.sourceItemId)
        || typeof f.sequence!=='number'||!Number.isInteger(f.sequence)||f.sequence<1||f.sequence>5000
        || typeof f.terminationConfirmed!=='boolean'||!['continued','last','stopped'].includes(String(f.flow))
        || f.stopStage!==null && (typeof f.stopStage!=='string'||!Object.hasOwn(labels.stage,f.stopStage))) throw Error('invalid_worker_response');
      if(f.held!==undefined && (f.held!==true || f.terminationConfirmed || !f.response)) throw Error('invalid_worker_response');
      if(f.title!==undefined && (typeof f.title!=='string'||!f.title.length||Array.from(f.title).length>500)) throw Error('invalid_worker_response');
      let response:WorkerFailure['response'];
      if(f.response!==undefined){
        const d=object(f.response);
        if(typeof d.code!=='string'||!Object.hasOwn(labels.response,d.code)||
          !(d.completedSeen===null||typeof d.completedSeen==='boolean')) throw Error('invalid_worker_response');
        if(d.transport!==undefined && (typeof d.transport!=='string'||!Object.hasOwn(labels.transport,d.transport)) ||
          d.httpStatus!==undefined && (typeof d.httpStatus!=='number'||!Number.isInteger(d.httpStatus)||d.httpStatus<100||d.httpStatus>599))
          throw Error('invalid_worker_response');
        response={code:d.code as keyof typeof labels.response,completedSeen:d.completedSeen,
          ...(typeof d.transport==='string'?{transport:d.transport as keyof typeof labels.transport}:{}),
          ...(typeof d.httpStatus==='number'?{httpStatus:d.httpStatus}:{})};
      }
      return {...(f.held===true?{held:true as const}:{}),...(typeof f.title==='string'?{title:f.title}:{}),...(response?{response}:{}),source:f.source,sourceItemId:f.sourceItemId,sequence:f.sequence,terminationConfirmed:f.terminationConfirmed,
        flow:f.flow as WorkerFailure['flow'],stopStage:f.stopStage as WorkerFailure['stopStage'],detail:failureDetail(f.detail)};
    });
  }
  return { busy: v.busy, run: { requestId: workerUuid(r.requestId), command, ...result, sourceResults, ...(failures?{failures}:{}) } };
}
function workerResult(r:Record<string,unknown>):WorkerResult {
  const counts = object(r.counts);
  if (!['running','completed','partial','failed','stopped','unknown','auth_required'].includes(String(r.state)) || typeof r.code !== 'string' || !/^[a-z0-9_]{0,80}$/.test(r.code)
    || Object.keys(counts).length > 30 || Object.entries(counts).some(([k,n]) => !/^[a-z_]{1,40}$/.test(k) || !Number.isSafeInteger(n) || Number(n) < 0)) throw Error('invalid_worker_response');
  return {state: r.state as WorkerRun['state'], code: r.code, counts: counts as Record<string,number>};
}
