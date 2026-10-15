"""Read a bounded, retained review envelope from stdin and emit previews only.

No environment/auth files, DB, HTTP, AI, writes, or automatic execution adapter.
Context must belong to the same revision AND current description.
"""
import json
import socket
import sys
from unittest.mock import patch

from ingest.seoul_review_connections import propose_connections, same_period_supported


def plan_rows(rows):
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError('bounded_retained_rows_required')
    by_id = {}
    for row in rows:
        if row['id'] in by_id and row != by_id[row['id']]:
            raise ValueError('conflicting_duplicate_review')
        by_id[row['id']] = row
    plans = []
    for row in by_id.values():
        d = row['detail']
        context = row.get('context', {})
        bound = (context.get('revision') == d['revision'] and
                 context.get('description') == d['facts']['description'])
        proposal = propose_connections(d, provider_fields=context.get('provider_fields') if bound else None,
                                       tables=context.get('tables', ()) if bound else (),
                                       operator_fields=row.get('operator_fields', ()))
        proposal.update(id=row['id'], reconfirm_periods=same_period_supported(d['facts']))
        plans.append(proposal)
    return {'count': len(plans), 'plans': plans}


if __name__ == '__main__':
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        data = sys.stdin.buffer.read(10_000_001)
        if len(data) > 10_000_000:
            raise ValueError('retained_input_too_large')
        print(json.dumps(plan_rows(json.loads(data)), ensure_ascii=False))
