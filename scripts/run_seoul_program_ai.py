"""One explicit Seoul target. Validation only unless --execute is supplied.

No environment-file loading, collection, activation, publication, or retry loop.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from typing import Callable, Sequence
from uuid import UUID, uuid4


def target_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError("invalid_source_item_id") from None


def revision_hash(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise argparse.ArgumentTypeError("invalid_revision")
    return value


def project_ref(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9]{20}", value):
        raise argparse.ArgumentTypeError("invalid_project_ref")
    return value


def execute_target(args: argparse.Namespace):
    # Dependencies, credentials, and clients are created only in explicit execution.
    from ingest.ai_provider import require_configured_provider, create_provider_adapter, close_provider_adapter
    from ingest.ai_claude import CLAUDE_JOB_USD_CAP, MAX_CREATE_CALLS
    from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job
    from ingest.supabase_store import create_ingest_client

    if CLAUDE_JOB_USD_CAP != 0.10 or MAX_CREATE_CALLS != 2:
        raise ValueError("unexpected_cost_contract")
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    # Also rejects embedded credentials, a different project, paths, and HTTP.
    if url.rstrip("/") != f"https://{args.project_ref}.supabase.co" or not key.strip():
        raise ValueError("invalid_server_configuration")
    provider_name, provider_key = require_configured_provider()
    if provider_name != 'chatgpt_plan':
        raise ValueError('explicit_chatgpt_plan_required')
    provider = create_provider_adapter(provider_name, provider_key)
    try:
        client = create_ingest_client(url, key)
        return process_seoul_program_job(
            ProgramAIAdapter.from_supabase(client), source_item_id=args.source_item_id,
            revision=args.revision, summarize_ko=provider.summarize_program_ko,
            translate_ja=provider.translate_ja, worker_id="program-manual-" + uuid4().hex,
        )
    finally:
        close_provider_adapter(provider)


def execute_queue(args: argparse.Namespace):
    from ingest.ai_provider import require_configured_provider,create_provider_adapter,close_provider_adapter
    from ingest.program_ai import ProgramAIAdapter
    from ingest.seoul_workflow import process_seoul_queue
    from ingest.supabase_store import create_ingest_client
    url=os.environ.get('SUPABASE_URL','');key=os.environ.get('SUPABASE_SERVICE_KEY','')
    if url.rstrip('/')!=f'https://{args.project_ref}.supabase.co' or not key.strip():
        raise ValueError('invalid_server_configuration')
    name,provider_key=require_configured_provider()
    if name!='chatgpt_plan':
        raise ValueError('explicit_chatgpt_plan_required')
    provider=create_provider_adapter(name,provider_key)
    try:
        client=create_ingest_client(url,key)
        return process_seoul_queue(ProgramAIAdapter.from_supabase(client),max_jobs=args.max_jobs,
            queue_pages=args.queue_pages,summarize_ko=provider.summarize_program_ko,
            translate_ja=provider.translate_ja,worker_id='program-manual-'+uuid4().hex)
    finally:close_provider_adapter(provider)


def main(argv: Sequence[str] | None = None, *, execute: Callable | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-item-id", type=target_id)
    parser.add_argument("--revision", type=revision_hash)
    parser.add_argument('--max-jobs',type=int)
    parser.add_argument('--queue-pages',type=int)
    parser.add_argument("--project-ref", required=True, type=project_ref)
    parser.add_argument("--execute", action="store_true", help="Explicitly allow one claim and provider job; separate approval required.")
    args = parser.parse_args(argv)
    queue=args.max_jobs is not None or args.queue_pages is not None
    if queue:
        if args.source_item_id or args.revision or args.max_jobs is None or args.queue_pages is None or not 1<=args.max_jobs<=25 or not 1<=args.queue_pages<=5:
            parser.error('Choose explicit target OR bounded --max-jobs (1..25) AND --queue-pages (1..5).')
    elif not args.source_item_id or not args.revision:
        parser.error('An explicit target/revision or bounded queue scope is required.')
    if not args.execute:
        from ingest.ai_provider import provider_validation_limits
        print(json.dumps({"mode": "validation_only", "source": "seoul_reservation",
                          "target_count": args.max_jobs if queue else 1, "queue_pages":args.queue_pages,
                          **provider_validation_limits(), "automatic_retries": 0,
                          "network_calls": 0, "publish": False}))
        return 0
    try:
        if queue:
            result=(execute or execute_queue)(args)
            print(json.dumps({'mode':'execution',**result}))
            return 1 if result['failed'] or result['state_unknown'] else 0
        result = (execute or execute_target)(args)
        success = (result.status == "processed" and result.claimed == 1 and result.completed == 1
                   and not (result.failed or result.retried or result.state_unknown))
        print(json.dumps({"mode": "execution", "completed": bool(success),
                          "status": result.status, "automatic_retries": 0, "publish": False}))
        return 0 if success else 1
    except Exception:
        # Never print SDK errors, tracebacks, key-bearing URLs, or raw responses.
        print("program_target_execution_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
