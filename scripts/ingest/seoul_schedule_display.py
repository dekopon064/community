"""Seoul-only presentation cleanup AFTER fact validation, never stored edits."""
from __future__ import annotations
import re
from datetime import date, datetime, timezone, timedelta
from ingest.ai_errors import AiJobError
from ingest.body_markdown import inline_text, read_body
from ingest.myseoul_ai_support import schedule_values
from ingest.myseoul_content import schedule_block, schedule_lines, _dated_schedule_details
from ingest.translation_validation import _entry
from ingest.translation_validation import _dates_and_times
from ingest.seoul_calendar_sessions import (record_calendar_sessions, session_text,
                                          _DATE as SESSION_DATE, _CLOCK as SESSION_CLOCK)

_SECTION = re.compile(r'(?ms)(^[ \t]*\[일정 안내\][ \t]*)(.*?)(?=^[ \t]*\[|\Z)')
_DATE = r'(?:\d{4}-\d{2}-\d{2}|(?:\d{4}\s*년\s*)?\d{1,2}\s*월\s*\d{1,2}\s*일)'
_CLOCK = r'(?:\d{1,2}:[0-5]\d(?::[0-5]\d)?|\d{1,2}\s*시(?!간)(?:\s*[0-5]?\d\s*분)?)'
_POINT = rf'{_DATE}(?:[T \t]+{_CLOCK})?(?:Z|[+-]\d{{2}}:?\d{{2}})?'
_RANGE = re.compile(rf'{_POINT}\s*(?:~|～|〜|–|—|-)\s*{_POINT}')
_APPLICATION = r'신청\s*기간|접수\s*기간|접수|신청'
_OPERATION = r'진행\s*기간|운영\s*기간|개최\s*기간|운영'


def _plain(line: str) -> str:
    return re.sub(r'^\s*[-+*]\s+', '', inline_text(line)).strip()


def normalize_period_labels(content: str) -> str:
    """Expose aliases to the existing role validator BEFORE removing anything."""
    def section(match):
        lines=[]
        for line in match[2].splitlines():
            plain=_plain(line)
            alias=re.fullmatch(rf'({_APPLICATION}|{_OPERATION})\s*[:：]\s*(.+)',plain)
            if alias and re.match(_DATE,alias[2]):
                role='신청기간' if re.fullmatch(_APPLICATION,alias[1]) else '진행기간'
                line=role+': '+alias[2]
            lines.append(line)
        return match[1]+'\n'+'\n'.join(lines).strip()+'\n\n'
    return _SECTION.sub(section,content)


def _table_rows(section: str) -> list[str]:
    result=[]
    for table in read_body(section).tables:
        headers={inline_text(h) for h in table.headers}
        if (headers & {'날짜','일자','수업일','교육일','회차'}
                and headers & {'시간','일시','오전','오후'}):
            result += [' '.join(inline_text(cell) for cell in row) for row in table.rows]
    return result


def _years(view):
    pair = view['periods']['operation'][0]['endpoints']
    return frozenset(range(int(pair[0]['value'][:4]), int(pair[1]['value'][:4])+1))


def _display_values(text, *, years=frozenset()):
    # Keep comparison-only metadata separate from the unchanged public text.
    # Reuse the date/AM-PM parser that already validates calendar table cells.
    values = schedule_values(text)
    parsed = _dates_and_times(text, known_years=years)
    values['dates'] = {v[2:] for v in parsed if v[0]=='date'} | values['dates']
    if re.search(r"\d{4}(?:\s*[년.-])|['’]\d{2}\s*\.", text):
        values['years'] |= {v[1] for v in parsed if v[0]=='date' and v[1] is not None}
    ranges = re.finditer(rf'({SESSION_CLOCK})\s*(?:~|～|〜|–|—|-|부터)\s*({SESSION_CLOCK})', text)
    clocks = [tuple(v for v in _dates_and_times(m[0]) if v[0]=='time') for m in ranges]
    if clocks:
        values['times'] = {tuple(v[1]*60+v[2]+(v[3]/60 if len(v)>3 else 0) for v in pair)
                           for pair in clocks if len(pair)==2}
    return values


def _pure_session(record: str, view: dict) -> bool:
    # Do not remove meeting instructions, activities, per-session conditions or
    # duration/count notes just because a table has the same numeric values.
    text=session_text(record)
    if not _display_values(text, years=_years(view))['dates']:
        return False
    text=re.sub(SESSION_DATE,'',text)
    text=re.sub(SESSION_CLOCK,'',text)
    text=re.sub(r'[（(]\s*[월화수목금토일](?:요일)?\s*[）)]|오전|오후','',text)
    return not text.strip(' \t/.,·、・;；~～〜–—-')


_CHECKIN = re.compile(r'시작\s*(\d+)\s*분\s*(전|후)(?:까지|에)?\s*도착')


def _session_and_checkin(record: str) -> tuple[str,str] | None:
    # A narrowly delimited source record, not arbitrary activity/condition prose.
    text=_plain(record)
    match=re.fullmatch(rf'(?:운영|진행|수업)\s*일시\s*[:：]\s*'
        rf'(?P<session>(?:[월화수목금토일]요일\s*)?[（(]?{_DATE}\s*'
        rf'{_CLOCK}\s*(?:~|～|〜|–|—|-){_CLOCK}[）)]?)\s*'
        r'[（(](?P<note>시간\s*꼭!?\s*준수,\s*시작\s*\d+\s*분\s*전\s*도착요망)[）)]',text)
    return (match['session'],match['note']) if match else None


def validate_checkin(content: str, view: dict) -> None:
    expected={tuple(m.groups()) for record in schedule_lines(view)
              if (parts:=_session_and_checkin(record))
              for m in _CHECKIN.finditer(parts[1])}
    if not expected: return
    for m in _CHECKIN.finditer(inline_text(content)):
        if tuple(m.groups()) not in expected: raise AiJobError('ai_schema_error')


def _covered(values: dict, rows: list[dict], occurrences=None) -> bool:
    if occurrences:
        # Shared-date lists are covered one date at a time, using the same
        # ordered source-clock associations as calendar validation. A global
        # bag of table dates/times cannot cover independently timed sessions.
        return all(any(row['dates']=={day[1:]} and values['years'].issubset(row['years'])
                       and {tuple(v[1]*60+v[2]+(v[3]/60 if len(v)>3 else 0) for v in clocks[i:i+2])
                            for i in range(0,len(clocks),2)}.issubset(row['times'])
                       and ({date(*day).weekday()} if values['weekdays'] and day[0] is not None
                            else values['weekdays']).issubset(row['weekdays'])
                       and values['counts'].issubset(row['counts']) for row in rows)
                   for day,clocks in occurrences if clocks) and all(clocks for _,clocks in occurrences)
    return any(values['dates']==row['dates'] and
        all(values[key].issubset(row[key]) for key in ('years','times','weekdays','counts'))
        for row in rows)


def _operation_period_display(sections: dict, view: dict) -> dict:
    """Separate calendar bounds from independently verified session clocks.

    Never change endpoint precision, application cutoffs or temporal gating.
    Without clear independent sessions, keep all times (including real midnight).
    """
    endpoints=view['periods']['operation']
    if len(endpoints)!=1: return sections
    pair=endpoints[0]['endpoints']
    if any(p.get('precision')=='day' for p in pair): return sections
    try:
        dates=[datetime.fromisoformat(p['value']).astimezone(timezone(timedelta(hours=9))) for p in pair]
    except (ValueError,TypeError): return sections
    if dates[0]>dates[1] or any((d.hour,d.minute,d.second,d.microsecond)!=(0,0,0,0) for d in dates):
        return sections
    start,end=(d.date() for d in dates)
    matrix=view.get('weekly_schedule')
    explicit=[_display_values(record,years=_years(view))['times'] for record in schedule_lines(view)]
    if any(a==0 or b==0 or a>=b for times in explicit for a,b in times):
        return sections
    if matrix:
        # Clocks are taken from the source matrix, not the generated table or
        # ordinary opening/contact hours elsewhere in the description.
        clocks=[tuple(map(int,row[0].split(':'))) for row in matrix.rows]
        if not clocks or any(hour==minute==0 for hour,minute in clocks):
            return sections
    else:
        evidence=[_display_values(record,years=_years(view)) for record in schedule_lines(view)]
        if not evidence or any(not v['dates'] or not v['times']
                or any(a==0 or b==0 or a>=b for a,b in v['times']) for v in evidence):
            return sections
        represented=set()
        for record,values in zip(schedule_lines(view),evidence):
            details=_dated_schedule_details(record,known_years=_years(view))
            for month,day in values['dates']:
                candidates=[]
                for year in range(start.year,end.year+1):
                    try: occurrence=date(year,month,day)
                    except ValueError: continue
                    if start<=occurrence<=end: candidates.append(occurrence)
                matching=[weekdays for dated,weekdays,_ in details if dated==(month,day)]
                weekdays=set().union(*matching) if matching else values['weekdays']
                if (len(candidates)!=1 or values['years']-{candidates[0].year}
                        or weekdays-{candidates[0].weekday()}):
                    return sections
                represented.add(candidates[0])
        if not {start,end}.issubset(represented):
            return sections
    # Only the bare reviewed operation row. Qualified period prose stays intact.
    first,last=start.isoformat(),end.isoformat()
    pattern=rf'(?m)^(- \*\*(?:진행기간|개최 기간):\*\*) {first} 00:00 ~ {last} 00:00$'
    result=dict(sections)
    rendered=first if first==last else first+' ~ '+last
    result['[일정 안내]']=re.sub(pattern,rf'\1 {rendered}',sections['[일정 안내]'])
    return result


def clean_schedule_display(content: str, sections: dict, view: dict) -> tuple[str,dict]:
    """Keep verified session tables and only source records they fully cover.

    Unknown/mixed prose stays. Values are already validated by role/year/date;
    table coverage is per record, not a global numeric-set comparison.
    """
    supplied=sections
    sections=dict(sections)
    match=_SECTION.search(content)
    if not match:
        return content,sections
    original=match[2]
    rows=[_display_values(row) for row in _table_rows(original)]
    records=schedule_lines(view)
    covered=[]
    notes=[]
    for record in records:
        values=_display_values(record,years=_years(view))
        parts=_session_and_checkin(record)
        occurrences=record_calendar_sessions(record,years=_years(view))
        if (_pure_session(record,view) or parts) and _covered(values,rows,occurrences):
            covered.append(record)
            if parts:
                rendered='- **집결 안내:** '+parts[1]
                # A previous projection goes back to its canonical slot on
                # reassembly, rather than moving ahead of the period rows.
                original='\n'.join(line for line in original.splitlines() if line.strip()!=rendered)
                source_checkin=_CHECKIN.search(parts[1]).groups()
                # Only a matching explicit check-in instruction plus time
                # compliance covers this entire note; otherwise copy the note.
                represented=any(m.groups()==source_checkin for m in _CHECKIN.finditer(inline_text(original)))
                if not represented or not re.search(r'준수|시간을?\s*지켜',inline_text(original)):
                    notes.append(parts[1])
    remaining=[record for record in records if record not in covered]
    def remove_block(text):
        block=schedule_block(records)
        return text.replace(block,schedule_block(remaining),1) if block else text
    canonical=remove_block(sections['[일정 안내]'])
    # Exact source/generated table equality only. Do not deduplicate different
    # activities/headers/cell layouts or replace one by reconstructed prose.
    tables=read_body(original).tables
    for table in read_body(canonical).tables:
        if any(table.headers==other.headers and table.rows==other.rows for other in tables):
            canonical=canonical.replace(table.markdown,'',1)
    if notes: canonical+='\n'+'\n'.join('- **집결 안내:** '+n for n in dict.fromkeys(notes))
    sections['[일정 안내]']=canonical.strip()
    sections=_operation_period_display(sections,view)
    roles={role for role,labels in (
        ('신청기간',r'신청\s*기간'),('진행기간',r'진행\s*기간|운영\s*기간|개최\s*기간'))
        if _entry(supplied['[일정 안내]'],labels) is not None}
    lines=[]
    for line in remove_block(original).splitlines():
        plain=_plain(line)
        period=re.fullmatch(r'(신청기간|진행기간)\s*[:：]\s*(.+)',plain)
        if period and period[1] in roles and _RANGE.fullmatch(period[2]):
            continue
        # Internal control metadata is not a public instruction. Keep ordinary
        # Korean-time guidance, opaque URLs/identifiers and mixed source prose.
        if re.fullmatch(r'(?:시간\s*(?:기준|대)|시간대)\s*[:：]\s*Asia/Seoul\.?',plain):
            continue
        if re.fullmatch(r'모든\s*시간은\s*한국시간\s*[（(]Asia/Seoul[）)]입니다\.',plain):
            line='모든 시간은 한국시간입니다.'
        lines.append(line)
    replacement=match[1]+'\n'+'\n'.join(lines).strip()+'\n\n'
    content=content[:match.start()]+replacement+content[match.end():]
    return content,sections
