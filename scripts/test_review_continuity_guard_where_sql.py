"""Regression for the private rollback fence; uses an existing isolated DB only."""
import argparse
import json
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--database', required=True)
args = parser.parse_args()
assert args.database.startswith('review_continuity_') and args.database.replace('_', '').isalnum()
container = 'machimoa-saved-count-sql-20261009-56ca9041'

def docker(parts, body=None):
    result = subprocess.run(['docker', *parts], input=body.encode() if body else None, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode())
    return result.stdout.decode().strip()

metadata = json.loads(docker(['inspect', container]))[0]
assert metadata['State']['Running'] and metadata['HostConfig']['NetworkMode'] == 'none'
assert not metadata['HostConfig']['PortBindings']
assert metadata['Config']['Labels']['machimoa.purpose'] == 'saved-count-sql-validation'
assert all(m['Type'] == 'volume' and m['Name'] == container + '-data' for m in metadata['Mounts'])
assert json.loads(docker(['context', 'inspect']))[0]['Endpoints']['docker']['Host'] == 'npipe:////./pipe/dockerDesktopLinuxEngine'

def sql(query):
    return docker(['exec', '-i', container, 'psql', '-XqAt', '-U', 'postgres', '-d', args.database,
                   '-v', 'ON_ERROR_STOP=1'], query)

checks = 0

def ok(condition):
    global checks
    assert condition
    checks += 1

def deny(query, message):
    global checks
    try:
        sql(query)
    except RuntimeError as error:
        assert message in str(error), str(error)
        checks += 1
    else:
        raise AssertionError('expected ' + message)

root = Path(__file__).resolve().parents[1]
up = (root / 'supabase/migrations/20261010114109_review_continuity_guard_where.sql').read_text(encoding='utf-8')
down = (root / 'supabase/rollback/20261010114109_review_continuity_guard_where_down.sql').read_text(encoding='utf-8')
ok('set dirty=true where singleton=true;' in up)
deny("begin;alter function machimoa_review.review_continuity_dirty() set search_path='public';" + up,
     'continuity_where_predecessor_changed')
deny('begin;alter table machimoa_review.review_classifications disable trigger review_continuity_dirty;' + up,
     'continuity_where_triggers_changed')
sql(up)
deny(up, 'continuity_where_predecessor_changed')
ok('where singleton=true;' in sql("select pg_get_functiondef('machimoa_review.review_continuity_dirty()'::regprocedure);"))
for role in ('anon', 'authenticated', 'service_role'):
    ok(sql("select has_function_privilege('" + role + "','machimoa_review.review_continuity_dirty()','execute');") == 'f')
sql(down)
ok('where singleton=true;' not in sql("select pg_get_functiondef('machimoa_review.review_continuity_dirty()'::regprocedure);"))
sql(up)
for table in ('review_classifications', 'review_classification_history', 'source_item_content_filters',
              'myseoul_residence_reviews', 'myseoul_fact_edits', 'source_item_program_facts'):
    # A zero-row statement still fires the fence; rolling back also rolls back the fence.
    ok(sql('begin;update machimoa_review.' + table + ' set ' +
           ('event_id=event_id' if table == 'myseoul_fact_edits' else 'source_item_id=source_item_id') +
           ' where false;select dirty from machimoa_review.review_continuity_install where singleton;rollback;') == 't')
    ok(sql('select dirty from machimoa_review.review_continuity_install where singleton;') == 'f')
sql('update machimoa_review.review_classifications set source_item_id=source_item_id where false;')
deny(down, 'continuity_where_records_present')
ok('where singleton=true;' in sql("select pg_get_functiondef('machimoa_review.review_continuity_dirty()'::regprocedure);"))
print(json.dumps({'checks': checks, 'database': args.database, 'result': 'passed',
                  'safeupdateExtensionAvailable': False, 'actualContentWrites': 0}))
