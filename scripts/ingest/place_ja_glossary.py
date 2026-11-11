"""Verified reusable names; no network lookup or stored-content rewriting."""
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / 'docs/ingest-inputs/place_ja_glossary.v1.json'


@lru_cache(maxsize=1)
def place_entries():
    return tuple(json.loads(_PATH.read_text(encoding='utf-8'))['entries'])


def place_prompt_block():
    lines = ['Verified place/person names (독음: 첫 등장 선택):']
    for entry in place_entries():
        reading = f" / {entry['reading_form']}" if entry.get('reading_form') else ''
        scope = f" [{entry['scope']}]" if entry.get('scope') else ''
        lines.append(f"{entry['ko']} → {entry['ja']}{scope}{reading}")
    return '\n'.join(lines)


def numeric_name_views(korean, japanese):
    """Mask only paired, verified numeric names for the residual digit check.

    Exit, line, clock and unknown-name digits remain intact. Different names,
    reordered names or missing occurrences are not an authorized exception.
    Do not use these comparison views for storage or prompt input.
    """
    entries = [e for e in place_entries() if re.search(r'\d', e['ko'])]
    def normalize(value):
        return unicodedata.normalize('NFKC', value)

    def spans(text, language):
        aliases = {}
        for index, entry in enumerate(entries):
            for name in ([entry['ko']] if language == 'ko' else entry['accepted_ja']):
                aliases[normalize(name)] = index
        pattern = re.compile('|'.join(re.escape(name) for name in sorted(aliases, key=len, reverse=True)))
        # Never interpret parts of an opaque URL as a place name.
        urls = list(re.finditer(r'https?://[^\s]+', text))
        return [(m.start(), m.end(), aliases[m[0]]) for m in pattern.finditer(text)
                if not any(m.start() < u.end() and u.start() < m.end() for u in urls)]

    ko_spans, ja_spans = spans(korean, 'ko'), spans(japanese, 'ja')
    if not ko_spans or [s[2] for s in ko_spans] != [s[2] for s in ja_spans]:
        return korean, japanese
    def mask(text, matches):
        for start, end, _ in reversed(matches):
            text = text[:start] + ' ' * (end - start) + text[end:]
        return text
    return mask(korean, ko_spans), mask(japanese, ja_spans)
