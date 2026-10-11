"""Validate the bounded collection plan. No scheduling or implicit AI execution."""
import argparse
import json
import os


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument('--execute',action='store_true')
    actions.add_argument('--diagnose-read',action='store_true',help='Read 50 rows once, without DB, retry or storage.')
    from run_seoul_program_ai import project_ref
    parser.add_argument('--project-ref',type=project_ref)
    args=parser.parse_args(argv)
    if args.diagnose_read:
        from ingest.connectors.seoul_reservation import SeoulReservationConnector
        from ingest.http_client import HttpClient
        from ingest.seoul_diagnostics import diagnose_read
        result=diagnose_read(SeoulReservationConnector(HttpClient(budget=1,max_attempts=1),page_size=50,max_pages=1))
        print(json.dumps(result,ensure_ascii=False))
        return int(result['status']=='failed')
    from ingest.seoul_workflow import PAGE_SIZE,MAX_PAGES,STORE_BATCH_SIZE,process_seoul_collection
    if args.execute:
        if not args.project_ref:
            print('explicit_project_ref_required');return 1
        try:
            from ingest.supabase_store import create_ingest_client,SupabaseIngestStore,_rpc_data
            from ingest.program_db import ProgramNewOnlyObservationAdapter
            from ingest.connectors.seoul_reservation import SeoulReservationConnector
            url=os.environ.get('SUPABASE_URL','');key=os.environ.get('SUPABASE_SERVICE_KEY','')
            if url.rstrip('/')!=f'https://{args.project_ref}.supabase.co' or not key.strip():
                raise ValueError('invalid_server_configuration')
            client=create_ingest_client(url,key)
            adapter=ProgramNewOnlyObservationAdapter(lambda name,params:_rpc_data(client,name,params))
            result=process_seoul_collection(SupabaseIngestStore(client),adapter,
                SeoulReservationConnector(page_size=PAGE_SIZE,max_pages=MAX_PAGES))
            print(json.dumps(result,ensure_ascii=False));return int(result['status'] in ('failed','state_unknown'))
        except Exception:
            print('seoul_collection_configuration_or_contract_unavailable');return 1
    print(json.dumps(dict(mode='validation_only',source='seoul_reservation',category='문화체험',
        page_size=PAGE_SIZE,max_pages=MAX_PAGES,http_attempt_budget=3,store_batch_size=STORE_BATCH_SIZE,
        ordering='untrusted',network_calls=0,ai_calls=0,execution_ready='requires_server_contract',
        required_contract='seoul-new-only-v1',publish=False),ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
