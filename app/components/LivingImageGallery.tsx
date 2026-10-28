'use client';
import Image from 'next/image';
import { ChevronLeft, ChevronRight, ZoomIn } from 'lucide-react';
import { useRef, useState, type PointerEvent } from 'react';
import SourceImageDialog from './SourceImageDialog';
import { livingImageSrc, type LivingImage } from '../lib/living/images';
import styles from './LivingImageGallery.module.css';

export default function LivingImageGallery({images,title,locale,admin=false}:{images:LivingImage[];title:string;locale:string;admin?:boolean}){
  const [index,setIndex]=useState(0),[failed,setFailed]=useState<string|null>(null);
  const trigger=useRef<HTMLButtonElement>(null),gesture=useRef({x:0,y:0,active:false,moved:false});
  if(!images.length)return null;
  const page=Math.min(index,images.length-1),image=images[page],ja=locale==='ja',src=livingImageSrc(image.id,admin);
  const label=(ja?image.altJa:image.altKo)||`${title} · ${ja?'画像':'이미지'} ${page+1}`;
  const previous=ja?'前の画像':'이전 이미지',next=ja?'次の画像':'다음 이미지';
  function move(n:number){setIndex(Math.max(0,Math.min(images.length-1,n)));}
  function begin(e:PointerEvent){gesture.current={x:e.clientX,y:e.clientY,active:e.isPrimary&&e.button===0,moved:false};}
  function end(e:PointerEvent){const g=gesture.current;if(!g.active)return;g.active=false;const dx=e.clientX-g.x,dy=e.clientY-g.y;
    if(Math.abs(dx)>50&&Math.abs(dx)>Math.abs(dy)*1.5){g.moved=true;move(page+(dx<0?1:-1));}}
  return <section className={styles.gallery} aria-label={ja?'カードニュース':'카드뉴스'} aria-roledescription={ja?'画像ギャラリー':'이미지 갤러리'}
    onKeyDown={e=>{if(e.altKey||e.ctrlKey||e.metaKey||(e.target as HTMLElement).closest('dialog'))return;if(e.key==='ArrowLeft'){e.preventDefault();move(page-1);}else if(e.key==='ArrowRight'){e.preventDefault();move(page+1);}}}>
    <div className={styles.stage} onPointerDown={begin} onPointerMove={e=>{if(gesture.current.active&&Math.hypot(e.clientX-gesture.current.x,e.clientY-gesture.current.y)>8)gesture.current.moved=true;}}
      onPointerUp={end} onPointerCancel={()=>{gesture.current.active=false;gesture.current.moved=true;}}>
      {failed===image.id?<p role="status" className={styles.error}>{ja?'画像を読み込めませんでした。別の画像に移動できます。':'이미지를 불러오지 못했습니다. 다른 이미지로 이동할 수 있습니다.'}</p>:
        <button key={image.id} type="button" ref={trigger} className={styles.imageButton} aria-haspopup="dialog" aria-label={ja?'画像を拡大':'이미지 크게 보기'}
          onClickCapture={e=>{if(e.detail>0&&gesture.current.moved){e.preventDefault();e.stopPropagation();}}}>
          <Image src={src} alt={label} width={1000} height={1400} unoptimized className={styles.image} draggable={false} onError={()=>setFailed(image.id)}/>
          <span className={styles.zoom}><ZoomIn size={19} aria-hidden="true"/></span>
        </button>}
    </div>
    {images.length>1&&<div className={styles.controls}>
      <button type="button" aria-label={previous} disabled={page===0} onClick={()=>move(page-1)}><ChevronLeft size={22} aria-hidden="true"/></button>
      <p className={styles.count} role="status" aria-live="polite">{page+1} / {images.length}</p>
      <button type="button" aria-label={next} disabled={page===images.length-1} onClick={()=>move(page+1)}><ChevronRight size={22} aria-hidden="true"/></button>
      <div className={styles.dots} aria-label={ja?'画像を選択':'이미지 선택'}>{images.map((v,n)=><button key={v.id} type="button" aria-label={ja?`画像${n+1}を見る`:`이미지 ${n+1} 보기`} aria-current={n===page?'true':undefined} onClick={()=>move(n)}><span/></button>)}</div>
    </div>}
    {failed!==image.id&&<SourceImageDialog key={image.id} src={src} title={label} locale={locale} trigger={trigger} kind="article"/>}
  </section>;
}
