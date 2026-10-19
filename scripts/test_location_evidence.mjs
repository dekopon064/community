// Cross-language contract parity; signed fake Auth/RPC integration is exercised
// by test_location_research.mjs. No credentials, network or actual provider.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
http.request=https.request=net.connect=net.createConnection=()=>{throw Error('external network forbidden');};
globalThis.fetch=()=>{throw Error('external network forbidden');};
const require=createRequire(import.meta.url),ts=require('typescript'),root=fileURLToPath(new URL('../',import.meta.url));
const file=path.join(root,'app/lib/review/location-evidence.ts'),out={};
new Function('require','exports',ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)(require,out);
const cases=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','-c',"import json;from test_location_evidence import LINK_CASES;from ingest.location_evidence import source_link,facility_name,source_region_conflict;print(json.dumps([{'case':c,'python':source_link(c[1],c[2],c[3]),'facility':facility_name(c[3]),'regionConflict':source_region_conflict(c[2],c[3],'서울','강동구')} for c in LINK_CASES],ensure_ascii=False))"],{cwd:path.join(root,'scripts'),encoding:'utf8'}));
let checks=0;
for(const row of cases){const [name,title,description,place,expected,role]=row.case;assert.deepEqual(out.sourceLink(title,description,place),[expected,role],name);assert.deepEqual(out.sourceLink(title,description,place),row.python,name);assert.equal(out.facilityName(place),row.facility,name);assert.equal(out.sourceRegionConflict(description,place,'서울','강동구'),row.regionConflict,name);checks+=4;}
assert.equal(out.quoteLink('합성물빛공원 1층 교육실 앞','합성물빛공원\n서울특별시 강동구 합성길','서울','강동구'),true);checks++;
assert.equal(out.quoteLink('다른공원 앞','합성물빛공원\n서울특별시 강동구 합성길','서울','강동구'),false);checks++;
assert.equal(out.sourceRegionConflict('만나는 장소: 서울 종로구 합성물빛공원 앞','합성물빛공원 앞','서울','강동구'),true);checks++;
assert.equal(out.quoteLink('합성역 6번출구','합성역 3,4번 출구 서울특별시 강동구 합성길','서울','강동구'),false);checks++;
assert.equal(out.quoteLink('합성역 3번출구','합성역 3,4번 출구 서울특별시 강동구 합성길','서울','강동구'),true);checks++;
console.log(JSON.stringify({checks,pythonTypeScriptParity:true,externalCalls:0,result:'passed'}));
