"""Bounded public-text excerpts for private candidate review, never error logs.

Coordinates are read only against the output that was just checked. They must
never be used to locate text in a subsequently edited candidate.
"""
from ingest.body_markdown import read_body
from ingest.ai_errors import ValidationError


def excerpt(text, location):
    try:
        if location.get('table'):
            table = read_body(text).tables[location['table'] - 1]
            row = table.headers if location.get('row') == 0 else table.rows[location['row'] - 1]
            return row[location['column'] - 1]
        if location.get('item'):
            return read_body(text).items[location['item'] - 1].text
        if location.get('line'):
            return text.splitlines()[location['line'] - 1]
        if location.get('field') in ('title', 'title_ja'):
            return text
    except (ValidationError, IndexError, KeyError, TypeError):
        pass
    return None


def attach_context(issues, output, source):
    budget = 12000  # UTF-8 bytes; do not multiply full responses into each issue.
    for issue in issues:
        if issue['stage'] != 'japanese_validation':
            continue  # Earlier KO checks can precede assembly; never guess positions.
        loc = issue.get('location', {})
        field = 'titleJa' if loc.get('field') in ('title', 'title_ja') else 'contentJa'
        candidate = excerpt(output[field], loc)
        reference = None if loc.get('line') else excerpt(output['titleKo' if field == 'titleJa' else 'contentKo'], loc)
        context = {'field': field}
        for key, value in (('candidate', candidate), ('reference', reference)):
            if isinstance(value, str) and 0 < len(value.strip()) <= 500:
                size = len(value.encode('utf-8'))
                if size <= budget:
                    context[key] = value.strip()
                    budget -= size
        if len(context) > 1:
            issue['context'] = context
        # A translated line number has no relationship to a source line number.
        # Only reuse a literal source match, never label the Korean summary as source.
        if reference and len(reference.strip()) <= 500 and reference.strip() in source:
            issue['evidence'] = reference.strip()
