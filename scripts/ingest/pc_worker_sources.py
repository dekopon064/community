"""One data-only catalog shared with the admin UI. Never imports executable paths."""
import json
from pathlib import Path

_rows=json.loads((Path(__file__).resolve().parents[2]/'app/lib/pc-worker/sources.json').read_text(encoding='utf-8'))
if (not isinstance(_rows,list) or not 1<=len(_rows)<=25
    or any(not isinstance(r,dict) or set(r)!={'id','label','collector','ai','collectionHint'}
           or any(not isinstance(v,str) or not v for v in r.values()) for r in _rows)
    or len({r['id'] for r in _rows})!=len(_rows)):
    raise ValueError('invalid_worker_catalog')
SOURCES={r['id']:r for r in _rows}
CATALOG='|'.join(':'.join((r['id'],r['collector'],r['ai'])) for r in _rows)


def collection_sources(source):
    if source=='all':return tuple(SOURCES)
    if source not in SOURCES:raise ValueError('unsupported_worker_source')
    return (source,)
