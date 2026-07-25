// Supabase 테이블 행(row)에 대응하는 도메인 타입

export interface Curation {
  id: string;
  slug: string;
  category: string;
  title: string;
  summary: string;
  content: string;
  created_at: string;
}

export interface QnaEntry {
  id: string;
  nickname: string;
  content: string;
  created_at: string;
}
