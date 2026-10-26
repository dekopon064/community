import { pcWorkerEndpoint, workerHello, workerStatus, workerCommand } from './contracts';
import type { WorkerHello, WorkerRun, WorkerStatus, WorkerCommand } from './contracts';

export type PcWorkerView = { connection:'off'|'connecting'|'ready'; sending:boolean; busy:boolean; unknown:boolean; run:WorkerRun|null; error:string };
class HttpFailure extends Error { constructor(readonly status:number,readonly code:string){super(code);} }
export class PcWorkerClient {
  private connection:{hello:WorkerHello;token:string}|null=null;
  private pending:{requestId:string;command:WorkerCommand;instance:string}|null=null;
  private generation=0;
  private inFlight=false;
  private state:PcWorkerView={connection:'off',sending:false,busy:false,unknown:false,run:null,error:''};
  constructor(private readonly changed:(state:PcWorkerView)=>void,private readonly fetcher:typeof fetch=(input,init)=>fetch(input,init),
    private readonly uuid:()=>string=()=>crypto.randomUUID()){}
  private emit(patch:Partial<PcWorkerView>){this.state={...this.state,...patch};this.changed({...this.state});}
  private async request(url:string,body?:unknown,token?:string){
    const response=await this.fetcher(url,{method:body===undefined?'GET':'POST',cache:'no-store',
      credentials:url.startsWith('/')?'same-origin':'omit',signal:AbortSignal.timeout(5000),
      headers:{...(body===undefined?{}:{'Content-Type':'application/json'}),...(token?{Authorization:`Bearer ${token}`}:{})},
      ...(body===undefined?{}:{body:JSON.stringify(body)})});
    const data=await response.json();
    if(!response.ok)throw new HttpFailure(response.status,typeof data?.code==='string'?data.code:'worker_unavailable');
    return data;
  }
  private async grant(action:'connect'|'run',hello:WorkerHello,requestId:string,command:WorkerCommand|null){
    const data=await this.request('/api/admin/pc-worker',{action,hello,requestId,command});
    if(typeof data?.ticket!=='string'||data.ticket.length>8192)throw Error('invalid_worker_response');
    return data.ticket as string;
  }
  async connect(){
    if(this.inFlight)return;this.inFlight=true;const generation=++this.generation;
    this.emit({connection:'connecting',sending:true,error:''});
    try{
      const hello=workerHello(await this.request(`${pcWorkerEndpoint}/hello`));
      const ticket=await this.grant('connect',hello,this.uuid(),null);
      const data=await this.request(`${pcWorkerEndpoint}/connect`,{ticket});
      if(typeof data?.token!=='string'||!/^[A-Za-z0-9_-]{32,128}$/.test(data.token)||data.instance!==hello.instance)throw Error('invalid_worker_response');
      if(generation!==this.generation)return;
      this.connection={hello,token:data.token};
      this.emit({connection:'ready'});
      const status=workerStatus(await this.request(this.statusUrl(),undefined,data.token));
      if(generation===this.generation)this.accept(status);
    }catch(error){if(generation===this.generation){this.connection=null;this.emit({connection:'off',error:this.errorCode(error),unknown:this.state.unknown||!!this.pending});}}
    finally{if(generation===this.generation){this.inFlight=false;this.emit({sending:false});}}
  }
  private errorCode(error:unknown){
    return error instanceof HttpFailure && ['signed_out','forbidden','wrong_origin','worker_busy','connection_expired','invalid_capability'].includes(error.code)?error.code:'worker_unavailable';
  }
  private accept(status:WorkerStatus){
    if(this.pending){
      if(status.run?.requestId!==this.pending.requestId||status.run.command.source!==this.pending.command.source
        ||status.run.command.kind!==this.pending.command.kind||status.run.command.limit!==this.pending.command.limit
        ||this.pending.instance!==this.connection?.hello.instance){this.emit({busy:status.busy,unknown:true,error:'result_unknown'});return;}
      if(!['running','unknown'].includes(status.run.state))this.pending=null;
    }
    const unknown=status.run?.state==='unknown';
    this.emit({busy:status.busy,run:status.run,unknown,error:unknown?'result_unknown':''});
  }
  private statusUrl(){return `${pcWorkerEndpoint}/status${this.pending?'?requestId='+this.pending.requestId:''}`;}
  async refresh(){
    if(!this.connection||this.inFlight)return;this.inFlight=true;const generation=this.generation;
    try{const status=workerStatus(await this.request(this.statusUrl(),undefined,this.connection.token));if(generation===this.generation)this.accept(status);}
    catch(error){if(generation===this.generation)this.emit({error:this.errorCode(error),unknown:this.state.unknown||this.state.run?.state==='running'||!!this.pending});}
    finally{if(generation===this.generation)this.inFlight=false;}
  }
  async run(raw:WorkerCommand){
    if(!this.connection||this.inFlight||this.state.busy||this.state.unknown)return;
    const command=workerCommand(raw),connection=this.connection,generation=this.generation;
    const requestId=this.uuid();let sent=false;this.inFlight=true;this.emit({sending:true,error:''});
    try{
      const ticket=await this.grant('run',connection.hello,requestId,command);
      if(generation!==this.generation)return;
      this.pending={requestId,command,instance:connection.hello.instance};sent=true;
      const status=workerStatus(await this.request(`${pcWorkerEndpoint}/run`,{ticket},connection.token));
      if(generation===this.generation)this.accept(status);
    }catch(error){if(generation===this.generation){
      const denied=error instanceof HttpFailure&&[401,403,409,422].includes(error.status);
      if(denied)this.pending=null;
      this.emit({unknown:sent&&!denied,error:sent&&!denied?'result_unknown':this.errorCode(error)});
    }}finally{if(generation===this.generation){this.inFlight=false;this.emit({sending:false});}}
  }
  dispose(){this.generation++;this.inFlight=false;this.connection=null;}
}
