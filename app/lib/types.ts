// Supabase 테이블 행(row)에 대응하는 도메인 타입

export interface Curation {
  id: string;
  slug: string;
  category: string;
  title: string;
  summary: string;
  content: string;
  title_ko: string | null;
  title_ja: string | null;
  summary_ko: string | null;
  summary_ja: string | null;
  content_ko: string | null;
  content_ja: string | null;
  source: string | null;
  source_item_id: string | null;
  source_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface LocalizedCuration {
  id: string;
  slug: string;
  category: string;
  title: string;
  summary: string;
  content: string;
  source: string | null;
  source_item_id: string | null;
  source_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface QnaEntry {
  id: string;
  nickname: string;
  content: string;
  created_at: string;
}
