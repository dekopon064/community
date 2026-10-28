import {notFound,redirect} from 'next/navigation';
import {getAdminAccess} from '@/app/lib/auth/admin';
import {loginUrl} from '@/app/lib/auth/urls';
import LivingArticlePanel from '@/app/components/admin/LivingArticlePanel';
export const dynamic='force-dynamic';
export const metadata={title:'생활 글 작성 | 마치모아',robots:{index:false,follow:false}};
export default async function LivingPage({params}:{params:Promise<{locale:string}>}){
  const {locale}=await params;if(!['ko','ja'].includes(locale))notFound();if(locale!=='ko')redirect('/ko/admin/living');
  const access=await getAdminAccess({readOnly:true});if(access.status==='signed_out')redirect(loginUrl('ko','/ko/admin/living'));
  return <section className="mx-auto max-w-7xl px-5 py-10 sm:py-12"><h1 className="text-3xl font-bold text-primary-text">생활 글 작성</h1>
    {access.status==='admin'?<><p className="mt-4 leading-7 text-info-body">한국어·일본어 생활 안내를 직접 작성합니다. 초안 저장 후 내용을 확인하고 게시하세요.</p><LivingArticlePanel/></>:<p role="alert" className="mt-5 text-info-status">운영자 접근 권한을 확인할 수 없습니다.</p>}</section>;
}
