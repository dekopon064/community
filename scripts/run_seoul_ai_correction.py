"""Run a previously requested Seoul excerpt correction with verified Pro auth."""
import argparse
import os
from uuid import UUID, uuid4

from ingest.ai_provider import close_provider_adapter, create_provider_adapter, require_configured_provider
from ingest.chatgpt_plan_sessions import PlanSessionManager
from ingest.program_ai import ProgramAIAdapter
from ingest.seoul_ai_correction import process_correction
from ingest.supabase_store import create_ingest_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--draft-id', required=True, type=UUID)
    parser.add_argument('--project-ref', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print('validation_only')
        return 0
    url = os.environ.get('SUPABASE_URL', '').rstrip('/')
    key = os.environ.get('SUPABASE_SERVICE_KEY', '')
    provider = None
    try:
        if url != f'https://{args.project_ref}.supabase.co' or not key:
            raise ValueError()
        name, secret = require_configured_provider()
        if name != 'chatgpt_plan':
            raise ValueError()
        provider = create_provider_adapter(name, secret, plan_session=PlanSessionManager().acquire(allow_login=False))
        adapter = ProgramAIAdapter.from_supabase(create_ingest_client(url, key))
        result = process_correction(adapter, str(args.draft_id), 'seoul-correction-' + uuid4().hex,
                                    provider.correct_seoul_excerpt)
        print(result)
        return 0 if result == 'validated' else 1
    except Exception:
        print('correction_not_confirmed')
        return 1
    finally:
        if provider is not None:
            close_provider_adapter(provider)


if __name__ == '__main__':
    raise SystemExit(main())

