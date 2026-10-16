"""Allowlisted public research output only; never serialize SDK/auth objects."""
import re
from ingest.chatgpt_plan_protocol import get_field


def clean_text(value):
    if not isinstance(value, str):
        return None
    if len(value) > 600_000:
        raise ValueError('diagnostic_too_large')
    value = re.sub(r'(?i)Bearer\s+[^\s"\'<>]+', 'Bearer [REDACTED]', value)
    value = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b|\bsk-[A-Za-z0-9_-]+', '[REDACTED]', value)
    return re.sub(r'(?i)((?:access[_-]?token|refresh[_-]?token|id[_-]?token|api[_-]?key|client[_-]?secret|authorization|password|cookie|token|secret|code)["\']?\s*[:=]\s*["\']?)[^\s"\'&,;}<>]+', r'\1[REDACTED]', value)


def response_record(response):
    if response is None:
        return None
    result = {'model':clean_text(get_field(response,'model')), 'status':clean_text(get_field(response,'status')), 'output':[]}
    output = get_field(response,'output',[]) or []
    if not isinstance(output,list) or len(output)>100:
        raise ValueError('diagnostic_output_invalid')
    for item in output:
        kind = get_field(item,'type')
        row = {'type':clean_text(kind)}
        if kind == 'message':
            row['content'] = []
            for part in get_field(item,'content',[]) or []:
                row['content'].append({'type':clean_text(get_field(part,'type')),
                    'text':clean_text(get_field(part,'text')), 'refusal':clean_text(get_field(part,'refusal')),
                    'citations':[clean_text(get_field(a,'url')) for a in get_field(part,'annotations',[]) or [] if get_field(a,'type')=='url_citation']})
        elif kind == 'web_search_call':
            action=get_field(item,'action')
            row.update(status=clean_text(get_field(item,'status')), action={k:clean_text(get_field(action,k)) for k in ('type','query','url','pattern')},
                sources=[clean_text(get_field(s,'url')) for s in get_field(action,'sources',[]) or []])
        # Never record reasoning contents, encrypted content, IDs, SDK metadata,
        # HTTP bodies/headers, credentials or arbitrary unknown object fields.
        result['output'].append(row)
    return result
