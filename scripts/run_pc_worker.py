"""Manual PC connection. Explicit signed admin clicks alone can start existing workers."""
import argparse
import errno
import os
from pathlib import Path
import re
import sys


class WorkerRootError(ValueError):
    pass


def select_worker_root(root: Path) -> Path:
    """Use one explicit release package; never fall back to the old worker."""
    root = root.resolve()
    scripts = root / "scripts"
    required = ("__init__.py", "pc_worker_existing.py", "pc_worker_bridge.py")
    if not all((scripts / "ingest" / name).is_file() for name in required):
        raise WorkerRootError()
    old_scripts = Path(__file__).resolve().parent
    sys.path[:] = [str(scripts)] + [entry for entry in sys.path
        if Path(entry).resolve() not in {old_scripts, scripts}]
    os.chdir(root)
    return root


class LocalConfigError(ValueError):
    pass


def load_local_config(path: Path, project: str) -> None:
    """Read only the existing worker settings and use them in this process."""
    names = ('SUPABASE_URL', 'NEXT_PUBLIC_SUPABASE_URL',
             'SUPABASE_SERVICE_KEY', 'SUPABASE_SERVICE_ROLE_KEY')
    values = {}
    try:
        with path.open(encoding='utf-8-sig') as source:
            for line in source:
                match = re.fullmatch(r'\s*(?:export\s+)?([A-Z_]+)\s*=\s*(.*?)\s*', line)
                if not match or match[1] not in names:
                    continue
                name, value = match.groups()
                if value.startswith(('"', "'")):
                    if len(value) < 2 or value[-1] != value[0]:
                        raise LocalConfigError()
                    value = value[1:-1]
                if name in values:
                    raise LocalConfigError()
                values[name] = value
    except (OSError, UnicodeError):
        raise LocalConfigError() from None

    expected_url = f'https://{project}.supabase.co'
    urls = {values[name].rstrip('/') for name in names[:2] if values.get(name)}
    keys = {values[name] for name in names[2:] if values.get(name)}
    if not re.fullmatch('[a-z0-9]{20}', project) or urls != {expected_url} or len(keys) != 1:
        raise LocalConfigError()
    key = keys.pop()
    if len(key) < 24 or any(character.isspace() for character in key):
        raise LocalConfigError()
    os.environ.update(SUPABASE_URL=expected_url, SUPABASE_SERVICE_KEY=key)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-ref',required=True)
    parser.add_argument('--app-origin',default='https://community-app-drab.vercel.app')
    parser.add_argument('--local-config', type=Path)
    parser.add_argument('--worker-root', type=Path)
    args=parser.parse_args()
    try:
        if args.local_config is not None:
            args.local_config = args.local_config.resolve()
        selected_root = select_worker_root(args.worker_root) if args.worker_root is not None else None
        if args.local_config is not None:
            load_local_config(args.local_config, args.project_ref)
        from ingest.pc_worker_bridge import PcWorkerControl,serve
        from ingest.pc_worker_existing import ExistingWorkers
        # Connection verification reads the key from this process, without opening a DB client.
        worker=ExistingWorkers(args.project_ref)
        control=PcWorkerControl(project=args.project_ref,origin=args.app_origin,
            key=lambda:os.environ.get('SUPABASE_SERVICE_KEY',''),execute=worker)
        worker.progress=control.report
        if selected_root is not None:
            print(f'worker 코드 연결: {selected_root.name}', flush=True)
        print('준비 확인 중입니다. 아래 PC 연결 준비 안내가 나올 때까지 기다려 주세요.',flush=True)
        print('관리자 화면의 PC 연결 버튼으로 인증 연결을 별도로 확인합니다.',flush=True)
        print('종료할 때는 Ctrl+C를 누르고 종료 안내를 기다려 주세요.',flush=True)
        serve(control)
        return 0
    except WorkerRootError:
        print('[시작 오류] 지정된 배포 worker 폴더를 찾을 수 없습니다. 이전 worker로 실행하지 않습니다.', flush=True)
    except LocalConfigError:
        print('[시작 오류] 기존 로컬 인증 설정 파일 또는 프로젝트·연결 키 설정을 확인해 주세요.',flush=True)
    except OSError as error:
        if error.errno==errno.EADDRINUSE or getattr(error,'winerror',None)==10048:
            print('[시작 오류] 연결 포트 14621이 이미 사용 중입니다. 기존 실행기 창을 확인해 주세요.',flush=True)
        elif error.errno in {errno.EACCES,errno.EPERM} or getattr(error,'winerror',None)==10013:
            print('[시작 오류] PC 연결 포트를 열 권한이 없습니다. 보안 설정을 임의로 해제하지 말고 오류를 확인해 주세요.',flush=True)
        else:
            print('[실행 오류] PC 연결 프로그램을 실행하지 못했습니다. 자동 재시도하지 않습니다.',flush=True)
    except (ImportError,ValueError):
        print('[시작 오류] 실행 환경 또는 연결 설정을 확인해 주세요. 인증정보를 새로 입력하거나 설정을 변경하지 않았습니다.',flush=True)
    except KeyboardInterrupt:
        print('PC 연결 프로그램을 종료했습니다.',flush=True)
        return 0
    except Exception:
        # Never echo credential-bearing exception messages or tracebacks.
        print('[실행 오류] PC 연결 프로그램이 중단되었습니다. 자동 재시도하지 않습니다.',flush=True)
    return 1


if __name__=='__main__':raise SystemExit(main())
