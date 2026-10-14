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


def _eligibility_atom(text):
    """Bounded complete clauses; qualifiers/negation are part of the key."""
    value=_key(_plain(text)).strip(' .。')
    group=r'(성인|청년|청소년|어린이|유아|어르신)'
    action=r'(?:신청|참가|참여)(?:[·/](?:신청|참가|참여))*'
    match=re.fullmatch(group+r'만'+action+r'(?:가|이)?(?:가능(?:합니다)?|할수있습니다)',value)
    if match:return ('exclusive_audience',match[1])
    if re.fullmatch(r'이전회차(?:참여자|참가자)(?:는|은)?'+action+
                    r'(?:가|이)?(?:불가(?:합니다)?|할수없습니다)',value):
        return ('previous_session_participant','denied')
    if re.fullmatch(r'선착순(?:으로)?(?:접수|신청)(?:합니다)?',value):
        return ('selection_order','first_come')
    return None


def _audience_atom(text):
    value=_key(text)
    match=re.fullmatch(r'(성인|청년|청소년|어린이|유아|어르신)[（(](.+)[）)]',value)
    if match and _eligibility_atom(match[2])==('exclusive_audience',match[1]):
        return ('exclusive_audience',match[1])
    return None


def _participation_bundle(text):
    """Only explicitly delimited source capacity + fully recognized rules.

    If any tail is unknown (proof, residence, guardian, refund, etc.), retain
    the entire compound row. Never trim an unknown qualifier to deduplicate it.
    """
    match=re.fullmatch(rf'ㅇ?\s*{_CAPACITY}\s*[:：]\s*({_QUANTITY})\s*[（(](.+)',text)
    if not match:return None
    tail=match[2].rstrip(' )）').strip()
    parts=[p.strip() for p in re.split(r'\*|[,，]',tail) if p.strip()]
    result=[(('capacity',_key(match[1])),match[1],'모집 인원')]
    for part in parts:
        atom=_eligibility_atom(part)
        if atom is None:return None
        result.append((atom,part,'참가 조건'))
    return result if parts else None


def _clean_participation_rows(content, sections):
    from ingest.seoul_fact_roles import optional_section
    body=optional_section(content,'[대상]')
    own={_key(_plain(line)) for line in sections['[대상]'].splitlines() if line.strip()}
    proof='\n'.join(line for line in body.splitlines() if _key(_plain(line)) not in own
                    and '|' not in line and not line[:1].isspace())
    clauses=re.split(r'(?:하며|이고|이며|하고),?\s*|[,，]\s*|(?<=[.!?。])\s+',inline_text(proof))
    covered={atom for clause in clauses if (atom:=_eligibility_atom(clause))}
    # Application order belongs to the booking method as well; require an
    # explicit complete positive clause, not a contact or negated method.
    method=optional_section(content,'[신청 방법]')
    method_clauses=re.split(r'(?:하며|이고|이며|하고),?\s*|[,，]\s*|(?<=[.!?。])\s+',inline_text(method))
    if any(_eligibility_atom(clause)==('selection_order','first_come') for clause in method_clauses):
        covered.add(('selection_order','first_come'))
    result=dict(sections);kept=[];removed=[]
    rows=sections['[대상]'].splitlines()
    for index,line in enumerate(rows):
        continuation=index+1<len(rows) and rows[index+1][:1].isspace() and rows[index+1].strip()
        if '|' in line or line[:1].isspace() or continuation:
            kept.append(line);continue
        value=_plain(line)
        audience=re.fullmatch(r'대상\s*[:：]\s*(.+)',value)
        if audience and (atom:=_audience_atom(audience[1])) and atom in covered:
            removed.append(line);continue
        condition=re.fullmatch(r'참가 조건\s*[:：]\s*(.+)',value)
        bundle=_participation_bundle(condition[1]) if condition else None
        if bundle:
            removed.append(line)
            kept.extend('- **'+label+':** '+text for atom,text,label in bundle if atom not in covered)
        else:kept.append(line)
    result['[대상]']='\n'.join(dict.fromkeys(kept))
    # On reassembly replace only exact old canonical bundle/target rows, not a
    # generated paragraph that happens to contain some of the same words.
    if removed:
        keys={_key(_plain(line)) for line in removed}
        new_body='\n'.join(line for line in body.splitlines() if _key(_plain(line)) not in keys)
        pattern=r'(?ms)(^[ \t]*\[대상\][ \t]*)(.*?)(?=^[ \t]*\[|\Z)'
        content=re.sub(pattern,lambda m:m[1]+'\n'+new_body+'\n\n',content,count=1)
    return content,result


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
    return _clean_participation_rows('\n'.join(lines),cleaned)
