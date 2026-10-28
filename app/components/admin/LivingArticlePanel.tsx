'use client';
import { useCallback,useEffect,useRef,useState } from 'react';
import Link from 'next/link';
import { CandidateEditor,fieldClass,primaryButton,secondaryButton } from './ReviewEditors';
import { emptyLivingDocument,livingArticle,livingBody } from '../../lib/living/contract';
import type {LivingArticle,LivingDocument,LivingListItem} from '../../lib/living/contract';
import CurationBody from '../CurationBody';
import CurationDetailHeading from '../CurationDetailHeading';
import CategoryIcon from '../CategoryIcon';
import {sourceImageUrl} from '../../lib/sourceImages';
import LivingImagesEditor from './LivingImagesEditor';
import LivingImageGallery from '../LivingImageGallery';

class LivingRequestError extends Error { constructor(readonly code:string,readonly fields:Record<string,string>={}){super(code);} }
async function request(path:string,body?:unknown) {
  const response=await fetch(path,{credentials:'same-origin',cache:'no-store',...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
  const data=await response.json().catch(()=>null);
  if(!response.ok)throw new LivingRequestError(data?.code??'unavailable',data?.fields??{});
  if(!['database','local-fixture'].includes(data?.mode))throw new LivingRequestError('unavailable');return data;
}
export default function LivingArticlePanel(){
  const [items,setItems]=useState<LivingListItem[]>([]),[selected,setSelected]=useState<LivingArticle|null>(null);
  const [id,setId]=useState(''),[draft,setDraft]=useState<LivingDocument>(emptyLivingDocument),[busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true),[mode,setMode]=useState(''),[offset,setOffset]=useState(0),[reload,setReload]=useState(0);
  const [notice,setNotice]=useState(''),[error,setError]=useState(''),[errors,setErrors]=useState<Record<string,string>>({});
  const [uncertain,setUncertain]=useState(false),[confirm,setConfirm]=useState(false),[preview,setPreview]=useState(false),[locale,setLocale]=useState<'ko'|'ja'>('ja');
  const mutation=useRef(false),heading=useRef<HTMLHeadingElement>(null);
  const [imageBusy,setImageBusy]=useState(false);
  const imageActivity=useCallback((active:boolean)=>setImageBusy(active),[]);
  const baseline=selected?.document??emptyLivingDocument(),dirty=JSON.stringify(baseline)!==JSON.stringify(draft);
  const published=selected?.status==='published',blocked=busy||uncertain||confirm||imageBusy;
  useEffect(()=>{let current=true;request(`/api/admin/living?offset=${offset}`).then(data=>{if(current){setItems(data.items);setMode(data.mode);setLoading(false);}}).catch(()=>{if(current){setError('목록을 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.');setLoading(false);}});return()=>{current=false;};},[offset,reload]);
  useEffect(()=>{const prevent=(event:BeforeUnloadEvent)=>{if(dirty||uncertain||busy||imageBusy){event.preventDefault();}};window.addEventListener('beforeunload',prevent);return()=>window.removeEventListener('beforeunload',prevent);},[dirty,uncertain,busy,imageBusy]);
  function accept(item:LivingArticle){setSelected(item);setId(item.id);setDraft(structuredClone(item.document));setErrors({});setError('');setConfirm(false);setUncertain(false);}
  function newDraft(){if(blocked||dirty)return;setSelected(null);setId(crypto.randomUUID());setDraft(emptyLivingDocument());setNotice('');setError('');setErrors({});setPreview(false);heading.current?.focus();}
  async function open(row:LivingListItem){if(blocked||dirty)return;setBusy(true);try{const data=await request(`/api/admin/living?id=${row.id}`);accept(livingArticle(data.item));setNotice('');setPreview(false);}catch{setError('생활 글을 불러오지 못했습니다. 현재 입력은 유지했습니다.');}finally{setBusy(false);}}
  async function save(action:'save'|'publish'){
    if(mutation.current||busy||uncertain||imageBusy||published||action==='publish'&&(!selected||dirty))return;
    mutation.current=true;setBusy(true);setError('');setErrors({});setNotice('');
    try{
      const data=await request('/api/admin/living',{id,version:selected?.version??'0',requestId:crypto.randomUUID(),action,document:action==='save'?draft:null});
      accept(livingArticle(data.item));setMode(data.mode);setNotice(action==='save'?'초안을 저장했습니다. 아직 공개되지 않았습니다.':data.mode==='local-fixture'?'로컬 가짜 게시가 완료됐습니다. 운영 게시가 아닙니다.':'생활 카테고리에 게시했습니다.');setReload(x=>x+1);
    }catch(e){
      const code=e instanceof LivingRequestError?e.code:'unavailable';setErrors(e instanceof LivingRequestError?e.fields:{});
      setError(code==='conflict'?'다른 변경이 감지됐습니다. 입력을 복사해 보관한 뒤 최신 저장값을 확인해 주세요.':code==='signed_out'?'로그인이 만료됐습니다. 입력은 유지했습니다. 다시 로그인한 뒤 상태를 확인해 주세요.':code==='forbidden'?'운영자 권한을 확인할 수 없습니다. 입력은 유지했습니다.':code==='invalid_input'?'입력 내용을 확인해 주세요. 제목·요약은 한·일 모두 작성하고, 본문 또는 카드뉴스 이미지를 등록해 주세요.':code==='already_processed'?'이미 게시된 글입니다. 현재 저장 상태를 확인해 주세요.':'저장 결과를 확인하지 못했습니다. 자동 재시도하지 않습니다. 현재 저장 상태를 먼저 확인해 주세요.');
      if(!['invalid_input','signed_out','forbidden'].includes(code))setUncertain(true);setConfirm(false);
    }finally{setBusy(false);mutation.current=false;}
  }
  async function checkSaved(){if(busy||!id)return;setBusy(true);try{
    const data=await request(`/api/admin/living?id=${id}`),item=livingArticle(data.item);
    // A read never overwrites an unsaved editor, even when the prior write succeeded.
    setSelected(item);setUncertain(false);setError('');setNotice(item.status==='published'?'게시 완료 상태를 확인했습니다. 입력은 보존했습니다.':'현재 저장 상태를 확인했습니다. 화면의 입력은 보존했습니다.');
  }catch(e){setError(e instanceof LivingRequestError&&e.code==='not_found'?'저장된 초안을 찾지 못했습니다. 입력은 유지했으며 쓰기는 반복하지 않았습니다.':'저장 상태가 여전히 불명확합니다. 입력을 유지하며 쓰기를 중단합니다.');}finally{setBusy(false);}}
  return <><Link href="/ko/admin" aria-disabled={blocked||dirty} onClick={event=>{if(blocked||dirty)event.preventDefault();}} className="mt-5 inline-flex min-h-11 items-center text-ink underline">검토 관리로 돌아가기</Link><div className="mt-8 grid min-w-0 gap-8 lg:grid-cols-[15rem_minmax(0,1fr)]">
    <aside aria-label="생활 글 목록" className="min-w-0 border-b border-info-rule pb-6 lg:border-b-0 lg:border-r lg:pr-6">
      <button type="button" className={primaryButton} disabled={blocked||dirty} onClick={newDraft}>새 생활 글</button>
      <p className="my-4 text-sm leading-6 text-info-muted">수동으로 작성한 생활 초안과 게시된 글을 확인합니다.</p>
      {loading?<p role="status">목록을 불러오는 중입니다.</p>:items.length===0?<p className="text-info-muted">저장한 생활 글이 없습니다.</p>:<ul className="divide-y divide-info-rule">{items.map(row=><li key={row.id}><button type="button" className="w-full break-words py-4 text-left leading-7 text-ink disabled:opacity-45" disabled={blocked||dirty} aria-current={id===row.id?'page':undefined} onClick={()=>open(row)}><span className="block text-sm text-info-muted">{row.status==='draft'?'비공개 초안':'게시됨'}</span>{row.title}</button></li>)}</ul>}
      <div className="mt-4 flex flex-wrap gap-2"><button type="button" className={secondaryButton} disabled={blocked||dirty||offset===0} onClick={()=>setOffset(x=>Math.max(0,x-25))}>이전</button><button type="button" className={secondaryButton} disabled={blocked||dirty||items.length<25} onClick={()=>setOffset(x=>x+25)}>다음</button></div>
    </aside>
    <section className="min-w-0" aria-labelledby="living-editor-heading">
      <h2 ref={heading} tabIndex={-1} id="living-editor-heading" className="text-2xl font-bold text-primary-text">{published?'게시된 생활 글':id?'생활 글 작성':'생활 글을 작성해 주세요'}</h2>
      {mode==='local-fixture'&&<p role="status" className="my-4 border-y border-info-rule py-3 text-info-status">로컬 시험 데이터 · 저장·게시는 가짜 저장소에서만 처리됩니다.</p>}
      {notice&&<p role="status" className="my-4 leading-7 text-info-body">{notice}</p>}
      {error&&<p role="alert" className="my-4 leading-7 text-info-status">{error}</p>}
      {!id?<p className="mt-4 leading-7 text-info-body">‘새 생활 글’을 눌러 시작하세요. 수집이나 AI 실행 없이 초안을 작성합니다.</p>:<>
        <div className="my-5 flex flex-wrap gap-3"><button type="button" className={secondaryButton} disabled={busy||confirm||imageBusy} onClick={()=>setPreview(x=>!x)}>{preview?'편집으로 돌아가기':'미리보기'}</button>
          {dirty&&<button type="button" className={secondaryButton} disabled={blocked} onClick={()=>setDraft(structuredClone(baseline))}>변경 취소</button>}
          {uncertain&&<button type="button" className={secondaryButton} disabled={busy} onClick={checkSaved}>현재 저장 상태 확인</button>}
          {!published&&<button type="button" className={primaryButton} disabled={blocked||Boolean(selected)&&!dirty} onClick={()=>save('save')}>{busy?'처리 중…':'초안 저장'}</button>}
        </div>
        {dirty&&<p className="mb-5 text-sm text-info-status">저장하지 않은 변경이 있습니다. 글 이동·게시 전에 초안을 저장하거나 변경을 취소해 주세요.</p>}
        {preview?<div><div role="group" aria-label="미리보기 언어" className="mb-6 flex gap-2">{(['ko','ja'] as const).map(lang=><button type="button" key={lang} aria-pressed={locale===lang} onClick={()=>setLocale(lang)} className={locale===lang?primaryButton:secondaryButton}>{lang==='ko'?'한국어':'日本語'}</button>)}</div>
          <p className="mb-4 text-sm text-info-muted">미리보기 · 현재 입력 내용이며 공개되지 않았습니다.</p>
          <div lang={locale}><CurationDetailHeading title={draft.content[locale==='ko'?'titleKo':'titleJa']||'제목 미입력'} url={draft.images?.length?null:draft.imageUrl||null} locale={locale} back={null} category={<span className="flex items-center gap-2"><CategoryIcon category="living" size={20}/>{locale==='ko'?'생활':'暮らし'}</span>} period={null} save={null}/>
          <LivingImageGallery key={id} images={draft.images??[]} title={draft.content[locale==='ko'?'titleKo':'titleJa']} locale={locale} admin/>
          <p className="my-6 leading-8 text-info-body"><span className="block text-sm text-info-muted">{locale==='ko'?'목록에 표시할 요약':'一覧に表示する要約'}</span>{draft.content[locale==='ko'?'summaryKo':'summaryJa']}</p>
          <article className="public-readable min-w-0 rounded-2xl border border-info-rule bg-canvas-white p-5 md:p-8"><CurationBody content={livingBody(draft,locale)} locale={locale}/></article>
          {sourceImageUrl(draft.referenceUrl)&&<a href={sourceImageUrl(draft.referenceUrl)!} target="_blank" rel="noopener noreferrer" className="mt-5 inline-block break-all text-ink underline">{locale==='ko'?'참고 링크':'参考リンク'}</a>}</div>
        </div>:<>
          <LivingImagesEditor key={id} articleId={id} version={selected?.version??'0'} images={draft.images??[]} onChange={images=>setDraft(old=>({...old,images}))} onActive={imageActivity} disabled={busy||uncertain||confirm||published}/>
          {(draft.images?.length??0)>0&&<p className="mb-5 text-sm leading-7 text-info-muted">카드뉴스가 본문 위에 먼저 표시됩니다. 제목·요약은 한·일 모두 작성하고, 추가 설명이 필요할 때만 상세 본문을 입력하세요.</p>}
          <CandidateEditor value={draft.content} onChange={content=>setDraft({...draft,content})} errors={errors} disabled={blocked||published} formattedBody/>
          <div className="mt-8 grid gap-6 sm:grid-cols-2">{([{key:'imageUrl',label:'별도 대표 이미지 URL (선택)',type:'url',help:'비워두면 카드뉴스의 첫 이미지를 목록에 표시합니다. 별도 대표 이미지가 필요할 때만 HTTPS 주소를 입력하세요.'},{key:'referenceUrl',label:'대표 참고 링크 (선택)',type:'url',help:'공식 안내 링크를 입력합니다. 추가 출처는 본문에 링크로 작성할 수 있습니다.'},{key:'checkedOn',label:'정보 확인일 (선택)',type:'date',help:'실제로 내용을 확인한 날짜를 입력합니다. 게시일과 구분해 본문 하단에 표시합니다.'}] as const).map(({key,label,type,help})=><div key={key}><label htmlFor={`living-${key}`} className="font-semibold text-ink">{label}</label><p className="my-2 text-sm leading-6 text-info-muted">{help}</p><input id={`living-${key}`} type={type} value={draft[key]} onChange={e=>setDraft({...draft,[key]:e.target.value})} disabled={blocked||published} className={fieldClass} aria-invalid={!!errors[key]}/>{errors[key]&&<p role="alert" className="mt-2 text-info-status">{errors[key]}</p>}</div>)}</div>
        </>}
        {published?<div className="mt-8 border-t border-info-rule pt-5"><p className="leading-7 text-info-body">게시된 글입니다. 이 화면에서는 저장값과 게시 이력을 확인할 수 있습니다.</p><div className="mt-3 flex flex-wrap gap-4"><a className="text-ink underline" href={`/ko/info/${selected?.publishedSlug}`}>한국어 공개 글</a><a className="text-ink underline" href={`/ja/info/${selected?.publishedSlug}`}>일본어 공개 글</a></div></div>:<div className="mt-8 border-t border-info-rule pt-6">
          <p className="mb-4 leading-7 text-info-muted">초안 저장과 미리보기는 비공개입니다. 저장된 최신 초안만 생활 카테고리에 게시합니다.</p>
          {confirm?<div><p className="mb-4 font-semibold text-ink">저장된 한국어·일본어 내용을 생활 카테고리에 게시할까요?</p><div className="flex flex-wrap gap-3"><button type="button" className={primaryButton} disabled={busy} onClick={()=>save('publish')}>확인하고 게시</button><button type="button" className={secondaryButton} disabled={busy} onClick={()=>setConfirm(false)}>돌아가기</button></div></div>:<button type="button" className={primaryButton} disabled={blocked||dirty||!selected} onClick={()=>setConfirm(true)}>게시 검토</button>}
        </div>}
        {selected&&<details className="mt-8 border-t border-info-rule pt-4"><summary className="min-h-11 cursor-pointer font-semibold text-ink">저장·게시 이력 ({selected.history.length})</summary><ol className="space-y-3 py-4 text-sm leading-6 text-info-muted">{selected.history.toReversed().map((entry,i)=><li key={i}>{entry.action==='save'?'초안 저장':'게시'} · {new Date(entry.at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})} · 운영자 {entry.actor}</li>)}</ol></details>}
      </>}
    </section>
  </div></>;
}
