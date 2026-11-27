"""Validation by default; execute is only reached by an explicit collection click."""
import argparse
import json
import os
from run_myseoul_program_ai import project_ref


def execute_collection(args):
    from ingest.culture_portal_collect import collect_culture_portal, HTTP_LIMIT
    from ingest.http_client import HttpClient
    from ingest.supabase_store import create_ingest_client
    url,key = os.environ.get("SUPABASE_URL",""),os.environ.get("SUPABASE_SERVICE_KEY","")
    if url.rstrip("/") != f"https://{args.project_ref}.supabase.co" or not key.strip():
        raise ValueError("invalid_server_configuration")
    client = create_ingest_client(url,key)
    return collect_culture_portal(HttpClient(budget=HTTP_LIMIT,max_attempts=1),lambda name,params:client.rpc(name,params).execute().data)


def main(argv=None,*,execute=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-ref",required=True,type=project_ref)
    parser.add_argument("--execute",action="store_true")
    args=parser.parse_args(argv)
    if not args.execute:
        from ingest.culture_portal_collect import BATCH_SIZE, HTTP_LIMIT
        from ingest.connectors.seoul_culture_portal import MAX_LIST_PAGES
        print(json.dumps(dict(mode="validation_only",http_calls=0,ai=False,batch_size=BATCH_SIZE,
            scope="unfinished_festival_snapshot",rolling_days_limit=None,
            requests_safety_max=HTTP_LIMIT,list_pages_safety_max=MAX_LIST_PAGES)))
        return 0
    try: result=(execute or execute_collection)(args)
    except Exception: print("portal_collection_failed"); return 1
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result["status"] in {"complete","skipped"} else 1


if __name__ == "__main__": raise SystemExit(main())
