import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { getAdminAccess } from "@/app/lib/auth/admin";
import { loginUrl } from "@/app/lib/auth/urls";
import ReviewWorkspace from "@/app/components/admin/ReviewWorkspace";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "검토 관리 | 마치모아", robots: { index: false, follow: false } };

export default async function AdminPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (locale !== "ko" && locale !== "ja") notFound();
  if (locale !== "ko") redirect("/ko/admin");
  const access = await getAdminAccess({ readOnly: true });
  if (access.status === "signed_out") redirect(loginUrl("ko", "/ko/admin"));

  const allowed = access.status === "admin";
  const unavailable = access.status === "auth_unavailable" || access.status === "configuration_error";
  const title = allowed ? "검토 관리" : unavailable ? "접근 권한을 확인할 수 없습니다" : "운영자 접근 권한이 없습니다";
  const description = allowed ? "원문 사실 확인과 AI 결과 검토를 각각 진행합니다. 운영자 접근이 확인되었습니다." : unavailable ?
    "잠시 후 다시 시도해 주세요. 문제가 계속되면 서비스 관리자에게 문의해 주세요." :
    "이 계정으로는 관리 화면을 이용할 수 없습니다. 운영자로 지정된 계정으로 다시 로그인해 주세요.";

  return (
    <section className={`mx-auto px-5 py-10 sm:py-12 ${allowed ? "max-w-7xl" : "max-w-xl"}`}>
      <h1 className="break-keep text-3xl font-bold tracking-tight text-primary-text">{title}</h1>
      <p className="mt-4 leading-7 text-info-body" role={allowed ? "status" : "alert"}>{description}</p>
      {allowed && <ReviewWorkspace />}
      <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
        <Link href="/ko" prefetch={false} className="inline-flex min-h-12 items-center rounded-xl bg-ink px-6 py-3 font-semibold text-canvas-white hover:opacity-85">공개 정보로 돌아가기</Link>
        {!allowed && <a href={unavailable ? "/ko/admin" : loginUrl("ko", "/ko/admin")} className="inline-flex min-h-11 items-center text-ink underline underline-offset-4">{unavailable ? "다시 확인하기" : "로그인 상태 확인"}</a>}
      </div>
    </section>
  );
}
