import { formatCurationPeriod } from './applicationDeadlineDisplay';
import { districtChoices, eventTopics, programTopics, provinceLabels } from './contentFilters';
import { sortedDistrictChoices } from './districtSort';
import type { LocalizedCuration } from './types';
import type { HomeTone } from './homeCardPalette';

export type { HomeTone } from './homeCardPalette';
export type HomeItem = {
  id: string; slug: string; title: string; summary: string; categoryLabel: string;
  imageUrl: string | null; period: string | null; tone?: HomeTone; toneManual?: boolean;
};
export type HomeSections = { deadline: HomeItem[]; experiences: HomeItem[]; learning: HomeItem[]; events: HomeItem[] };

// Preserve the incumbent home contract: the first two localized published rows,
// already ordered by created_at descending in fetchLocalizedCurations. No new eligibility policy.
export function currentHomeItems(rows: readonly LocalizedCuration[], locale: string, today: string,
  categories: (key: string) => string): HomeItem[] {
  return rows.slice(0, 2).map(item => ({
    id: item.id, slug: item.slug, title: item.title, summary: item.summary,
    imageUrl: item.source_image_url ?? null,
    categoryLabel: item.userCategory ? categories(item.userCategory) : '',
    period: formatCurationPeriod({ category: item.userCategory, deadlineKind: item.application_deadline_kind,
      deadlineOn: item.application_deadline_on, eventStartOn: item.event_start_on,
      eventEndOn: item.event_end_on, todayKst: today, locale }),
  }));
}

// A destination builder only: the list remains the authority for filtering.
export function homeFinderHref(category: 'program' | 'event', topic: string, region: string): string {
  const query = new URLSearchParams();
  if (Object.hasOwn(category === 'program' ? programTopics : eventTopics, topic)) query.set('topic', topic);
  const [province, district] = region.split(':');
  if (Object.hasOwn(provinceLabels, province)) {
    query.set('region', province);
    if (district && districtChoices[province as keyof typeof provinceLabels].includes(district)) query.set('district', `${province}:${district}`);
  }
  return `/info/category/${category}${query.size ? `?${query}` : ''}`;
}

export function homeDistricts(province: keyof typeof provinceLabels, locale: string): readonly string[] {
  return sortedDistrictChoices(province, locale);
}

export const homeCopy = {
  ko: {
    discover: '지금 살펴볼 정보', detail: '상세 내용 보기', previous: '이전 콘텐츠', next: '다음 콘텐츠',
    positions: '대표 콘텐츠 위치', expand: '펼쳐보기', close: '닫기', featured: '대표 콘텐츠', carousel: '캐러셀',
    emptyTitle: '지금은 소개할 정보가 없어요', emptyBody: '프로그램과 행사 목록을 살펴보세요.',
    programList: '프로그램 보기', eventList: '행사 보기', allPrograms: '프로그램 전체 목록 보기',
    deadline: '이번 주 신청 마감', deadlineEmpty: '신청 마감 정보는 프로그램 목록에서 확인해 주세요.',
    browse: '관심 가는 것부터 찾아보세요', experiences: '일상에 새로운 경험을', learning: '한국 생활에 도움이 되는 배움',
    events: '다가오는 행사', morePrograms: '프로그램 더 보기', moreEvents: '행사 더 보기',
    sectionEmpty: '목록에서 더 많은 정보를 살펴보세요.', finder: '조건을 골라 찾아보기',
    program: '프로그램', event: '행사', topic: '활동 분야', eventTopic: '행사 분야', region: '개최 지역',
    all: '전체', whole: '전체', findProgram: '조건에 맞는 프로그램 보기', findEvent: '조건에 맞는 행사 보기',
    finderNote: '대상·접수 상태 등 자세한 조건은 목록에서 선택할 수 있어요.',
    mailTitle: '한국 생활 이야기, 들려주세요.', mailBody: '불편했던 점이나 더 알고 싶은 것. 로그인 없이 익명으로 보낼 수 있어요.',
    mailAction: '이야기 보내기', note: '참여 조건과 최신 안내는 상세 내용과 공식 원문에서 확인해 주세요.',
  },
  ja: {
    discover: 'いまチェックしたい情報', detail: '詳しく見る', previous: '前のコンテンツ', next: '次のコンテンツ',
    positions: '表示するコンテンツ', expand: 'すべて見る', close: '閉じる', featured: 'ピックアップ', carousel: 'カルーセル',
    emptyTitle: 'いま紹介できる情報はありません', emptyBody: 'プログラムやイベントの一覧をご覧ください。',
    programList: 'プログラムを見る', eventList: 'イベントを見る', allPrograms: 'プログラムの全一覧を見る',
    deadline: '今週、申込締切の情報', deadlineEmpty: '申込締切はプログラムの一覧でご確認ください。',
    browse: '気になることから探す', experiences: 'いつもの毎日に、新しい体験を', learning: '韓国の暮らしに役立つ学び',
    events: 'これからのイベント', morePrograms: 'プログラムをもっと見る', moreEvents: 'イベント一覧',
    sectionEmpty: '一覧からほかの情報もご覧ください。', finder: '条件を選んで探す',
    program: 'プログラム', event: 'イベント', topic: '活動分野', eventTopic: 'イベント分野', region: '開催地域',
    all: 'すべて', whole: '全域', findProgram: '条件に合うプログラムを見る', findEvent: '条件に合うイベントを見る',
    finderNote: '対象者や受付状況など、詳しい条件は一覧で選べます。',
    mailTitle: '韓国での暮らしについて、聞かせてください。', mailBody: '不便だったことや、もっと知りたいこと。ログインなしで匿名で送れます。',
    mailAction: '声を届ける', note: '参加条件と最新の案内は詳細と公式ページでご確認ください。',
  },
} as const;
export function homeWords(locale: string) { return homeCopy[locale === 'ja' ? 'ja' : 'ko']; }
