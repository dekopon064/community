"""Enrich only a positionless week matrix with a corroborated own-detail table."""
from dataclasses import replace
import hashlib
import re

from ingest.ai_errors import AiJobError
from ingest.connectors.seoul_reservation import parse_body
from ingest.http_client import HttpBudgetExhausted, HttpRequestFailed, HttpStatusError, ResponseTooLarge, read_html_once
from ingest.seoul_fact_roles import WEEKDAY, key, weekly_schedule


def supplement_weekly_table(record, http):
    payload = record.normalized_payload
    text = payload['program_text']
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if re.fullmatch(r'\s*시간\s*[/·]\s*요일\s*', line)]
    if len(starts) != 1 or payload.get('source_link', {}).get('kind') != 'reservation_detail':
        return record
    try:
        flat = weekly_schedule(text)
    except AiJobError:
        return record
    if not flat or not flat.flattened or not http.remaining():
        return record
    url = 'https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=' + record.external_key
    try:
        html, _, _ = read_html_once(http, url)
        tables = parse_body(html)['tables']
    except (HttpBudgetExhausted, HttpRequestFailed, HttpStatusError, ResponseTooLarge, UnicodeError, ValueError):
        return record
    candidates = []
    for table in tables:
        if not table or len(table) != len(flat.rows) + 1 or any(len(row) != len(flat.headers) for row in table):
            continue
        if any(c['rowspan'] != 1 or c['colspan'] != 1 or c.get('nested_tables') for row in table for c in row):
            continue
        header, *rows = [[c['text'] for c in row] for row in table]
        if not re.fullmatch(r'시간(?:\s*[/·]\s*요일)?', header[0]) or tuple(header[1:]) != flat.headers[1:]:
            continue
        if any(not re.fullmatch(WEEKDAY, h) for h in header[1:]):
            continue
        if any([key(c) for c in r if c.strip()] != [key(c) for c in f] for r, f in zip(rows, flat.rows)):
            continue
        matrix = [header, ['---'] * len(header), *rows]
        markdown = '\n'.join('| ' + ' | '.join((c or '—').replace('|', r'\|') for c in r) + ' |' for r in matrix)
        candidates.append(markdown)
    if len(candidates) != 1:
        return record
    start = starts[0]
    remaining = ''.join(key(cell) for row in (flat.headers[1:], *flat.rows) for cell in row)
    for end in range(start + 1, len(lines)):
        token = key(lines[end])
        if not remaining.startswith(token):
            return record
        remaining = remaining[len(token):]
        if not remaining:
            table = candidates[0]
            updated = ''.join(lines[:start]) + '\n' + table + '\n\n' + ''.join(lines[end + 1:])
            digest = hashlib.sha256((record.revision_hash + '\n' + table).encode()).hexdigest()
            return replace(record, revision_hash=digest, normalized_payload={
                **payload, 'program_text': updated, 'weekly_table_supplement': {'url': url, 'table': table}})
    return record
