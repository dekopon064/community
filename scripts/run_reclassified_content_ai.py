"""Explicit one-target follow-up. Validation only by default; never loads env files."""
from __future__ import annotations
import argparse
import json
import os
from uuid import uuid4
from run_seoul_program_ai import target_id,revision_hash,project_ref

def execute_target(args):
    from ingest.ai_provider import require_configured_provider
    from ingest.ai_claude import ClaudeAdapter,CLAUDE_JOB_USD_CAP,MAX_CREATE_CALLS
    from ingest.program_ai import ProgramAIAdapter
    from ingest.reclassification_ai import process_reclassified_job
    from ingest.supabase_store import create_ingest_client
    if CLAUDE_JOB_USD_CAP!=0.10 or MAX_CREATE_CALLS!=2:raise ValueError('unexpected_cost_contract')
    url=os.environ.get('SUPABASE_URL','');key=os.environ.get('SUPABASE_SERVICE_KEY','')
    if url.rstrip('/')!=f'https://{args.project_ref}.supabase.co' or not key.strip():raise ValueError('invalid_server_configuration')
    _,provider_key=require_configured_provider();provider=ClaudeAdapter(api_key=provider_key)
    return process_reclassified_job(ProgramAIAdapter.from_supabase(create_ingest_client(url,key)),source_item_id=args.source_item_id,revision=args.revision,classification_version=args.classification_version,summarize_ko=provider.summarize_ko,translate_ja=provider.translate_ja,worker_id='classification-manual-'+uuid4().hex)

def main(argv=None,*,execute=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-item-id',required=True,type=target_id)
    parser.add_argument('--revision',required=True,type=revision_hash)
    parser.add_argument('--classification-version',required=True,type=int)
    parser.add_argument('--project-ref',required=True,type=project_ref)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args(argv)
    if args.classification_version<1:parser.error('invalid_classification_version')
    if not args.execute:
        print(json.dumps({'mode':'validation_only','target_count':1,'usd_cap':0.10,'automatic_retries':0,'network_calls':0,'publish':False}));return 0
    try:
        r=(execute or execute_target)(args);success=r.status=='processed' and r.completed==1 and not (r.retried or r.failed or r.state_unknown)
        print(json.dumps({'mode':'execution','completed':success,'status':r.status,'automatic_retries':0,'publish':False}));return 0 if success else 1
    except Exception:
        print('classification_target_execution_failed');return 1

if __name__=='__main__':raise SystemExit(main())
