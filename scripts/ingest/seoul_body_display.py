"""Seoul public prose cleanup only; original facts/conditions remain immutable."""
import re
from ingest.body_markdown import inline_text

_TARGET = r'(?:참가\s*대상|대상)'
_CAPACITY = r'(?:참가\s*인원|모집\s*인원|정원)'
_QUANTITY = r'(?:(?:\d+\s*)?회(?:차)?\s*당\s*)?\d+\s*명(?:\s*[·–—-]\s*\d+\s*가족)?'


def _plain(text):
    return re.sub(r'^\s*[-*■]\s*', '', inline_text(text)).strip()


def _key(text):
    # Explicit people/family pairs only; do not normalize arbitrary ranges/URLs.
    text=re.sub(r'\s+', '', text)
    return re.sub(r'(?<=명)[·–—-](?=\d+가족)', '·', text)


def clean_fact_repetitions(content: str, sections: dict, facts: dict) -> tuple[str,dict]:
    """Remove only exact simple facts duplicated by authoritative public rows.

    Compound conditions, continuations, tables, URLs and the one-line summary
    stay. A venue sentence is removed only as a complete independently matched
    sentence; no substring deletion from a mixed obligation.
    """
    targets=set(); capacities=set()
    for value in [facts['target_raw'], *facts['conditions']]:
        value=_plain(value)
        target=re.fullmatch(rf'{_TARGET}\s*[:：]\s*(.+)',value)
        if target: targets.add(_key(target[1]))
        elif value==facts['target_raw']: targets.add(_key(value))
        capacity=re.match(rf'{_CAPACITY}\s*[:：]\s*({_QUANTITY})(?=$|\s*[（(])',value)
        if capacity: capacities.add(_key(capacity[1]))
    venues=facts['activity_evidence']
    section=None; lines=[]
    original=content.splitlines()
    for index,line in enumerate(original):
        header=re.fullmatch(r'\s*\[[^\]]+\]\s*',line)
        if header: section=line.strip()
        continuation=index+1<len(original) and original[index+1][:1].isspace() and original[index+1].strip()
        if header or section=='[한 줄 요약]' or '|' in line or line[:1].isspace() or continuation:
            lines.append(line);continue
        plain=_plain(line)
        target=re.fullmatch(rf'{_TARGET}\s*[:：]\s*(.+)',plain)
        capacity=re.fullmatch(rf'{_CAPACITY}\s*[:：]\s*({_QUANTITY})',plain)
        bare_capacity=re.fullmatch(_QUANTITY,plain)
        if section=='[대상]' and ((target and _key(target[1]) in targets)
                or _key(plain) in targets
                or capacity and _key(capacity[1]) in capacities
                or bare_capacity and _key(plain) in capacities):
            continue
        parts=re.split(r'(?<=[.!?。])(?=\s|$)',line)
        kept=[]
        for part in parts:
            text=_plain(part)
            duplicate=any(re.fullmatch(rf'(?:집결\s*장소|집결|장소)\s*[:：]\s*{re.escape(venue)}',text)
                or re.fullmatch(rf'(?:집결\s*장소|장소)는\s*{re.escape(venue)}(?:입니다|이다)[.。]',text)
                for venue in venues)
            if not duplicate: kept.append(part)
        if kept: lines.append(''.join(kept).strip())
    # Strip only source bullet delimiters nested inside a canonical condition
    # label, so source text does not become "- -" or a second nested list.
    cleaned=dict(sections)
    cleaned['[대상]']=re.sub(r'(\*\*참가 조건:\*\*\s*)[-*■]\s*',r'\1',cleaned['[대상]'])
    return '\n'.join(lines),cleaned
