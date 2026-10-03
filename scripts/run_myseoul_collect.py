"""Validation-only unless explicitly executed; collection never calls AI."""
import argparse
import json
import os
from run_myseoul_program_ai import project_ref


def execute_collection(args):
    from ingest.http_client import HttpClient
    from ingest.myseoul_collect import HTTP_LIMIT, collect_myseoul
    from ingest.supabase_store import create_ingest_client

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if url.rstrip("/") != f"https://{args.project_ref}.supabase.co" or not key.strip():
        raise ValueError("invalid_server_configuration")
    client = create_ingest_client(url, key)
    def rpc(name, params):
        return client.rpc(name, params).execute().data
    return collect_myseoul(HttpClient(budget=HTTP_LIMIT, max_attempts=1), rpc)


def main(argv=None, *, execute=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-ref", required=True, type=project_ref)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({"mode": "validation_only", "http_calls": 0, "details_max": 10,
                          "list_pages_max": 2, "list_page_size": 10, "requests_max": 12,
                          "recheck_slots": 0, "public_list_reader_ready": True, "ai": False}))
        return 0
    try:
        result = (execute or execute_collection)(args)
        print(json.dumps(result))
        return 0 if result["status"] == "complete" else 1
    except Exception:
        print("myseoul_collection_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
