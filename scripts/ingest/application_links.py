"""Public application URL display normalization; no fetches or fact mutations.

Remove only explicit click/campaign tracking keys. Unknown query components
remain byte-for-byte, including duplicates, encoding, order and empty values.
Signed query strings are opaque and are not rewritten.
"""
from __future__ import annotations

import re
from urllib.parse import unquote_plus, urlsplit

_TRACKING_KEYS = frozenset({
    'fbclid', 'gclid', 'dclid', 'msclkid', 'gbraid', 'wbraid',
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
})
_SIGNATURE_KEYS = frozenset({'sig', 'signature', 'hmac', 'x-amz-signature', 'x-goog-signature'})


def normalize_application_link(value: str) -> str:
    """Do not expand short links, infer equivalence or rewrite unknown keys."""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or re.search(r'[\s\x00-\x1f\x7f]', value)):
        return value
    base, fragment_sep, fragment = value.partition('#')
    location, query_sep, query = base.partition('?')
    if not query_sep:
        return value
    components = query.split('&')
    names = [unquote_plus(part.partition('=')[0]).casefold() for part in components]
    if any(name in _SIGNATURE_KEYS for name in names):
        return value
    kept = [part for part, name in zip(components, names) if name not in _TRACKING_KEYS]
    if len(kept) == len(components):
        return value
    return location + ('?' + '&'.join(kept) if kept else '') + (fragment_sep + fragment if fragment_sep else '')


def normalize_application_links(values: list[str]) -> list[str]:
    """Stable exact deduplication after tracking removal, without input mutation."""
    return list(dict.fromkeys(normalize_application_link(value) for value in values))


def normalize_application_link_text(text: str, links: list[str]) -> str:
    """Replace only complete, known application URLs; leave other links alone."""
    known = set(normalize_application_links(links))
    if not known:
        return text
    def replace(match):
        original = match[0]
        value, suffix = original, ''
        while value:
            normalized = normalize_application_link(value)
            if normalized in known:
                return normalized + suffix
            # Check the complete token first, so literal URL punctuation is
            # retained when it belongs to the known query value/fragment.
            if value[-1] not in ').。,、':
                break
            suffix = value[-1] + suffix
            value = value[:-1]
        return original
    return re.sub(r'https?://[^\s<>"\'\[\]]+', replace, text)


def application_link_facts_view(facts: dict) -> dict:
    """A read-only presentation copy for summary input and protected body text."""
    links = facts.get('application_links', [])
    if not links:
        return facts
    view = dict(facts, application_links=normalize_application_links(links))
    if isinstance(facts.get('description'), str):
        view['description'] = normalize_application_link_text(facts['description'], links)
    for field in ('application_methods', 'conditions'):
        if isinstance(facts.get(field), list):
            view[field] = [normalize_application_link_text(value, links) for value in facts[field]]
    return view
