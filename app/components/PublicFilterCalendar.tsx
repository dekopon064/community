'use client';

import { useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import styles from './PublicCurationFilters.module.css';

// Calendar navigation only. Matching published event occurrences stays in publicContentFilters.
const dateObject = (value: string) => new Date(`${value}T12:00:00Z`);
const dateValue = (value: Date) => value.toISOString().slice(0, 10);
function shiftMonth(value: string, amount: number) {
  const date = dateObject(value), day = date.getUTCDate();
  date.setUTCDate(1);
  date.setUTCMonth(date.getUTCMonth() + amount);
  const last = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate();
  date.setUTCDate(Math.min(day, last));
  return dateValue(date);
}

export default function PublicFilterCalendar({ value, today, onChange }: { value: string; today: string; onChange: (value: string) => void }) {
  const locale = useLocale(), t = useTranslations('PublicFilters');
  const [cursor, setCursor] = useState(value || today);
  const root = useRef<HTMLDivElement>(null);
  const month = cursor.slice(0, 7), [year, monthNumber] = month.split('-').map(Number);
  const first = new Date(Date.UTC(year, monthNumber - 1, 1));
  const days = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
  const formatter = new Intl.DateTimeFormat(locale === 'ja' ? 'ja-JP' : 'ko-KR', { timeZone: 'UTC', year: 'numeric', month: 'long' });
  const dayFormatter = new Intl.DateTimeFormat(locale === 'ja' ? 'ja-JP' : 'ko-KR', { timeZone: 'UTC', dateStyle: 'full' });
  const weekdayFormatter = new Intl.DateTimeFormat(locale === 'ja' ? 'ja-JP' : 'ko-KR', { timeZone: 'UTC', weekday: 'short' });
  const weekdays = Array.from({ length: 7 }, (_, index) => weekdayFormatter.format(new Date(Date.UTC(2023, 9, 1 + index))));
  function focusDay(next: string) {
    setCursor(next);
    requestAnimationFrame(() => root.current?.querySelector<HTMLButtonElement>(`[data-date="${next}"]`)?.focus({ preventScroll: true }));
  }
  function move(event: KeyboardEvent<HTMLButtonElement>, date: string) {
    const next = dateObject(date);
    let destination: string;
    switch (event.key) {
      case 'ArrowLeft': next.setUTCDate(next.getUTCDate() - 1); break;
      case 'ArrowRight': next.setUTCDate(next.getUTCDate() + 1); break;
      case 'ArrowUp': next.setUTCDate(next.getUTCDate() - 7); break;
      case 'ArrowDown': next.setUTCDate(next.getUTCDate() + 7); break;
      case 'Home': next.setUTCDate(next.getUTCDate() - next.getUTCDay()); break;
      case 'End': next.setUTCDate(next.getUTCDate() + 6 - next.getUTCDay()); break;
      case 'PageUp': destination = shiftMonth(date, -1); break;
      case 'PageDown': destination = shiftMonth(date, 1); break;
      default: return;
    }
    event.preventDefault();
    destination ??= dateValue(next);
    if (destination >= '1900-01-01' && destination <= '2199-12-31') focusDay(destination);
  }
  const weeks = Array.from({ length: Math.ceil((first.getUTCDay() + days) / 7) }, (_, week) => Array.from({ length: 7 }, (_, column) => week * 7 + column - first.getUTCDay() + 1));
  return <div ref={root} className={styles.calendar}>
    <p className={styles.note}>{t('dateHelp')}</p>
    <div className={styles.calendarHeading}>
      <button type="button" className={styles.iconButton} aria-label={t('previousMonth')} disabled={month === '1900-01'} onClick={() => setCursor(shiftMonth(`${month}-01`, -1))}><ChevronLeft size={16} aria-hidden="true" /></button>
      <span className={styles.calendarMonth} aria-live="polite">{formatter.format(first)}</span>
      <button type="button" className={styles.iconButton} aria-label={t('nextMonth')} disabled={month === '2199-12'} onClick={() => setCursor(shiftMonth(`${month}-01`, 1))}><ChevronRight size={16} aria-hidden="true" /></button>
    </div>
    <table role="grid" aria-label={`${formatter.format(first)} ${t('date')}`}>
      <thead><tr>{weekdays.map(day => <th key={day} scope="col">{day}</th>)}</tr></thead>
      <tbody>{weeks.map((week, index) => <tr key={index}>{week.map((day, column) => {
        if (day < 1 || day > days) return <td key={column} />;
        const date = `${month}-${String(day).padStart(2, '0')}`;
        return <td key={column}><button type="button" className={styles.calendarDay} data-date={date} tabIndex={date === cursor ? 0 : -1} aria-label={dayFormatter.format(dateObject(date))} aria-pressed={value === date} aria-current={date === today ? 'date' : undefined} onFocus={() => setCursor(date)} onKeyDown={event => move(event, date)} onClick={() => { setCursor(date); onChange(value === date ? '' : date); }}>{day}</button></td>;
      })}</tr>)}</tbody>
    </table>
    <div className={styles.calendarSelection}>
      <span>{value ? `${t('selectedDate')} ${value.replaceAll('-', '.')}` : t('chooseDate')}</span>
      {value && <button type="button" className={styles.clearDate} onClick={() => { onChange(''); focusDay(cursor); }}>{t('clearDate')}</button>}
    </div>
  </div>;
}
