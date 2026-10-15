"""Structural source-link validation; never fetch, repair IDs or follow redirects.

Culture listings include links to other institutions. These routes are supported
separately from Seoul's own SVCID detail page. Query values identify the external
service, not a Seoul SVCID; neither registration availability nor reachability is
inferred. Raw provider text remains separate from the usable URL.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit


_EXTERNAL_ROUTES = {
    ('umppa.seoul.go.kr', '/icare/user/chilProgrm/orgideaExprnCtzn/BD_selectOrgideaExprnCtzn.do'):
        ({'q_progrmCl', 'q_placeCode', 'q_progrmSn'}, set()),
    ('kctg.or.kr', '/tour/touristSiteView.do'): ({'tourist_cd'}, {'page_no'}),
    ('www.kctg.or.kr', '/tour/touristSiteView.do'): ({'tourist_cd'}, {'page_no'}),
    ('firesafety.eseoul.go.kr', '/multi/main.do'): (set(), set()),
    ('culture.gangseo.seoul.kr', '/gsfc/education/view.do'): ({'eduSn'}, {'menuNo'}),
}
_AMP = re.compile(r'&(?:amp|#0*38|#x0*26);', re.I)


def seoul_source_link(raw: str, sid: str, *, culture_external: bool = False) -> dict:
    """Return a usable link and its original value, or a fixed safe error.

    Only explicit culture callers may accept external institution routes. The
    legacy connector's own-detail contract is unchanged. HTML ampersands are
    decoded once in the external query only, never percent-decoded as a URL.
    """
    if re.search(r'[\x00-\x1f\x7f]', raw):
        raise ValueError('seoul_link_invalid')
    clean = raw.strip()
    if not clean:
        return dict(url=None, kind='missing', original=raw, ampersand_decoded=False)
    if len(clean) > 2048 or re.search(r'[\s\\\x00-\x1f\x7f]', clean):
        raise ValueError('seoul_link_invalid')
    try:
        u = urlsplit(clean)
        q = parse_qs(u.query)
        own_detail = (u.scheme in {'http', 'https'} and u.netloc == 'yeyak.seoul.go.kr'
            and u.path == '/web/reservation/selectReservView.do'
            and q.get('rsv_svc_id') == [sid] and set(q) == {'rsv_svc_id'} and not u.fragment
            and re.fullmatch(r'https?://yeyak\.seoul\.go\.kr/web/reservation/selectReservView\.do\?rsv_svc_id=[A-Za-z0-9_-]+', clean))
        if own_detail:
            return dict(url=clean, kind='reservation_detail', original=raw, ampersand_decoded=False)
        # A mismatched Seoul detail link is not reclassified as external.
        if not culture_external:
            raise ValueError('seoul_link_invalid')
        # Decode before parsing: the '#' in a numeric ampersand entity is
        # data, not a URL fragment. Only query separators may change.
        prefix, separator, tail = clean.partition('?')
        usable = prefix + separator + _AMP.sub('&', tail)
        u = urlsplit(usable)
        if u.scheme != 'https' or u.fragment:
            raise ValueError('seoul_link_invalid')
        route = _EXTERNAL_ROUTES.get((u.netloc, u.path))
        if route is None:
            raise ValueError('seoul_link_invalid')
        # Parameter names must be literal; percent decoding is only used for
        # typed values by parse_qs, not to disguise routing/redirect keys.
        if any(not re.fullmatch(r'[A-Za-z_]+', pair.partition('=')[0]) for pair in u.query.split('&') if pair):
            raise ValueError('seoul_link_invalid')
        q = parse_qs(u.query, keep_blank_values=True, strict_parsing=True)
        required, optional = route
        if not required <= set(q) <= required | optional or any(len(v) != 1 for v in q.values()):
            raise ValueError('seoul_link_invalid')
        for name, values in q.items():
            value = values[0]
            pattern = r'[A-Za-z0-9_-]{1,128}' if name == 'tourist_cd' else r'[0-9]{1,32}'
            if name == 'page_no' and value == '':
                continue
            if not re.fullmatch(pattern, value):
                raise ValueError('seoul_link_invalid')
        # Preserve scheme/authority/path and every query value/ordering. Only
        # the observed HTML query separator changes in the usable link.
        return dict(url=usable, kind='culture_external', original=raw,
                    ampersand_decoded=usable != clean)
    except (TypeError, ValueError):
        raise ValueError('seoul_link_invalid') from None
