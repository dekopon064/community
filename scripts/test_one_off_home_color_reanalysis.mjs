// Synthetic image bytes and fake SQL only; all actual network fails closed.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {registerHooks,syncBuiltinESMExports} from 'node:module';
import {pathToFileURL,fileURLToPath} from 'node:url';
import https from 'node:https';import http from 'node:http';import net from 'node:net';
import ts from 'typescript';import sharp from 'sharp';
import {runReanalysis,analyzerHash,planSql,reserveSql,finishSql} from './one_off_home_color_reanalysis.mjs';
globalThis.fetch=https.request=https.get=http.request=http.get=net.Socket.prototype.connect=()=>{throw Error('network_forbidden');};syncBuiltinESMExports();
registerHooks({resolve(specifier,context,next){
 if(specifier.startsWith('.')&&context.parentURL?.startsWith('file:')){const file=new URL(specifier,context.parentURL);for(const suffix of ['','.ts']){const p=fileURLToPath(file);if(fs.existsSync(p+suffix)&&fs.statSync(p+suffix).isFile())return{url:pathToFileURL(p+suffix).href,shortCircuit:true};}}
 return next(specifier,context);
},load(url,context,next){if(url.endsWith('.ts'))return{format:'module',source:ts.transpileModule(fs.readFileSync(new URL(url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText,shortCircuit:true};return next(url,context);}});
const {analyzeHomeImage}=await import('../app/lib/home-colors/analysis.ts');
let n=0;const eq=(a,b)=>{assert.deepEqual(a,b);n++;};const rejects=async f=>{await assert.rejects(f);n++;};
const id='00000000-0000-4000-8000-000000000001',actor='00000000-0000-4000-8000-000000000002';
const row={id,candidate_id:id,revision:'a'.repeat(64),public_hash:'b'.repeat(64),candidate_hash:'c'.repeat(64),analysis_hash:'d'.repeat(64),version:'e'.repeat(64),image_url:'https://images.example.org/synthetic.png',eligibility:'eligible'};
const codeHash=await analyzerHash(),image=await sharp({create:{width:80,height:80,channels:4,background:'#ffe4d9'}}).png().toBuffer();
let writes=0,loads=0;const sql=async query=>{writes++;return{status:query.includes('insert into')?'reserved':'completed',tone:'orange'};};
const config={rows:[row],actor,sql,loadImage:async()=>{loads++;return image;},analyze:analyzeHomeImage,codeHash,confirmedCodeHash:codeHash};
eq(await runReanalysis(config),[{id,status:'eligible'}]);eq(writes,0);eq(loads,0);
eq(await runReanalysis({...config,execute:true}),[{id,status:'completed',tone:'orange'}]);eq(writes,2);eq(loads,1);
for(const eligibility of ['manual','already_attempted','ineligible']){const before=writes;eq(await runReanalysis({...config,execute:true,rows:[{...row,eligibility}]}),[{id,status:eligibility}]);eq(writes,before);}
for(const status of ['changed','already_attempted']){let images=0,calls=0;eq(await runReanalysis({...config,execute:true,sql:async()=>{calls++;return{status};},loadImage:async()=>{images++;}}),[{id,status}]);eq(calls,1);eq(images,0);}
for(const errorAt of ['reserve','finish']){
 let calls=0,images=0;await rejects(()=>runReanalysis({...config,execute:true,sql:async()=>{calls++;if(calls===(errorAt==='reserve'?1:2))throw Error('SECRET_do_not_surface');return{status:'reserved'};},loadImage:async()=>{images++;return image;}}));eq(calls,errorAt==='reserve'?1:2);eq(images,errorAt==='reserve'?0:1);
}
for(const status of ['unconfirmed','unexpected']){let calls=0;await rejects(()=>runReanalysis({...config,execute:true,sql:async()=>{calls++;return{status};}}));eq(calls,1);}
let queries=[];eq(await runReanalysis({...config,execute:true,loadImage:async()=>{throw Error('signed_image_secret');},sql:async q=>{queries.push(q);return{status:q.includes('insert into')?'reserved':'failed',tone:'default'};}}),[{id,status:'failed',tone:'default'}]);eq(queries.length,2);eq(queries[1].includes('signed_image_secret'),false);eq(queries[1].includes('analysis_failed'),true);
await rejects(()=>runReanalysis({...config,execute:true,confirmedCodeHash:'f'.repeat(64)}));
await rejects(()=>runReanalysis({...config,execute:true,rows:[row,row]}));await rejects(()=>runReanalysis({...config,limit:0}));await rejects(()=>runReanalysis({...config,rows:[row],limit:0}));
await rejects(()=>runReanalysis({...config,execute:true,actor:'not-a-uuid'}));
for(const limit of [0,-1,501,1.1]){assert.throws(()=>planSql(limit));n++;}
eq(planSql(2).includes('limit 3'),true);
assert.throws(()=>reserveSql({...row,public_hash:'injection'},actor,id,codeHash));n++;
assert.throws(()=>finishSql(row,actor,id,{state:'failed',tone:'red',reason:'analysis_failed'}));n++;
// Confirmed failure continues once; unknown completion never starts the next item.
const second={...row,id:'00000000-0000-4000-8000-000000000003'};let calls=0;
eq((await runReanalysis({...config,execute:true,rows:[row,second],loadImage:async()=>{throw Error('synthetic');},sql:async q=>{calls++;return{status:q.includes('insert into')?'reserved':'failed'};}})).map(r=>r.status),['failed','failed']);eq(calls,4);
calls=0;await rejects(()=>runReanalysis({...config,execute:true,rows:[row,second],sql:async()=>{calls++;return{status:calls===1?'reserved':'unconfirmed'};}}));eq(calls,2);
console.log(JSON.stringify({passed:n,real_network:0,real_db:0,ai:0,images:'synthetic PNG with production analyzer'}));
