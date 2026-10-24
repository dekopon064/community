// Synthetic image bytes + fake DNS/HTTPS/Auth/RPC only. No real endpoints/keys.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { registerHooks, syncBuiltinESMExports } from 'node:module';
import { pathToFileURL } from 'node:url';
import https from 'node:https';
import http from 'node:http';
import dns from 'node:dns/promises';
import net from 'node:net';
import { EventEmitter } from 'node:events';
import { Readable } from 'node:stream';
import ts from 'typescript';
import sharp from 'sharp';
globalThis.fetch=()=>{throw Error('real_network_forbidden')};
https.request=http.request=https.get=http.get=()=>{throw Error('real_http_forbidden')};
dns.lookup=()=>{throw Error('real_dns_forbidden')};
net.Socket.prototype.connect=()=>{throw Error('real_socket_forbidden')};
syncBuiltinESMExports();
const root=path.resolve('.');
registerHooks({
 resolve(specifier,context,next){
  const candidate=specifier.startsWith('@/')?path.join(root,specifier.slice(2)):specifier.startsWith('.')&&context.parentURL?.startsWith('file:')?new URL(specifier,context.parentURL):null;
  if(candidate){const file=typeof candidate==='string'?candidate:decodeURIComponent(candidate.pathname).replace(/^\/(\w:)/,'$1');for(const suffix of ['', '.ts','.tsx'])if(fs.existsSync(file+suffix)&&fs.statSync(file+suffix).isFile())return {url:pathToFileURL(file+suffix).href,shortCircuit:true};}
  return next(specifier,context);
 },
 load(url,context,next){if(/\.tsx?$/.test(url))return {format:'module',source:ts.transpileModule(fs.readFileSync(new URL(url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText,shortCircuit:true};return next(url,context);}
});
const {analyzeHomeImage,sampleTone,imageByteLimit}=await import('../app/lib/home-colors/analysis.ts');
const {imageDownloader,isPublicImageAddress}=await import('../app/lib/home-colors/download.ts');
const {preparePublishedHomeColor}=await import('../app/lib/home-colors/publication.ts');
const {attachHomeCardColors}=await import('../app/lib/home-colors/public-read.ts');
const {reviewDetail}=await import('../app/lib/review/handlers.ts');
const {LocalReviewStore}=await import('../app/lib/review/local-fixture.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
let checks=0;const check=async(name,fn)=>{await fn();checks++;console.log('PASS '+name)};
const png=async(color)=>sharp({create:{width:24,height:24,channels:4,background:color}}).png().toBuffer();
const colors={orange:'#f58c25',yellow:'#eedb28',green:'#26a892',blue:'#3865d8',purple:'#923fe0',red:'#dc3263'};
for(const [tone,color]of Object.entries(colors))await check('real PNG decoder selects '+tone,async()=>assert.equal((await analyzeHomeImage(await png(color))).tone,tone));
for(const format of ['jpeg','webp','gif','avif'])await check(format+' raster decodes without AI or file storage',async()=>assert.equal((await analyzeHomeImage(await sharp(await png(colors.orange)).toFormat(format).toBuffer())).tone,'orange'));
for(const color of ['#ffffff','#000000','#888888',{r:255,g:0,b:0,alpha:0}])await check('neutral / transparent image remains default',async()=>assert.deepEqual(await analyzeHomeImage(await png(color)),{tone:'default',reason:'ambiguous'}));
await check('balanced multiple colors do not force a family',()=>assert.equal(sampleTone(Uint8Array.from([255,0,0,255,0,0,255,255])).tone,'default'));
await check('white margins and black text do not outweigh chromatic poster area',()=>assert.equal(sampleTone(Uint8Array.from([...Array(20).fill([255,255,255,255]).flat(),...Array(10).fill([0,0,0,255]).flat(),...Array(10).fill([255,120,20,255]).flat()])).tone,'orange'));
await check('tiny color marks are not a dominant poster color',()=>assert.equal(sampleTone(Uint8Array.from([...Array(100).fill([255,255,255,255]).flat(),255,0,0,255])).tone,'default'));
const pixels=(...parts)=>Uint8Array.from(parts.flatMap(([count,color])=>Array.from({length:count},()=>color).flat()));
const paleColors={orange:[255,228,217,255],yellow:[255,255,221,255],green:[92,107,97,255],blue:[204,211,248,255],purple:[226,213,238,255],red:[245,217,225,255]};
for(const [tone,color]of Object.entries(paleColors))await check('broad pale '+tone+' is a color, not a neutral margin',async()=>{
 const rgba=pixels([75,color],[15,[255,255,255,255]],[10,[0,0,0,255]]);
 assert.equal(sampleTone(rgba).tone,tone);
 const image=await sharp(Buffer.from(rgba),{raw:{width:10,height:10,channels:4}}).png().toBuffer();
 assert.equal((await analyzeHomeImage(image)).tone,tone);
});
await check('muted background area outweighs a small highly saturated decoration',()=>{
 assert.equal(sampleTone(pixels([75,paleColors.green],[20,[255,255,255,255]],[5,[255,0,0,255]])).tone,'green');
 assert.equal(sampleTone(pixels([70,paleColors.yellow],[20,[0,0,255,255]],[10,[255,120,0,255]])).tone,'yellow');
});
await check('pastel peach background is not replaced by a green illustration',()=>{
 assert.equal(sampleTone(pixels([65,paleColors.orange],[20,[0,140,125,255]],[15,[255,255,255,255]])).tone,'orange');
});
await check('equal or sub-40% families stay ambiguous regardless of saturation',()=>{
 for(const color of [paleColors.blue,[0,0,255,255]])assert.equal(sampleTone(pixels([50,color],[50,[255,0,0,255]])).tone,'default');
 assert.equal(sampleTone(pixels([34,paleColors.yellow],[33,paleColors.green],[33,paleColors.red])).tone,'default');
 assert.equal(sampleTone(pixels([39,paleColors.yellow],[35,paleColors.green],[26,paleColors.red])).tone,'default');
});
await check('exactly 40% qualifies when it is the unique largest chromatic area',()=>{
 assert.equal(sampleTone(pixels([40,paleColors.yellow],[35,paleColors.green],[25,paleColors.red])).tone,'yellow');
});
await check('when two families exceed 40%, the larger area wins without a lead requirement',()=>{
 assert.equal(sampleTone(pixels([47,paleColors.orange],[43,paleColors.red],[10,paleColors.green])).tone,'orange');
 assert.equal(sampleTone(pixels([43,paleColors.orange],[47,paleColors.red],[10,paleColors.green])).tone,'red');
 assert.equal(sampleTone(pixels([501,paleColors.orange],[499,paleColors.red])).tone,'orange');
});
await check('white margins are excluded from the 40% denominator but not the coverage guard',()=>{
 assert.equal(sampleTone(pixels([75,[255,255,255,255]],[12,paleColors.blue],[13,[255,0,0,255]])).tone,'red');
 assert.equal(sampleTone(pixels([93,[255,255,255,255]],[7,[0,0,255,255]])).tone,'default');
 assert.equal(sampleTone(pixels([92,[255,255,255,255]],[8,[0,0,255,255]])).tone,'blue');
});
await check('an exact top tie remains default with white margins and another family',()=>{
 assert.equal(sampleTone(pixels([50,[255,255,255,255]],[22,paleColors.orange],[22,paleColors.red],[6,paleColors.green])).tone,'default');
});
await check('partial-alpha ties are independent of family and pixel order',()=>{
 const rgba=pixels([255,[255,0,0,128]],[128,[0,0,255,255]]);
 assert.equal(sampleTone(rgba).tone,'default');
 assert.equal(sampleTone(pixels([128,[0,0,255,255]],[255,[255,0,0,128]])).tone,'default');
});
await check('close neighbouring red/orange families are not automatically merged',()=>{
 assert.equal(sampleTone(pixels([50,[250,40,50,255]],[50,[255,120,20,255]])).tone,'default');
});
await check('near-white warm paper and gray paper do not become background colors',()=>{
 for(const paper of [[255,253,252,255],[245,245,245,255],[100,100,100,255]]){
  assert.equal(sampleTone(pixels([97,paper],[3,[0,0,255,255]])).tone,'default');
 }
});
await check('transparent pixels cannot invent a background or dilute a visible one',()=>{
 assert.equal(sampleTone(pixels([900,[255,0,0,0]],[100,paleColors.green])).tone,'green');
 assert.equal(sampleTone(pixels([900,[0,0,255,100]],[100,paleColors.yellow])).tone,'yellow');
});
await check('white information sheets retain a strong sparse accent',()=>{
 assert.equal(sampleTone(pixels([75,[255,255,255,255]],[10,[30,65,100,255]],[15,[255,140,0,255]])).tone,'orange');
});
await check('larger portrait and landscape rasters preserve broad pale colors without upscaling',async()=>{
 for(const [width,height]of [[384,512],[512,384],[8,8]]){
  const buffer=await sharp({create:{width,height,channels:4,background:{r:92,g:107,b:97,alpha:1}}}).png().toBuffer();
  assert.equal((await analyzeHomeImage(buffer)).tone,'green');
 }
});
await check('corrupt, empty, excessive, SVG and TIFF input are rejected',async()=>{
 for(const bytes of [Buffer.from('not an image'),Buffer.alloc(0),Buffer.alloc(imageByteLimit+1),Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>'),await sharp(await png('#ff0000')).tiff().toBuffer()])await assert.rejects(()=>analyzeHomeImage(bytes));
});
await check('public-only address validation includes IPv4/IPv6 reserved and mapped ranges',()=>{
 for(const ip of ['127.0.0.1','10.2.3.4','100.64.1.2','169.254.169.254','192.168.1.2','192.0.2.3','198.18.0.1','224.0.0.1','::1','fc00::1','fe80::1','::ffff:8.8.8.8','2001:db8::1','2002:7f00:1::'])assert.equal(isPublicImageAddress(ip),false,ip);
 for(const ip of ['8.8.8.8','1.1.1.1','2606:4700:4700::1111','2001:4860:4860::8888'])assert.equal(isPublicImageAddress(ip),true,ip);
});
const bytes=await png(colors.orange);const url='https://images.example.org/poster.png';
function fakeHttp({status=200,type='image/png',chunks=[bytes],declared,hold=false}={}){
 const calls=[];
 const connect=(options,callback)=>{
  calls.push(options);const req=new EventEmitter();req.end=()=>queueMicrotask(()=>{
   const response=new Readable({read(){if(!hold){for(const chunk of chunks)this.push(chunk);this.push(null)}}});
   response.statusCode=status;response.headers={'content-type':type,...(declared?{'content-length':declared}:{})};callback(response);
   options.signal.addEventListener('abort',()=>{response.destroy();req.emit('error',Error('synthetic abort'))},{once:true});
  });return req;
 };return {connect,calls};
}
await check('one HTTPS GET pins checked IP and preserves TLS hostname/path without credentials',async()=>{
 const h=fakeHttp();const load=imageDownloader(async()=>[{address:'8.8.8.8',family:4}],h.connect);
 assert.deepEqual(Buffer.from(await load(url)),bytes);assert.equal(h.calls.length,1);
 assert.equal(h.calls[0].hostname,'8.8.8.8');assert.equal(h.calls[0].servername,'images.example.org');assert.equal(h.calls[0].agent,false);
 assert.deepEqual(h.calls[0].headers,{Host:'images.example.org',Accept:'image/jpeg,image/png,image/webp,image/gif,image/avif'});
});
await check('private/mixed DNS, unsafe URL and DNS failure never send HTTP',async()=>{
 for(const resolve of [async()=>[{address:'127.0.0.1',family:4}],async()=>[{address:'8.8.8.8',family:4},{address:'10.0.0.1',family:4}],async()=>[],async()=>{throw Error('PRIVATE_DNS_ERROR')}]){
  const h=fakeHttp();await assert.rejects(()=>imageDownloader(resolve,h.connect)(url));assert.equal(h.calls.length,0);
 }
 for(const value of ['http://images.example.org/a.png','https://user:password@images.example.org/a.png','https://images.local/a.png','https://images.example.org/a.svg']){
  const h=fakeHttp();await assert.rejects(()=>imageDownloader(async()=>{throw Error('DNS should not execute')},h.connect)(value));assert.equal(h.calls.length,0);
 }
});
await check('redirect, wrong type, excessive declared/streamed size fail without retry',async()=>{
 for(const options of [{status:302},{status:500},{type:'text/html'},{declared:String(imageByteLimit+1)},{chunks:[Buffer.alloc(imageByteLimit),Buffer.from([1])]}]){
  const h=fakeHttp(options);await assert.rejects(()=>imageDownloader(async()=>[{address:'8.8.8.8',family:4}],h.connect)(url));assert.equal(h.calls.length,1);
 }
});
await check('octet-stream PNG passes by signature, including split signature and MIME parameters',async()=>{
 for(const chunks of [[bytes],[bytes.subarray(0,3),bytes.subarray(3,7),bytes.subarray(7)]]){
  const h=fakeHttp({type:'application/octet-stream; charset=binary',chunks,declared:String(bytes.length)});
  const loaded=await imageDownloader(async()=>[{address:'8.8.8.8',family:4}],h.connect)(url);
  assert.deepEqual(Buffer.from(loaded),bytes);assert.equal((await analyzeHomeImage(loaded)).tone,'orange');assert.equal(h.calls.length,1);
 }
});
await check('octet-stream never admits HTML, SVG, JPEG, empty or truncated signatures',async()=>{
 for(const input of [Buffer.from('<html>no file</html>'),Buffer.from('<svg/>'),await sharp(bytes).jpeg().toBuffer(),Buffer.alloc(0),bytes.subarray(0,7)]){
  const h=fakeHttp({type:'application/octet-stream',chunks:[input]});
  await assert.rejects(()=>imageDownloader(async()=>[{address:'8.8.8.8',family:4}],h.connect)(url),/image_format/);assert.equal(h.calls.length,1);
 }
});
await check('new PNG path retains MIME allowlist, HTTP status and both size limits',async()=>{
 for(const options of [{type:'text/html',chunks:[bytes]},{type:'application/x-octet-stream',chunks:[bytes]},{type:null},
  {type:'application/octet-stream',status:302},{type:'application/octet-stream',status:403},
  {type:'application/octet-stream',declared:String(imageByteLimit+1)},
  {type:'application/octet-stream',declared:'-1'},{type:'application/octet-stream',declared:'2.0'},
  {type:'application/octet-stream',chunks:[bytes,Buffer.alloc(imageByteLimit)]}]){
  const h=fakeHttp(options);await assert.rejects(()=>imageDownloader(async()=>[{address:'8.8.8.8',family:4}],h.connect)(url));assert.equal(h.calls.length,1);
 }
});
await check('PNG signature alone cannot bypass the actual raster decoder',async()=>{
 const h=fakeHttp({type:'application/octet-stream',chunks:[Buffer.concat([bytes.subarray(0,8),Buffer.from('<svg/>')])]});
 const input=await imageDownloader(async()=>[{address:'8.8.8.8',family:4}],h.connect)(url);
 await assert.rejects(()=>analyzeHomeImage(input));
});
await check('stalled DNS stops at the fixed deadline without sending HTTP',async()=>{
 const h=fakeHttp();await assert.rejects(()=>imageDownloader(()=>new Promise(()=>{}),h.connect)(url));assert.equal(h.calls.length,0);
});
await check('stalled HTTP stops at the fixed deadline without a second request',async()=>{
 const h=fakeHttp({hold:true});await assert.rejects(()=>imageDownloader(async()=>[{address:'8.8.8.8',family:4}],h.connect)(url));assert.equal(h.calls.length,1);
});
const actor='00000000-0000-4000-8000-000000000001',id='20000000-0000-4000-8000-000000000001',pub='30000000-0000-4000-8000-000000000001',token='40000000-0000-4000-8000-000000000001';
const published={...(await new LocalReviewStore().get('candidates',id)),status:'published',publishedId:pub};
function fakeRpc({state='pending',claimUnknown=false,finishUnknown=false,finishConflict=false}={}){
 const record={state,tone:'default',url,calls:[]};
 const client={rpc:async(name,args)=>{
  record.calls.push({name,args});
  if(name==='admin_home_color_claim'){
   if(record.state!=='pending')return {data:{state:record.state==='no_image'?'no_image':record.state==='processing'?'processing':'settled'},error:null};
   record.state='processing';if(claimUnknown)throw Error('SECRET_SERVER_MESSAGE');return {data:{state:'claimed',token,url:record.url},error:null};
  }
  if(name==='admin_home_color_finish'){
   assert.equal(args.p_token,token);assert.equal(args.p_actor,actor);
   if(finishConflict)return {data:null,error:{message:'home_color_conflict'}};
   record.state=args.p_state;record.tone=args.p_tone;record.reason=args.p_reason;
   if(finishUnknown)throw Error('SECRET_COMPLETION_MESSAGE');return {data:{state:record.state,tone:record.tone},error:null};
  }
  throw Error('unexpected RPC '+name);
 }};return {record,client};
}
await check('first publish analyzes once; reentry and changed image never reanalyze',async()=>{
 const {record,client}=fakeRpc();let loads=0;const load=async()=>{loads++;return bytes};
 assert.equal(await preparePublishedHomeColor(client,published,actor,load),'completed');assert.equal(record.tone,'orange');
 record.url='https://images.example.org/changed.png';assert.equal(await preparePublishedHomeColor(client,published,actor,load),'unchanged');
 assert.equal(loads,1);assert.equal(record.calls.filter(x=>x.name==='admin_home_color_finish').length,1);
});
for(const source of ['seoul_reservation','myseoul_program','synthetic_future'])await check(source+' uses shared publication color path',async()=>{
 const {client,record}=fakeRpc();assert.equal(await preparePublishedHomeColor(client,{...published,source:{...published.source,name:source}},actor,async()=>bytes),'completed');assert.equal(record.tone,'orange');
});
await check('generic PNG download connects to one fenced completion through shared publication path',async()=>{
 const {client,record}=fakeRpc(),h=fakeHttp({type:'application/octet-stream'});
 assert.equal(await preparePublishedHomeColor(client,published,actor,imageDownloader(async()=>[{address:'8.8.8.8',family:4}],h.connect)),'completed');
 assert.equal(record.tone,'orange');assert.equal(record.calls.length,2);assert.equal(h.calls.length,1);
});
await check('successful neutral analysis is distinguished from failure without changing stored completed state',async()=>{
 const {client,record}=fakeRpc();
 assert.equal(await preparePublishedHomeColor(client,published,actor,async()=>png('#ffffff')),'completed_default');
 assert.equal(record.state,'completed');assert.equal(record.tone,'default');assert.equal(record.reason,'ambiguous');
});
for(const state of ['no_image','processing','completed','failed'])await check(state+' never downloads or finishes again',async()=>{
 const {client,record}=fakeRpc({state});await preparePublishedHomeColor(client,published,actor,async()=>{throw Error('must not download')});assert.equal(record.calls.length,1);
});
await check('new pale-image logic completes only a new pending attempt through the same fenced RPC',async()=>{
 const {client,record}=fakeRpc();let loads=0;
 assert.equal(await preparePublishedHomeColor(client,published,actor,async()=>{loads++;return png({r:92,g:107,b:97,alpha:1});}),'completed');
 assert.equal(record.tone,'green');assert.equal(record.reason,'matched');assert.equal(loads,1);
 assert.deepEqual(record.calls.map(x=>x.name),['admin_home_color_claim','admin_home_color_finish']);
 assert.equal(record.calls[1].args.p_token,token);
});
await check('40% winner reaches one fenced completion and a tied result stores default once',async()=>{
 for(const [rgba,tone,outcome]of [
  [pixels([40,paleColors.yellow],[35,paleColors.green],[25,paleColors.red]),'yellow','completed'],
  [pixels([45,paleColors.orange],[45,paleColors.red],[10,paleColors.green]),'default','completed_default']
 ]){
  const {client,record}=fakeRpc();let loads=0;
  const input=await sharp(Buffer.from(rgba),{raw:{width:10,height:10,channels:4}}).png().toBuffer();
  const load=async()=>{loads++;return input;};
  assert.equal(await preparePublishedHomeColor(client,published,actor,load),outcome);
  assert.equal(record.tone,tone);assert.equal(record.reason,tone==='default'?'ambiguous':'matched');
  assert.equal(await preparePublishedHomeColor(client,published,actor,load),'unchanged');
  assert.equal(loads,1);assert.equal(record.calls.filter(x=>x.name==='admin_home_color_finish').length,1);
 }
});
await check('stored successful and ambiguous results remain immutable after analyzer changes',async()=>{
 for(const [tone,reason]of [['blue','matched'],['default','ambiguous']]){
  const {client,record}=fakeRpc({state:'completed'});record.tone=tone;record.reason=reason;
  const saved={state:record.state,tone:record.tone,reason:record.reason};
  assert.equal(await preparePublishedHomeColor(client,published,actor,async()=>{throw Error('must_not_reanalyze');}),'unchanged');
  assert.deepEqual({state:record.state,tone:record.tone,reason:record.reason},saved);
  assert.deepEqual(record.calls.map(x=>x.name),['admin_home_color_claim']);
 }
});
for(const load of [async()=>{throw Error('SECRET_URL')},async()=>Buffer.from('invalid')])await check('known download/decode failure saves default once',async()=>{
 const {client,record}=fakeRpc();assert.equal(await preparePublishedHomeColor(client,published,actor,load),'failed');
 assert.equal(record.tone,'default');assert.equal(record.reason,'analysis_failed');assert.equal(record.calls.length,2);
});
await check('claim response unknown does not download or force failure',async()=>{
 const {client,record}=fakeRpc({claimUnknown:true});assert.equal(await preparePublishedHomeColor(client,published,actor,async()=>{throw Error('must not load')}),'unavailable');assert.equal(record.state,'processing');assert.equal(record.calls.length,1);
});
await check('finish response unknown is not repeated; a committed result remains intact',async()=>{
 const {client,record}=fakeRpc({finishUnknown:true});let loads=0;
 assert.equal(await preparePublishedHomeColor(client,published,actor,async()=>{loads++;return bytes}),'unavailable');
 assert.equal(await preparePublishedHomeColor(client,published,actor,async()=>{loads++;return bytes}),'unchanged');
 assert.equal(loads,1);assert.equal(record.calls.filter(x=>x.name==='admin_home_color_finish').length,1);assert.equal(record.tone,'orange');
});
await check('stale finish rejection is not retried or overwritten',async()=>{
 const {client,record}=fakeRpc({finishConflict:true});assert.equal(await preparePublishedHomeColor(client,published,actor,async()=>bytes),'unavailable');assert.equal(record.calls.length,2);assert.equal(record.state,'processing');
});
await check('non-published or invalid identity never calls color RPC',async()=>{
 const {client,record}=fakeRpc();for(const item of [{...published,status:'pending'},{...published,publishedId:null},{...published,id:'bad'}])assert.equal(await preparePublishedHomeColor(client,item,actor,async()=>bytes),'unavailable');assert.equal(record.calls.length,0);
});
const item={id:pub,slug:'synthetic',title:'합성',summary:'요약',categoryLabel:'프로그램',period:null,imageUrl:url};
await check('public projection attaches ready colors, holds preparing cards, preserves input and releases fallback',async()=>{
 const input=Object.freeze([Object.freeze(item)]);
 assert.deepEqual(await attachHomeCardColors(input,{rpc:async()=>({data:[{id:pub,tone:'orange',ready:true}],error:null})}),[{...item,tone:'orange'}]);
 assert.deepEqual(await attachHomeCardColors(input,{rpc:async()=>({data:[{id:pub,tone:'default',ready:false}],error:null})}),[]);
 assert.deepEqual(await attachHomeCardColors(input,{rpc:async()=>({data:[{id:pub,tone:'default',ready:true}],error:null})}),[{...item,tone:'default'}]);assert.equal(item.tone,undefined);
});
await check('read failures/malformed tone use default; hidden or absent public rows disappear',async()=>{
 for(const reply of [{data:null,error:{message:'SECRET'}},{data:[{id:pub,tone:'unapproved',ready:true}],error:null},{data:[{id:pub,tone:'red',ready:true},{id:pub,tone:'blue',ready:true}],error:null}])assert.equal((await attachHomeCardColors([item],{rpc:async()=>reply}))[0].tone,'default');
 assert.deepEqual(await attachHomeCardColors([item],{rpc:async()=>({data:[],error:null})}),[]);
});
const origin='http://localhost:3100';
await check('manual projection survives no image, drops stale flags, and exposes no admin metadata',async()=>{
 const noImage={...item,imageUrl:null},client={rpc:async()=>({data:[{id:pub,tone:'red',manual:true,ready:true,actor:'PRIVATE'}],error:null})};
 assert.deepEqual(await attachHomeCardColors([noImage],client),[{...noImage,tone:'red',toneManual:true}]);
 const stale={...noImage,tone:'red',toneManual:true};
 assert.deepEqual(await attachHomeCardColors([stale],{rpc:async()=>({data:null,error:{}})}),[{...noImage,tone:'default'}]);
 assert.deepEqual(await attachHomeCardColors([stale],{rpc:async()=>({data:[{id:pub,tone:'blue',manual:false,ready:true}],error:null})}),[{...noImage,tone:'blue'}]);
});
function request(body,headers={}){return new Request(origin+'/api/admin/review/candidates/'+id,{method:'POST',headers:{origin,'content-type':'application/json',...headers},body:JSON.stringify(body)});}
await check('actual handler: publish -> one color claim/analysis/finish, no facts/candidate edits',async()=>{
 const store=new LocalReviewStore(),before=await store.get('candidates',id),{client,record}=fakeRpc();let publications=0;
 const database={mode:'database',execute:async(kind,cid,command,user)=>{publications++;const result=await store.execute(kind,cid,command,user);return {...result,publishedId:pub};}};
 const response=await reviewDetail(request({action:'publish',revision:before.revision,version:before.version}),'candidates',id,{authorize:async()=>({userId:actor}),store:()=>database,onPublished:(value,user)=>preparePublishedHomeColor(client,value,user,async()=>bytes)});
 const data=await response.json();assert.equal(response.status,200);assert.match(response.headers.get('cache-control'),/private.*no-store/);
 assert.equal(data.homeColor,'completed');assert.equal(publications,1);assert.equal(record.calls.length,2);
 assert.deepEqual(data.item.content,before.content);assert.deepEqual(data.item.source,before.source);assert.equal(data.item.revision,before.revision);assert.equal(data.item.history.at(-1).action,'publish');
});
await check('actual handler: color outage cannot turn confirmed publication into a failed publish',async()=>{
 const store=new LocalReviewStore(),before=await store.get('candidates',id);
 const response=await reviewDetail(request({action:'publish',revision:before.revision,version:before.version}),'candidates',id,{authorize:async()=>({userId:actor}),store:()=>({mode:'database',execute:async(...args)=>({...await store.execute(...args),publishedId:pub})}),onPublished:async()=>{throw Error('SECRET')}});
 const data=await response.json();assert.equal(response.status,200);assert.equal(data.item.status,'published');assert.equal(data.homeColor,'unavailable');assert(!JSON.stringify(data).includes('SECRET'));
});
await check('actual handler: auth/origin/stale publish protections precede image work',async()=>{
 const store=new LocalReviewStore(),before=await store.get('candidates',id);let runs=0;
 const deps={authorize:async()=>({userId:actor}),store:()=>({mode:'database',execute:(...args)=>store.execute(...args)}),onPublished:async()=>{runs++;return 'completed'}};
 const cmd={action:'publish',revision:before.revision,version:before.version};
 assert.equal((await reviewDetail(request(cmd),'candidates',id,{...deps,authorize:async()=>{throw new AdminAccessError('signed_out')}})).status,401);
 assert.equal((await reviewDetail(request(cmd,{origin:'https://evil.invalid'}),'candidates',id,deps)).status,403);
 assert.equal((await reviewDetail(request({...cmd,version:'f'.repeat(64)}),'candidates',id,deps)).status,409);assert.equal(runs,0);
});
await check('actual route is Node-only and calls the shared post-publish path, never a page-view analysis',()=>{
 const route=fs.readFileSync('app/api/admin/review/[kind]/[id]/route.ts','utf8'),page=fs.readFileSync('app/[locale]/page.tsx','utf8');
 assert(route.includes("runtime = 'nodejs'"));assert(route.includes('preparePublishedHomeColor(getReviewRpcClient(), item, actor)'));
 assert(page.includes('attachHomeCardColors(display(selection.featured), supabase)'));assert(!/analyzeHomeImage|preparePublishedHomeColor|downloadHomeImage/.test(page));
});
console.log(JSON.stringify({passed:checks,real_images:0,external_network:0,operational_db:0,ai:0}));
