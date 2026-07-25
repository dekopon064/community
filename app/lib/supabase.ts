import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!supabaseUrl) {
  throw new Error(
    "환경 변수 NEXT_PUBLIC_SUPABASE_URL이 설정되지 않았습니다. .env.local을 확인해주세요.",
  );
}

if (!supabaseAnonKey) {
  throw new Error(
    "환경 변수 NEXT_PUBLIC_SUPABASE_ANON_KEY가 설정되지 않았습니다. .env.local을 확인해주세요.",
  );
}

// 앱 어디서든 재사용 가능한 공통 Supabase 클라이언트 인스턴스
export const supabase = createClient(supabaseUrl, supabaseAnonKey);
