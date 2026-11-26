import { Link } from '@/i18n/navigation';
import MailboxIllustration from './mailbox/MailboxIllustration';
import mailbox from './mailbox/mailbox-widget.module.css';
import HomeFeaturedCarousel from './HomeFeaturedCarousel';
import HomeContentCard, { HomeArrow } from './HomeContentCard';
import HomeFinder from './HomeFinder';
import { SettlementRow, WeeklyRow } from './HomeEditionRows';
import { homeWords, type HomeItem, type HomeSections } from '../lib/homePresentation';
import type { WeeklyEntry, settlementArticles } from '../lib/homeEditions';
import styles from './HomeExperience.module.css';
import css from './HomeEditions.module.css';

export default function HomeExperience({ locale, headline, intro, items, sections, topicLabels, settlement = [], weekly }: {
  locale: string; headline: string[]; intro: string; items: readonly HomeItem[];
  sections?: HomeSections; topicLabels: Record<string,string>; settlement?: ReturnType<typeof settlementArticles>; weekly?: { label: string; items: WeeklyEntry[] };
}) {
  const ja = locale === 'ja', words = homeWords(locale);
  const weeklyTitle = ja ? '今週のおでかけ' : '이번 주에 갈 만한 곳';
  const prepareTitle = '韓国で暮らし始める方へ';
  const livingLink = <Link className={css.more} href="/info/category/living">{words.moreLiving}<HomeArrow /></Link>;
  function articles(id: string, title: string, values: HomeItem[] | undefined, more: React.ReactNode, empty: string) {
    return <section className={css.section} aria-labelledby={id}>
      <div className={css.heading}><h2 id={id}>{title}</h2>{more}</div>
      {values?.length ? <div className={styles.livingItems}>{values.map(item =>
        <HomeContentCard key={item.id} item={item} locale={locale} layout="living" />)}</div> : <p>{empty}</p>}
    </section>;
  }
  const living = articles('home-living-title',words.living,sections?.living,livingLink,words.livingEmpty);
  const learning = articles('home-learning-title',words.learning,sections?.learning,
    <Link className={css.more} href="/info/category/program?topic=language_learning&topic=employment_career&topic=daily_safety">{words.morePrograms}<HomeArrow /></Link>,words.sectionEmpty);
  const outings = <section id="week" aria-labelledby="week-title" className={css.week}>
    <div className={css.heading}><h2 id="week-title">{weeklyTitle}</h2><span>{weekly?.label}</span></div>
    {weekly?.items.length ? weekly.items.map(item => <WeeklyRow key={item.slug} item={item} locale={locale} />)
      : <div className={css.empty}><p>{ja ? '今週の開催を確認できる情報はまだありません。' : '이번 주 개최가 확인된 일정은 아직 없습니다.'}</p>
        <Link href="/info/category/event">{words.eventList}<HomeArrow /></Link></div>}
  </section>;
  return <div className={`${styles.home} ${css.edition} public-readable`}>
    <section className={`${styles.intro} ${css.intro}`}><h1>{headline.join(ja ? '' : ' ')}</h1><p>{intro}</p>
      {ja && <nav className={css.routes} aria-label="目的から探す"><a href="#settle">{prepareTitle} ↓</a><a href="#week">{weeklyTitle} ↓</a></nav>}
    </section>
    {ja && <div className={css.dual}>
      <section id="settle" aria-labelledby="settle-title" className={css.section}>
        <div className={css.heading}><h2 id="settle-title">{prepareTitle}</h2></div>
        {settlement.length ? settlement.map(item => <SettlementRow key={item.slug} item={item} />) : <p>{words.sectionEmpty}</p>}
        {livingLink}
      </section>{outings}</div>}
    <HomeFeaturedCarousel key={locale} items={items} locale={locale} />
    {!ja && outings}
    <div className={css.tools}>
      <HomeFinder locale={locale}>
        <nav className={css.topics} aria-label={words.topic}>{Object.entries(topicLabels).map(([topic,label]) =>
          <Link key={topic} href={`/info/category/program?topic=${topic}`}>{label}<HomeArrow /></Link>)}</nav>
      </HomeFinder>
      <aside className={styles.mailbox} aria-labelledby="home-mail-title"><MailboxIllustration className={mailbox.illustration} />
        <div><h2 id="home-mail-title">{words.mailTitle}</h2><p>{words.mailBody}</p></div>
        <Link className={css.more} href="/feedback">{words.mailAction}<HomeArrow /></Link>
      </aside>
    </div>
    {!ja && living}{learning}{ja && living}
  </div>;
}
