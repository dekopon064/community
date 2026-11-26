// Local public-read fixture for the actual Next home and detail routes.
import http from 'node:http';
const day = new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul'}).format(new Date());
const offset = n => new Date(Date.parse(day)+n*86400000).toISOString().slice(0,10);
const from=offset(-2),through=offset(10);
const known=value=>({status:'known',value}), unknown={status:'unknown',value:null}, na={status:'not_applicable',value:null};
const rows=['program','event'].map((category,i)=>{
 // Preserved article titles. The preview calendar and event are synthetic.
 const subject=i?'주말 문화 행사':'2026 더 임팩트 청년예술인 공모전시 [흐르는 호수처럼] 미술전시해설 도슨트 프로그램';
 const ja=i?'週末の文化イベント':'2026 ザ・インパクト 若手芸術家公募展［流れる湖のように］美術展解説ドーセントプログラム';
 return {id:'00000000-0000-4000-8000-00000000000'+(i+1),slug:i?'demo-event':'demo-exhibition',user_category:category,category,
 title_ko:subject,title_ja:ja,summary_ko:i?'공개 행사 예시':'전시와 별도로 작가 해설은 사전 예약이 필요합니다.',summary_ja:i?'公開イベントの例':'作家による解説は別途予約が必要です。',
 content_ko:'로컬 합성 자료입니다.',content_ja:'ローカル検証用のデータです。',source:null,source_item_id:null,source_url:null,source_image_url:null,is_published:true,
 created_at:from+'T00:00:00Z',updated_at:from+'T00:00:00Z',application_deadline_kind:null,application_deadline_on:null,event_start_on:i?day:null,event_end_on:i?day:null,
 content_filters:i?null:{schema:'content-filters-v1',category,topic:known('culture_experience'),location:known({scope:'specific',venues:[{province:'11',district:null,facility:'',address:''}]}),
 delivery:known('onsite'),audience:known('other'),foreignerProgram:unknown,spaceKind:na,application:unknown,schedule:na},
 program_outing:i?null:{viewing:{subject:'exhibition',from,through,weekdays:[0,1,2,3,4,5,6],exceptions:[],reservationNotRequired:true}}};
});
http.createServer((req,res)=>{
 const u=new URL(req.url,'http://localhost');
 if(u.pathname==='/rest/v1/curations' && req.method==='GET'){
 const selected=rows.filter(r=>(!u.searchParams.has('slug')||u.searchParams.get('slug')==='eq.'+r.slug)&&(!u.searchParams.has('user_category')||u.searchParams.get('user_category')==='eq.'+r.user_category));
 res.setHeader('content-range',selected.length?'0-'+(selected.length-1)+'/'+selected.length:'*/0');
 res.setHeader('content-type','application/json');res.end(JSON.stringify(req.headers.accept?.includes('vnd.pgrst.object')?selected[0]??null:selected));return;
 }
 if(['/rest/v1/rpc/public_home_card_colors','/rest/v1/rpc/public_home_featured_pins'].includes(u.pathname)){res.setHeader('content-type','application/json');res.end('[]');return;}
 res.writeHead(404);res.end();
}).listen(4392,'127.0.0.1');
