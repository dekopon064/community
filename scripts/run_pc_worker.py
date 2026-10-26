"""Manual PC connection. Explicit signed admin clicks alone can start existing workers."""
import argparse
import os


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-ref',required=True)
    parser.add_argument('--app-origin',default='https://community-app-drab.vercel.app')
    args=parser.parse_args()
    from ingest.pc_worker_bridge import PcWorkerControl,serve
    from ingest.pc_worker_existing import ExistingWorkers
    # Lazy key callback: startup/status never reads credentials or opens a client.
    worker=ExistingWorkers(args.project_ref)
    control=PcWorkerControl(project=args.project_ref,origin=args.app_origin,
        key=lambda:os.environ.get('SUPABASE_SERVICE_KEY',''),execute=worker)
    worker.progress=control.report
    serve(control)


if __name__=='__main__':main()
