// Browser-safe control protocol. Credentials and worker implementations stay on the server/PC.
import sourceCatalog from './sources.json';
export const pcWorkerSchema = 'machimoa-pc-worker-v3';
export const pcWorkerEndpoint = 'http://127.0.0.1:14621';
export const workerCatalog = sourceCatalog;
export const workerSources:Record<string,string> = Object.fromEntries(sourceCatalog.map(row=>[row.id,row.label]));
export const workerCatalogId=sourceCatalog.map(row=>[row.id,row.collector,row.ai].join(':')).join('|');
export type WorkerCommand = { source: string; kind: 'collect' | 'ai'; limit: number | 'all' };
export type WorkerHello = { schema: typeof pcWorkerSchema; instance: string; challenge: string; project: string; catalog: string };
export type WorkerResult = { state: 'running' | 'completed' | 'partial' | 'failed' | 'stopped' | 'unknown' | 'auth_required'; code: string; counts: Record<string, number> };
export type WorkerSourceResult = WorkerResult & {source:string};
export type WorkerRun = WorkerResult & { requestId: string; command: WorkerCommand; sourceResults?:WorkerSourceResult[] };
export type WorkerStatus = { busy: boolean; run: WorkerRun | null };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('invalid_worker_response');
  return value as Record<string, unknown>;
}
export function workerUuid(value: unknown): string { if (typeof value !== 'string' || !uuid.test(value)) throw Error('invalid_worker_input'); return value; }
export function workerCommand(value: unknown): WorkerCommand {
  const v = object(value);
  if (Object.keys(v).sort().join() !== 'kind,limit,source' || typeof v.source !== 'string' || typeof v.kind !== 'string' || !(v.source==='all'||Object.hasOwn(workerSources, v.source)) || !['collect','ai'].includes(v.kind)
    || (v.kind==='ai'&&v.source!=='all')
    || !(v.kind==='ai'&&v.limit==='all')&&(!Number.isInteger(v.limit)||Number(v.limit)<1||Number(v.limit)>(v.kind==='collect'?1:25))) throw Error('invalid_worker_input');
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
  return { busy: v.busy, run: { requestId: workerUuid(r.requestId), command: workerCommand(r.command), ...result, sourceResults } };
}
function workerResult(r:Record<string,unknown>):WorkerResult {
  const counts = object(r.counts);
  if (!['running','completed','partial','failed','stopped','unknown','auth_required'].includes(String(r.state)) || typeof r.code !== 'string' || !/^[a-z0-9_]{0,80}$/.test(r.code)
    || Object.keys(counts).length > 30 || Object.entries(counts).some(([k,n]) => !/^[a-z_]{1,40}$/.test(k) || !Number.isSafeInteger(n) || Number(n) < 0)) throw Error('invalid_worker_response');
  return {state: r.state as WorkerRun['state'], code: r.code, counts: counts as Record<string,number>};
}
