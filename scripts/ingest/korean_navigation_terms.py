"""Exact Korean UI/search literals in Japanese application guidance only.

No inferred proper-name exception: literals must be quoted in the Korean
instructions with an explicit search/selection role and quoted again in a
Japanese instruction. This module never changes stored text.
"""
import re

HANGUL = re.compile(r'[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]')
_QUOTED = re.compile(r'‘([^’\n]{1,80})’|「([^」\n]{1,80})」|"([^"\n]{1,80})"|\x27([^\x27\n]{1,80})\x27')
_SECTION = re.compile(r'^\s*\[[^\]\n]+\]\s*$')
_KO_AFTER = re.compile(r'^\s*(?:(?:을|를|으로|로)\s*(?:검색|입력|선택|클릭)|에서\s*[^.!?。\n‘’「」]{0,40}선택|(?:메뉴|탭|버튼|예약\s*항목)(?:에서|으로|을|를|에|\s|$))')
_KO_BEFORE = re.compile(r'(?:검색어|검색\s*입력어|메뉴명|메뉴|탭|버튼|예약\s*항목명|예약\s*항목)\s*[:：]?\s*$')
_JA_AFTER = re.compile(r'^\s*(?:[（(][^()（）\n]{1,80}[）)]\s*)?(?:(?:を|で|と)\s*(?:検索|入力|選択|クリック)|で[^.!?。\n「」]{0,40}選択|(?:メニュー|タブ|ボタン|予約項目)(?:を|から|で|に|へ|の|\s|$))')
_JA_BEFORE = re.compile(r'(?:検索語|検索キーワード|入力語|メニュー名|メニュー|タブ|ボタン|予約項目名|予約項目)\s*[:：]?\s*$')


def _eligible_lines(text, headers):
    """With structured bodies, never authorize quotes outside application."""
    lines = text.splitlines(keepends=True)
    structured = any(_SECTION.fullmatch(line.strip()) for line in lines)
    active = not structured
    offset = 0
    for line in lines:
        if _SECTION.fullmatch(line.strip()):
            active = line.strip() in headers
        elif active:
            yield offset, line
        offset += len(line)


def _literals(text, headers, before, after, conjunction):
    for offset, line in _eligible_lines(text, headers):
        # Do not interpret opaque links, code or table cells as UI instructions.
        if '://' in line or '`' in line or '|' in line:
            continue
        matches = list(_QUOTED.finditer(line))
        accepted = set()
        for index in range(len(matches) - 1, -1, -1):
            match = matches[index]
            term = next(v for v in match.groups() if v is not None)
            if (HANGUL.search(term) and term == term.strip()
                    and not re.search(r'[<>\[\]{}\\\x00-\x1f]', term)
                    and (before.search(line[:match.start()]) or after.match(line[match.end():])
                         or (index + 1 in accepted and re.fullmatch(conjunction,
                             line[match.end():matches[index + 1].start()])))):
                accepted.add(index)
        for index in sorted(accepted):
            match = matches[index]
            yield next(v for v in match.groups() if v is not None), offset + match.start(), offset + match.end()


def navigation_literals(korean):
    return list(_literals(korean, {'[신청 방법]'}, _KO_BEFORE, _KO_AFTER, r'\s*(?:또는|혹은|및|와|과)\s*'))


def checked_navigation_texts(korean, japanese):
    """Return validation-only views and missing exact literals; no rewrites."""
    source = navigation_literals(korean)
    terms = {term for term, _, _ in source}
    target = [entry for entry in _literals(japanese, {'[申請方法]', '[申込方法]'}, _JA_BEFORE, _JA_AFTER,
                                          r'\s*(?:または|もしくは|と|及び|および)\s*')
              if entry[0] in terms]
    def mask(text, entries):
        for _, start, end in sorted(entries, key=lambda item: item[1], reverse=True):
            text = text[:start] + (' ' * (end - start)) + text[end:]
        return text
    return mask(korean, source), mask(japanese, target), sorted(terms - {t for t, _, _ in target})
