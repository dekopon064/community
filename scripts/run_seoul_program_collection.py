"""Validate the bounded collection plan. No scheduling or implicit AI execution."""
import argparse
import json
import os


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument('--execute',action='store_true')
    actions.add_argument('--diagnose-read',action='store_true',help='Read the culture range (<=2000 rows, <=2 HTTP), without DB, retry or storage.')
    from run_seoul_program_ai import project_ref
    parser.add_argument('--project-ref',type=project_ref)
    args=parser.parse_args(argv)
    if args.diagnose_read:
        from ingest.connectors.seoul_reservation import SeoulCultureConnector
        from ingest.seoul_diagnostics import diagnose_culture_read
        result=diagnose_culture_read(SeoulCultureConnector())
        print(json.dumps(result,ensure_ascii=False))
        return int(result['status']=='failed')
    from ingest.seoul_workflow import PAGE_SIZE,MAX_PAGES,STORE_BATCH_SIZE,process_seoul_collection
    if args.execute:
        if not args.project_ref:
            print('explicit_project_ref_required');return 1
        try:
            from ingest.supabase_store import create_ingest_client,SupabaseIngestStore,_rpc_data
            from ingest.program_db import ProgramNewOnlyObservationAdapter
            from ingest.connectors.seoul_reservation import SeoulCultureConnector
            url=os.environ.get('SUPABASE_URL','');key=os.environ.get('SUPABASE_SERVICE_KEY','')
            if url.rstrip('/')!=f'https://{args.project_ref}.supabase.co' or not key.strip():
                raise ValueError('invalid_server_configuration')
            client=create_ingest_client(url,key)
            adapter=ProgramNewOnlyObservationAdapter(lambda name,params:_rpc_data(client,name,params))
            result=process_seoul_collection(SupabaseIngestStore(client),adapter,
                SeoulCultureConnector())
            print(json.dumps(result,ensure_ascii=False));return int(result['status'] in ('failed','state_unknown'))
        except Exception:
            print('seoul_collection_configuration_or_contract_unavailable');return 1
    print(json.dumps(dict(mode='validation_only',source='seoul_reservation',category='문화체험',
        audience_any_of=['제한없음','성인','청년'],audience_source='USETGTINFO',
        api_service='ListPublicReservationCulture',status_any_of=['안내중','접수중'],
        page_size=PAGE_SIZE,max_pages=MAX_PAGES,max_scan_items=PAGE_SIZE*MAX_PAGES,http_attempt_budget=2,store_batch_size=STORE_BATCH_SIZE,
        ordering='RCPTBGNDT_desc_then_SVCID',source_ordering='untrusted',full_range_required=True,
        network_calls=0,ai_calls=0,execution_ready='requires_server_contract',
        required_contract='seoul-new-only-v1',publish=False),ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
