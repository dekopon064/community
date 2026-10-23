import { Link } from '@/i18n/navigation';
import MailboxIllustration from './mailbox/MailboxIllustration';
import mailbox from './mailbox/mailbox-widget.module.css';
import HomeFeaturedCarousel from './HomeFeaturedCarousel';
import HomeContentCard, { HomeArrow } from './HomeContentCard';
import HomeFinder from './HomeFinder';
import { homeWords, type HomeItem, type HomeSections } from '../lib/homePresentation';
import styles from './HomeExperience.module.css';

// Section assignments are explicit inputs. No source IDs, automatic topic guesses,
// deadline eligibility rules, or poster-color mappings live in the presentation.
export default function HomeExperience({ locale, headline, intro, items, sections, topicLabels }: {
  locale: string; headline: string[]; intro: string; items: readonly HomeItem[];
  sections?: HomeSections; topicLabels: Record<string, string>;
}) {
  const words = homeWords(locale);
  function rows(values: HomeItem[] | undefined) {
    return values?.length ? values.map(item => <HomeContentCard key={item.id} item={item} locale={locale} />)
      : <p className={styles.sectionEmpty}>{words.sectionEmpty}</p>;
  }
  return <div className={`${styles.home} public-readable`}>
    <section className={styles.intro}><h1>{headline.map((line, i) => <span key={i}>{line}</span>)}</h1><p>{intro}</p></section>
    <HomeFeaturedCarousel key={locale} items={items} locale={locale} />
    <section className={styles.deadline} aria-labelledby="home-deadline-title">
      <h2 id="home-deadline-title">{words.deadline}</h2>
      <div>{sections?.deadline.length ? rows(sections.deadline) : <p>{words.deadlineEmpty} <Link href="/info/category/program">{words.programList}<HomeArrow /></Link></p>}</div>
    </section>
    <section className={styles.topicStrip} aria-labelledby="home-browse-title"><h2 id="home-browse-title">{words.browse}</h2>
      <nav aria-label={words.browse}>{['culture_experience', 'language_learning', 'employment_career'].map(topic =>
        <Link key={topic} href={`/info/category/program?topic=${topic}`}>{topicLabels[topic]}<HomeArrow /></Link>)}</nav>
    </section>
    <div className={styles.homeBody}>
      <section className={styles.experiences} aria-labelledby="home-experiences-title">
        <div className={styles.sectionHeading}><h2 id="home-experiences-title">{words.experiences}</h2><Link href="/info/category/program">{words.morePrograms}<HomeArrow /></Link></div>
        <div className={styles.experienceItems}>{rows(sections?.experiences)}</div>
      </section>
      <div className={styles.rail}>
        <HomeFinder locale={locale} />
        <aside className={styles.mailbox} aria-labelledby="home-mail-title">
          <MailboxIllustration className={mailbox.illustration} />
          <div><h2 id="home-mail-title">{words.mailTitle}</h2><p>{words.mailBody}</p><Link href="/feedback">{words.mailAction}<HomeArrow /></Link></div>
        </aside>
      </div>
      <section className={styles.learning} aria-labelledby="home-learning-title"><div className={styles.sectionHeading}>
        <h2 id="home-learning-title">{words.learning}</h2></div>{rows(sections?.learning)}
        <Link className={styles.sectionMore} href="/info/category/program?topic=language_learning">{words.morePrograms}<HomeArrow /></Link>
      </section>
    </div>
    <section className={styles.events} aria-labelledby="home-events-title"><div className={styles.sectionHeading}>
      <h2 id="home-events-title">{words.events}</h2><Link href="/info/category/event">{words.moreEvents}<HomeArrow /></Link>
    </div>{rows(sections?.events)}</section>
    <p className={styles.bottomNote}>{words.note}</p>
  </div>;
}
