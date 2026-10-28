'use client';
import Image from 'next/image';
import { ArrowUp,ArrowDown,Trash2 } from 'lucide-react';
import { useEffect,useRef,useState } from 'react';
import { fieldClass,secondaryButton } from './ReviewEditors';
import { livingImageBytes,livingImageLimit,livingImageSrc,type LivingImage } from '../../lib/living/images';

type Transfer={id:string;name:string;state:'uploading'|'ready'|'failed'|'unknown';message?:string};
export default function LivingImagesEditor({articleId,version,images,onChange,onActive,disabled}:{
  articleId:string;version:string;images:LivingImage[];onChange:(images:LivingImage[])=>void;onActive:(active:boolean)=>void;disabled:boolean;
}){
  const [transfers,setTransfers]=useState<Transfer[]>([]),[sending,setSending]=useState(false),[notice,setNotice]=useState('');
  const gate=useRef(false),current=useRef(images);
  useEffect(()=>{current.current=images;},[images]);
  const unresolved=transfers.some(t=>t.state==='unknown'),locked=disabled||sending||unresolved;
  useEffect(()=>{onActive(sending||unresolved);},[sending,unresolved,onActive]);
  function update(id:string,patch:Partial<Transfer>){setTransfers(old=>old.map(t=>t.id===id?{...t,...patch}:t));}
  function attach(id:string){if(!current.current.some(i=>i.id===id)){const next=[...current.current,{id,altKo:'',altJa:''}];current.current=next;onChange(next);}}
  async function upload(files:File[]){
    if(gate.current||locked)return;
    if(files.length+images.length>livingImageLimit){setNotice('카드뉴스는 최대 20장까지 등록할 수 있습니다.');return;}
    if(files.some(f=>!['image/png','image/jpeg','image/webp'].includes(f.type)||f.size>livingImageBytes||!f.size)){setNotice('PNG·JPEG·WebP 파일을 한 장당 4MiB 이내로 선택해 주세요.');return;}
    gate.current=true;setSending(true);setNotice('');
    try{for(let n=0;n<files.length;n++){
      const file=files[n],id=crypto.randomUUID();setTransfers(old=>[...old,{id,name:file.name,state:'uploading'}]);
      try{
        const res=await fetch(livingImageSrc(id,true),{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':file.type,'x-living-article':articleId,'x-living-version':version},body:file});
        const data=await res.json().catch(()=>null);
        if(res.ok&&data?.item?.id===id&&data.item.status==='ready'){attach(id);update(id,{state:'ready'});continue;}
        if(res.status===422){update(id,{state:'failed',message:data?.fields?.images??'파일 형식·크기를 확인해 주세요.'});continue;}
        if([401,403,409].includes(res.status)){update(id,{state:'failed',message:'로그인·권한 또는 초안 버전이 변경됐습니다. 현재 입력을 유지하고 업로드를 중단했습니다.'});break;}
        throw Error();
      }catch{update(id,{state:'unknown',message:'업로드 결과를 확인하지 못했습니다. 자동 재시도하지 않습니다.'});setNotice(n+1<files.length?'남은 파일은 전송하지 않았습니다. 결과 확인 후 다시 선택해 주세요.':'');break;}
    }}finally{gate.current=false;setSending(false);}
  }
  async function check(id:string){if(gate.current)return;gate.current=true;setSending(true);
    try{const res=await fetch(`${livingImageSrc(id,true)}?view=status`,{credentials:'same-origin',cache:'no-store'}),data=await res.json();
      if(res.ok&&data?.item?.id===id&&data.item.status==='ready'){attach(id);update(id,{state:'ready',message:''});}
      else update(id,{message:'완료를 확인하지 못했습니다. 자동 재전송 없이 보류합니다.'});
    }catch{update(id,{message:'상태 조회에 실패했습니다. 입력은 유지했습니다.'});}finally{gate.current=false;setSending(false);}
  }
  function move(index:number,delta:number){const list=[...images];[list[index],list[index+delta]]=[list[index+delta],list[index]];onChange(list);}
  return <section className="mb-10 border-y border-info-rule py-6" aria-labelledby="living-images-title">
    <h3 id="living-images-title" className="text-xl font-bold text-primary-text">카드뉴스 이미지</h3>
    <p className="mt-3 text-sm leading-7 text-info-muted">여러 파일을 한 번에 선택하세요. 첫 이미지가 목록의 대표 이미지가 됩니다. 한·일 화면에서 같은 이미지를 사용하며, 텍스트는 자동 번역하지 않습니다.</p>
    <p className="mt-2 text-sm leading-6 text-info-muted">최대 20장 · 한 장당 4MiB · PNG·JPEG·WebP. 초안 이미지는 비공개로 보관하고 글 게시 후 공개합니다.</p>
    <label className="mt-5 block font-semibold text-ink" htmlFor="living-image-files">PC 이미지 파일 선택</label>
    <input id="living-image-files" type="file" accept="image/png,image/jpeg,image/webp" multiple disabled={locked} className="mt-3 block max-w-full text-sm text-primary-text file:mr-3 file:min-h-11 file:rounded-lg file:border file:border-info-rule file:bg-info-surface file:px-4 file:text-ink disabled:opacity-50"
      onChange={e=>{const files=Array.from(e.target.files??[]);e.target.value='';void upload(files);}}/>
    {notice&&<p role="status" className="mt-3 leading-7 text-info-status">{notice}</p>}
    {transfers.filter(t=>t.state!=='ready').map(t=><div key={t.id} className="mt-4 border-b border-info-rule pb-4">
      <p role="status" className="break-words text-sm leading-7 text-info-body">{t.name} · {t.state==='uploading'?'업로드 중…':t.message}</p>
      {t.state==='unknown'&&<div className="mt-2 flex flex-wrap gap-2"><button type="button" className={secondaryButton} disabled={sending} onClick={()=>check(t.id)}>업로드 상태 확인</button><button type="button" className={secondaryButton} disabled={sending} onClick={()=>update(t.id,{state:'failed',message:'이 이미지의 연결을 제외했습니다. 보관된 파일과 이력은 삭제하지 않았습니다.'})}>이번 이미지 제외</button></div>}
    </div>)}
    {!images.length?<p className="mt-5 leading-7 text-info-muted">등록한 이미지가 없습니다. 이미지 없이 글만 작성할 수도 있습니다.</p>:
      <ol className="mt-6 divide-y divide-info-rule">{images.map((image,index)=><li key={image.id} className="grid min-w-0 gap-4 py-5 sm:grid-cols-[6rem_minmax(0,1fr)]">
        <Image src={livingImageSrc(image.id,true)} alt={image.altKo||`등록한 이미지 ${index+1}`} width={96} height={120} unoptimized className="h-28 w-24 object-contain"/>
        <div className="min-w-0"><div className="flex flex-wrap items-center justify-between gap-3"><span className="font-semibold text-ink">{index+1} / {images.length}{index===0?' · 대표 이미지':''}</span><div className="flex gap-2">
          <button type="button" className={secondaryButton} aria-label={`이미지 ${index+1} 앞으로 이동`} disabled={locked||index===0} onClick={()=>move(index,-1)}><ArrowUp size={18} aria-hidden="true"/></button>
          <button type="button" className={secondaryButton} aria-label={`이미지 ${index+1} 뒤로 이동`} disabled={locked||index===images.length-1} onClick={()=>move(index,1)}><ArrowDown size={18} aria-hidden="true"/></button>
          <button type="button" className={secondaryButton} aria-label={`이미지 ${index+1} 연결 삭제`} disabled={locked} onClick={()=>onChange(images.filter(i=>i.id!==image.id))}><Trash2 size={18} aria-hidden="true"/></button>
        </div></div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">{(['Ko','Ja']as const).map(lang=><div key={lang}><label htmlFor={`image-${image.id}-${lang}`} className="text-sm font-semibold text-ink">{lang==='Ko'?'한국어':'일본어'} 이미지 설명 (선택)</label><input id={`image-${image.id}-${lang}`} value={image[`alt${lang}`]} maxLength={500} disabled={locked} className={fieldClass} onChange={e=>onChange(images.map(i=>i.id===image.id?{...i,[`alt${lang}`]:e.target.value}:i))}/></div>)}</div></div>
      </li>)}</ol>}
  </section>;
}
