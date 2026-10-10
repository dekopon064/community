"""Fresh synthetic database, existing verified network-none PostgreSQL only."""
import argparse
import json
import subprocess
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
args = argparse.ArgumentParser()
args.add_argument('--container', default='machimoa-program-ai-5689d361')
args.add_argument('--database')
args.add_argument('--setup-only', action='store_true')
args.add_argument('--cases',choices=['all','generic','narrow','public'],default='all')
args.add_argument('--install-new', action='store_true')
args.add_argument('--prepare-tail', action='store_true')
args.add_argument('--fixture-root', type=Path)
ARGS = args.parse_args()

def docker(parts, body=None):
    result = subprocess.run(['docker', *parts], input=body.encode('utf-8') if body is not None else None, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8').strip())
    return result.stdout.decode('utf-8').strip()

resource = json.loads(docker(['inspect', ARGS.container]))[0]
assert resource['State']['Running'] and resource['HostConfig']['NetworkMode'] == 'none'
assert not resource['HostConfig'].get('PortBindings') and not resource['Mounts']
assert resource['Config']['Labels'].get('machimoa.purpose') == 'isolated-program-ai-concurrency'
context = json.loads(docker(['context', 'inspect']))[0]
assert context['Endpoints']['docker']['Host'] == 'npipe:////./pipe/dockerDesktopLinuxEngine'
free = int(docker(['exec', ARGS.container, 'df', '-B1', '/var/lib/postgresql/data']).splitlines()[-1].split()[3])
assert free >= 64 * 1024 * 1024
DB = ARGS.database or 'review_reclass_' + uuid4().hex[:12]
assert DB.startswith('review_reclass_') and DB.replace('_', '').isalnum()

def sql(body):
    return docker(['exec', '-i', ARGS.container, 'psql', '-X', '-U', 'postgres', '-d', DB, '-v', 'ON_ERROR_STOP=1', '-v', 'VERBOSITY=verbose', '-qAt'], body)

if not ARGS.database:
    docker(['exec', ARGS.container, 'createdb', '-U', 'postgres', DB])
    print(json.dumps({'newDatabase': DB, 'freeBytes': free}), flush=True)
    sql("""do $$ begin
    if not exists(select 1 from pg_roles where rolname='anon') then create role anon;end if;
    if not exists(select 1 from pg_roles where rolname='authenticated') then create role authenticated;end if;
    if not exists(select 1 from pg_roles where rolname='service_role') then create role service_role bypassrls;end if;
    end $$;
    create table public.curations(id uuid primary key default gen_random_uuid(),slug text not null unique,category text,title text not null,summary text,content text not null,created_at timestamptz not null default now());
    alter table public.curations enable row level security;
    insert into public.curations(slug,title,summary,content) values('baseline-one','one','one','one'),('baseline-two','two','two','two');
    """)
if not ARGS.database or ARGS.prepare_tail:
    folder = ROOT / 'supabase/migrations'
    def predecessor(name):
        target = folder / name
        if not target.exists() and ARGS.fixture_root:
            target = ARGS.fixture_root / 'supabase/migrations' / name
        return target.read_text(encoding='utf-8')
    # Same dependency installation path as the established My서울 SQL fixture.
    predecessors = sorted(p for p in folder.glob('*.sql') if
        '20260827022301' <= p.name < '20260903' or '20260913' <= p.name <= '20261001000001_seoul_program_ai.sql')
    predecessors += [folder / name for name in [
        '20261002000000_admin_review_ai_queue.sql', '20261002000100_admin_review_trash.sql',
        '20261002000200_admin_review_trash_publication.sql', '20261002000300_myseoul_program_contract.sql',
        '20261002000400_myseoul_program_ai.sql', '20261003000000_source_images.sql',
        '20261003000001_myseoul_change_collection.sql', '20261003000100_myseoul_list_discovery.sql',
        '20261003000200_myseoul_source_images.sql', '20261003000300_myseoul_candidate_images.sql',
        '20261003000400_myseoul_review_simplify.sql',
        '20261004000000_myseoul_ai_pre_application.sql', '20261004000100_myseoul_candidate_notice_input.sql',
        '20261005000000_common_pre_application_publish.sql', '20261005055032_myseoul_venue_confirmation.sql',
        '20261006022909_myseoul_plain_text_heading.sql']]
    if ARGS.prepare_tail:
        predecessors = [p for p in predecessors if p.name >= '20261004000000']
    for p in predecessors:
        try:
            sql(predecessor(p.name))
            if p.name.startswith('20260827022301'):
                sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status) select 'youthcenter','baseline-'||n,repeat('a',64),'candidate-'||n,'title','summary','content','{}','success' from generate_series(1,4)n;")
        except RuntimeError as e:
            print('predecessor installation stopped:', p.name, flush=True)
            raise e
    # Reuse the exact local metadata fixture used by the prior filter SQL checks.
    # This is NOT a Production read or a guard alteration.
    temp = Path.home() / 'AppData/Local/Temp'
    dismissal = json.loads((temp/'machimoa_admin_ops_dismiss_20261006.json').read_text(encoding='utf-8'))
    sql(';\n'.join(dismissal[0]['statements'])+';')
    definitions = json.loads((temp/'machimoa_admin_ops_current_defs_20261006.json').read_text(encoding='utf-8'))
    for definition in definitions.values():
        if definition: sql(definition+';')
    for name in ['20261006051000_admin_operations_myseoul_trash.sql', '20261006090222_reviewed_content_temporal_processing.sql', '20261007090144_content_filter_contract.sql', '20261007115846_content_filter_registration_attempts.sql']:
        sql(predecessor(name))
if ARGS.install_new:
    sql((ROOT/'supabase/migrations/20261010013000_review_reclassification.sql').read_text(encoding='utf-8'))
if ARGS.setup_only:
    print('isolated predecessor installation complete', flush=True)
else:
    from test_review_reclassification_cases import run_cases
    run_cases(sql, ROOT, ARGS.cases)
