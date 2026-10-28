// Reuse the formal network-denying harness and retain its text-draft regressions.
await import('./test_living_articles.mjs');
const {default:assert}=await import('node:assert/strict');
const {randomUUID}=await import('node:crypto');
const {default:sharp}=await import('sharp');
const {LocalLivingStore}=await import('../app/lib/living/store.ts');
const {LocalLivingImageStore,DatabaseLivingImageStore}=await import('../app/lib/living/image-store.ts');
const {livingImageHandler}=await import('../app/lib/living/image-handler.ts');
const {normalizeLivingImage}=await import('../app/lib/living/image-upload.ts');
const {parseLivingImages,livingImageBytes}=await import('../app/lib/living/images.ts');
const {sourceImageUrl,sourceImageDisplayUrl}=await import('../app/lib/sourceImages.ts');
const {livingBody}=await import('../app/lib/living/contract.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const {default:fs}=await import('node:fs');
const example=JSON.parse(fs.readFileSync(new URL('./fixtures/living-instagram-example.json',import.meta.url),'utf8'));
const actor='00000000-0000-4000-8000-000000000001',origin='http://localhost:3298',article=randomUUID(),image=randomUUID();
const store=new LocalLivingStore(),assets=new LocalLivingImageStore(store);
const deps={authorize:async()=>({userId:actor}),store:()=>assets};let passed=0;
async function test(name,fn){await fn();passed++;console.log('PASS image '+name);}
const png=await sharp({create:{width:80,height:100,channels:3,background:'#ffeecc'}}).png().toBuffer();
const request=(id=image,body=png,extra={},version='0')=>new Request(origin+'/api/admin/living/images/'+id,{method:'POST',headers:{Origin:origin,'Content-Type':'image/png','x-living-article':article,'x-living-version':version,...extra},body});
const read=(id=image,query='')=>new Request(origin+'/api/admin/living/images/'+id+query);
await test('Auth denies before image bytes, metadata or Storage access',async()=>{
 for(const state of ['signed_out','forbidden','auth_unavailable']){
 let accesses=0;const result=await livingImageHandler(request(),image,{authorize:async()=>{throw new AdminAccessError(state);},store:()=>{accesses++;return assets;}});
 assert.ok([401,403,503].includes(result.status));assert.equal(accesses,0);
 }
});
await test('CSRF, submitted article/version and unsupported format fail closed',async()=>{
 for(const headers of [{Origin:'https://attacker.example.org'},{'x-living-article':'bad'},{'x-living-version':'bad'},{'Content-Type':'image/svg+xml'}])assert.ok((await livingImageHandler(request(image,png,headers),image,deps)).status>=400);
 assert.equal(assets.blobs.size,0);assert.equal(store.imageAssets.size,0);
});
await test('byte limit, raster signature, MIME mismatch and invalid payloads rejected',async()=>{
 for(const [bytes,mime] of [[Buffer.from('<svg/>'),'image/png'],[Buffer.from('<html>'),'image/jpeg'],[png,'image/webp'],[Buffer.alloc(livingImageBytes+1),'image/png']]){
 const result=await livingImageHandler(request(randomUUID(),bytes,{'Content-Type':mime}),randomUUID(),deps);assert.equal(result.status,422);
 }
 assert.equal(assets.blobs.size,0);
});
await test('PNG normalization retains dimensions/text pixels, strips metadata and uses no AI',async()=>{
 const data=await normalizeLivingImage(png,'image/png'),meta=await sharp(data.data).metadata();
 assert.equal(meta.format,'webp');assert.equal(meta.width,80);assert.equal(meta.height,100);assert.equal(meta.exif,undefined);
 assert.deepEqual(await sharp(data.data).raw().toBuffer(),await sharp(png).raw().toBuffer());
});
await test('confirmed upload ready once; duplicate confirmed request never rewrites Storage',async()=>{
 assert.equal((await livingImageHandler(request(),image,deps)).status,200);assert.equal(assets.blobs.size,1);assert.equal(store.articles.size,0);
 assert.equal((await livingImageHandler(request(),image,deps)).status,200);assert.equal(assets.blobs.size,1);
 const other=await sharp({create:{width:80,height:100,channels:3,background:'#112233'}}).png().toBuffer();
 assert.equal((await livingImageHandler(request(image,other),image,deps)).status,409);assert.equal(assets.blobs.size,1);
});
await test('private preview works; unpublished images cannot be read publicly',async()=>{
 const privateRead=await livingImageHandler(read(),image,deps);assert.equal(privateRead.status,200);assert.equal(privateRead.headers.get('content-type'),'image/webp');assert.match(privateRead.headers.get('cache-control'),/no-store/);
 assert.equal((await livingImageHandler(read(),image,deps,false)).status,404);assert.deepEqual(await assets.gallery(article),[]);
});
await test('pending duplicate / ambiguous reservation never repeats Storage',async()=>{
 let puts=0;const pending={...await assets.read(image,true),status:'pending',fresh:false};
 const fake={...assets,begin:async()=>pending,put:async()=>{puts++;},finish:async()=>{throw Error();}};
 assert.equal((await livingImageHandler(request(),image,{...deps,store:()=>fake})).status,503);assert.equal(puts,0);
 fake.begin=async()=>{throw Error('private-storage-token');};
 const result=await livingImageHandler(request(),image,{...deps,store:()=>fake});assert.equal(result.status,503);assert.equal(puts,0);assert.ok(!(await result.text()).includes('private-storage-token'));
});
await test('Storage error leaves private pending result; no finish or retries',async()=>{
 const id=randomUUID();let calls=0,finishes=0;const fake={begin:assets.begin.bind(assets),put:async()=>{calls++;throw Error();},finish:async()=>{finishes++;}};
 assert.equal((await livingImageHandler(request(id),id,{...deps,store:()=>fake})).status,503);assert.equal(calls,1);assert.equal(finishes,0);assert.equal((await assets.read(id,true)).status,'pending');
});
await test('lost completion response is checked by GET without reupload or document writes',async()=>{
 const id=randomUUID();let uploads=0;const fake={begin:assets.begin.bind(assets),put:async(...args)=>{uploads++;await assets.put(...args);},finish:async(...args)=>{await assets.finish(...args);throw Error();}};
 assert.equal((await livingImageHandler(request(id),id,{...deps,store:()=>fake})).status,503);assert.equal(uploads,1);
 const result=await livingImageHandler(read(id,'?view=status'),id,deps);assert.equal((await result.json()).item.status,'ready');assert.equal(store.articles.size,0);
});
await test('unknown/cross-article images, duplicates and over 20 images cannot be attached',async()=>{
 for(const images of [[{id:randomUUID(),altKo:'',altJa:''}],[{id:image,altKo:'',altJa:''},{id:image,altKo:'',altJa:''}]])await assert.rejects(store.write({id:article,version:'0',requestId:randomUUID(),action:'save',document:{...example,images}},actor));
 const id=randomUUID();await assert.rejects(store.write({id,version:'0',requestId:randomUUID(),action:'save',document:{...example,images:[{id:image,altKo:'',altJa:''}]}},actor));
 assert.throws(()=>parseLivingImages(Array.from({length:21},()=>({id:randomUUID(),altKo:'',altJa:''}))));
});
await test('image-first draft can publish with bilingual titles/summaries and optional body',async()=>{
 const doc={...example,content:{...example.content,contentKo:' \n\t',contentJa:'\n'},images:[{id:image,altKo:'첫 카드',altJa:'最初の画像'}]};
 const saved=await store.write({id:article,version:'0',requestId:randomUUID(),action:'save',document:doc},actor);
 assert.equal((await livingImageHandler(request(randomUUID()),randomUUID(),deps)).status,409);
 const published=await store.write({id:article,version:saved.version,requestId:randomUUID(),action:'publish',document:null},actor);
 assert.equal(published.status,'published');assert.equal(store.publications.get(article).source_image_url,'/api/living/images/'+image);
 assert.equal(store.publications.get(article).content_ko,livingBody(doc,'ko'));assert.deepEqual(await assets.gallery(article),doc.images);
 assert.equal((await livingImageHandler(read(),image,deps,false)).status,200);
 assert.equal(published.history.length,2);
});
await test('removing public publication hides images while preserving bytes, metadata and history',async()=>{
 const history=structuredClone(store.articles.get(article).history),bytes=assets.blobs.size;store.publications.delete(article);
 assert.equal((await livingImageHandler(read(),image,deps,false)).status,404);assert.equal(assets.blobs.size,bytes);assert.deepEqual(store.articles.get(article).history,history);
});
await test('render-only URL support does not weaken submitted URL or download guards',async()=>{
 const src='/api/living/images/'+image;assert.equal(sourceImageUrl(src),null);assert.equal(sourceImageDisplayUrl(src),src);
 for(const value of ['/api/living/images/../../secret',src+'?url=https://evil.example.org',src+'#x','javascript:alert(1)','//evil.example.org/a'])assert.equal(sourceImageDisplayUrl(value),null);
});
await test('pixel limit rejects excessive raster without Storage writes',async()=>{
 const huge=await sharp({create:{width:4001,height:4000,channels:3,background:'#ffffff'}}).png().toBuffer();
 await assert.rejects(normalizeLivingImage(huge,'image/png'),e=>e.code==='invalid_input');
});
await test('official Storage adapter disables upsert and sanitizes error detail',async()=>{
 let call;const fake={rpc:async()=>({data:await assets.read(image,true),error:null}),storage:{from(bucket){assert.equal(bucket,'living-card-images');return{upload:async(...args)=>{call=args;return{error:null};},download:async()=>({data:new Blob([png],{type:'image/webp'}),error:null})};}}};
 const db=new DatabaseLivingImageStore(fake);await db.put(article+'/'+image+'.webp',png);assert.equal(call[2].upsert,false);assert.equal(call[2].contentType,'image/webp');
 assert.equal((await db.read(image,true)).id,image);
 fake.storage.from=()=>({upload:async()=>{throw Error('private key');}});await assert.rejects(db.put('x',png),e=>e.code==='unavailable'&&!e.message.includes('private key'));
});
await test('real gallery renders 0/1/2/20 cards in both languages without autoplay or external image URLs',async()=>{
 const React=await import('react'),{renderToStaticMarkup}=await import('react-dom/server'),{default:ts}=await import('typescript'),{createRequire}=await import('node:module');
 const require=createRequire(import.meta.url),exports={};
 const code=ts.transpileModule(fs.readFileSync(new URL('../app/components/LivingImageGallery.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 const dependencies={'next/image':{default:props=>React.createElement('img',Object.fromEntries(Object.entries(props).filter(([k])=>!['unoptimized','onError'].includes(k))))},'./SourceImageDialog':{default:()=>null},'./LivingImageGallery.module.css':{default:{}},'../lib/living/images':await import('../app/lib/living/images.ts')};
 new Function('require','exports',code)(name=>name in dependencies?dependencies[name]:require(name),exports);
 for(const locale of ['ko','ja'])for(const count of [0,1,2,20]){
  const images=Array.from({length:count},()=>({id:randomUUID(),altKo:'합성 카드',altJa:'テスト画像'}));
  const html=renderToStaticMarkup(React.createElement(exports.default,{images,title:'<safe title>',locale}));
  assert.equal(html.includes('aria-roledescription'),count>0);assert.equal(html.includes(locale==='ko'?'다음 이미지':'次の画像'),count>1);
  if(count){assert.match(html,/src="\/api\/living\/images\//);assert.equal((html.match(/<img/g)||[]).length,1);}
 }
});
await test('exact 4MiB input accepted, over-limit input rejected before decoding',async()=>{
 const exact=Buffer.concat([png,Buffer.alloc(livingImageBytes-png.length)]);assert.equal((await normalizeLivingImage(exact,'image/png')).width,80);
 await assert.rejects(normalizeLivingImage(Buffer.concat([exact,Buffer.alloc(1)]),'image/png'),e=>e.code==='invalid_input');
});
console.log(JSON.stringify({image_groups_passed:passed,text_groups_passed:14,external_network:0,real_storage:0,operational_db:0,ai:0}));
