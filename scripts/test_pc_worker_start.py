"""Desktop entry-point tests. Fake worker/auth only; no external connections."""
import contextlib
import errno
import io
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import queue
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import run_pc_worker

ROOT=Path(__file__).resolve().parents[1]
PROJECT='a'*20
DESKTOP_PROJECT='czhiqikcpmujeujyfunq'
FAKE_KEY='synthetic-only-local-key-for-launcher'


class StartTests(unittest.TestCase):
    def setUp(self):
        self.worker=SimpleNamespace(progress=None)
        self.control=SimpleNamespace(report=Mock())
        self.make_worker=Mock(return_value=self.worker)
        self.make_control=Mock(return_value=self.control)
        self.serve=Mock()
        self.output=io.StringIO()
        modules={
            'ingest.pc_worker_bridge':SimpleNamespace(PcWorkerControl=self.make_control,serve=self.serve),
            'ingest.pc_worker_existing':SimpleNamespace(ExistingWorkers=self.make_worker),
        }
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(sys.modules,modules))
        self.stack.enter_context(patch.object(sys,'argv',['run_pc_worker.py','--project-ref',PROJECT]))
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.stack.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')))
        environment_get=os.environ.get
        def guarded_get(key,default=None):
            if key.startswith(('SUPABASE_','OPENAI_','CHATGPT_','AI_')):
                raise AssertionError('startup must not read credentials')
            return environment_get(key,default)
        self.stack.enter_context(patch.object(os.environ,'get',side_effect=guarded_get))

    def test_normal_start_uses_existing_contract_without_authentication_or_execution(self):
        self.assertEqual(run_pc_worker.main(),0)
        self.make_worker.assert_called_once_with(PROJECT)
        options=self.make_control.call_args.kwargs
        self.assertEqual(options['project'],PROJECT)
        self.assertEqual(options['origin'],'https://community-app-drab.vercel.app')
        self.assertIs(options['execute'],self.worker)
        self.assertTrue(callable(options['key']))
        self.assertIs(self.worker.progress,self.control.report)
        self.serve.assert_called_once_with(self.control)
        self.assertIn('인증 연결을 별도로 확인',self.output.getvalue())

    def check_error(self,error,expected):
        self.serve.side_effect=error
        self.assertEqual(run_pc_worker.main(),1)
        self.assertIn(expected,self.output.getvalue())
        self.assertNotIn('private-value-must-not-leak',self.output.getvalue())
        self.serve.assert_called_once()

    def test_port_in_use(self):
        self.check_error(OSError(errno.EADDRINUSE,'private-value-must-not-leak'),'이미 사용 중')

    def test_windows_port_in_use(self):
        error=OSError('private-value-must-not-leak');error.winerror=10048
        self.check_error(error,'이미 사용 중')

    def test_port_permission_denied(self):
        self.check_error(PermissionError(errno.EACCES,'private-value-must-not-leak'),'열 권한이 없습니다')

    def test_windows_port_permission_denied(self):
        error=OSError('private-value-must-not-leak');error.winerror=10013
        self.check_error(error,'열 권한이 없습니다')

    def test_other_os_error(self):
        self.check_error(OSError(errno.EIO,'private-value-must-not-leak'),'자동 재시도하지 않습니다')

    def test_missing_dependency(self):
        self.make_worker.side_effect=ImportError('private-value-must-not-leak')
        self.assertEqual(run_pc_worker.main(),1)
        self.assertIn('실행 환경 또는 연결 설정',self.output.getvalue())
        self.assertNotIn('private-value-must-not-leak',self.output.getvalue())
        self.serve.assert_not_called()

    def test_invalid_configuration(self):
        self.make_control.side_effect=ValueError('private-value-must-not-leak')
        self.assertEqual(run_pc_worker.main(),1)
        self.serve.assert_not_called()
        self.assertNotIn('private-value-must-not-leak',self.output.getvalue())

    def test_unexpected_error_has_no_secret_and_no_retry(self):
        self.check_error(RuntimeError('private-value-must-not-leak'),'자동 재시도하지 않습니다')

    def test_keyboard_interrupt_is_normal_stop(self):
        self.serve.side_effect=KeyboardInterrupt
        self.assertEqual(run_pc_worker.main(),0)
        self.assertIn('종료했습니다',self.output.getvalue())
        self.serve.assert_called_once()

    def test_missing_project_stops_before_import_and_start(self):
        with patch.object(sys,'argv',['run_pc_worker.py']),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as error:
            run_pc_worker.main()
        self.assertEqual(error.exception.code,2)
        self.make_worker.assert_not_called();self.serve.assert_not_called()


@unittest.skipUnless(os.name=='nt','Windows desktop launcher')
class BatchTests(unittest.TestCase):
    def setUp(self):
        temporary_root=ROOT/'scripts'/'__pycache__'
        temporary_root.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(prefix='pc launcher 공백 ',dir=temporary_root)
        assert Path(self.tmp.name).resolve().parent==temporary_root.resolve()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'launcher'
        self.root.mkdir()
        self.config=self.root.parent/'google-login'/'.env.local'
        self.config.parent.mkdir()
        self.config.write_text(
            f'NEXT_PUBLIC_SUPABASE_URL=https://{DESKTOP_PROJECT}.supabase.co\n'
            f'export SUPABASE_SERVICE_KEY="{FAKE_KEY}"\n'
            'UNRELATED_SETTING=must-not-load\n', encoding='utf-8-sig',
        )
        shutil.copyfile(ROOT/'start_pc_worker.cmd',self.root/'start_pc_worker.cmd')
        (self.root/'scripts').mkdir()
        self.release=self.root.parent/'seoul-condition-navigation-release-20261111'
        self.package=self.release/'scripts'/'ingest';self.package.mkdir(parents=True)
        for name in ('__init__.py','pc_worker_existing.py','pc_worker_bridge.py'):
            (self.package/name).write_text('',encoding='utf-8')
        # Child receives only OS/runtime paths, never inherited application credentials.
        safe_names=('SystemRoot','WINDIR','COMSPEC','TEMP','TMP','PATHEXT','SystemDrive')
        self.env={key:os.environ[key] for key in safe_names if key in os.environ}
        self.env['PATH']=str(Path(sys.executable).parent)+os.pathsep+str(Path(os.environ['SystemRoot'])/'System32')

    def launch(self,source=None,env=None):
        if source is not None:(self.root/'scripts'/'run_pc_worker.py').write_text(source,encoding='utf-8')
        # cmd requires its own outer quotes, rather than list2cmdline's C-runtime escaping.
        command='"'+os.environ['COMSPEC']+'" /d /s /c ""'+str(self.root/'start_pc_worker.cmd')+'""'
        return subprocess.run(command,
            input='\n',capture_output=True,text=True,encoding='utf-8',errors='replace',
            cwd=ROOT.parent,env=env or self.env,timeout=10)

    def actual_entry_with_fake_dependencies(self,serve_body):
        shutil.copyfile(ROOT/'scripts'/'run_pc_worker.py',self.root/'scripts'/'run_pc_worker.py')
        package=self.package
        (package/'__init__.py').write_text('',encoding='utf-8')
        (package/'pc_worker_existing.py').write_text(
            'class ExistingWorkers:\n def __init__(self,project):pass\n def __call__(self,*args):raise AssertionError("execution forbidden")\n',encoding='utf-8')
        (package/'pc_worker_bridge.py').write_text(
            'class PcWorkerControl:\n def __init__(self,**kwargs):self.key=kwargs["key"]\n def report(self,*args):pass\ndef serve(control):\n '+serve_body+'\n',encoding='utf-8')

    def test_actual_entry_reports_ready_through_batch_without_workers(self):
        self.actual_entry_with_fake_dependencies(
            f"import os\n assert control.key() == {FAKE_KEY!r}\n"
            f" assert os.environ['SUPABASE_URL'] == 'https://{DESKTOP_PROJECT}.supabase.co'\n"
            " assert os.environ['AI_PROVIDER'] == 'chatgpt_plan'\n"
            " assert 'UNRELATED_SETTING' not in os.environ\n"
            " from pathlib import Path\n assert Path.cwd().name == 'seoul-condition-navigation-release-20261111'\n"
            " assert Path(__file__).resolve().parent.parent.parent == Path.cwd()\n"
            " print('PC 연결 준비: http://127.0.0.1:14621 [FAKE SOCKET]')"
        )
        result=self.launch(env={**self.env,'AI_PROVIDER':'openai'})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PC 연결 준비:',result.stdout)
        self.assertIn('인증 연결을 별도로 확인',result.stdout)
        self.assertNotIn(FAKE_KEY,result.stdout+result.stderr)

    def test_missing_release_stops_without_old_worker_fallback(self):
        self.actual_entry_with_fake_dependencies("raise AssertionError('must not serve')")
        (self.package/'pc_worker_existing.py').unlink()
        result=self.launch()
        self.assertEqual(result.returncode,1)
        self.assertIn('이전 worker로 실행하지 않습니다',result.stdout)
        self.assertNotIn(FAKE_KEY,result.stdout+result.stderr)

    def test_batch_rejects_wrong_project_or_missing_config_before_serving(self):
        self.actual_entry_with_fake_dependencies("raise AssertionError('must not serve')")
        self.config.write_text(
            f'SUPABASE_URL=https://{"b"*20}.supabase.co\nSUPABASE_SERVICE_KEY={FAKE_KEY}\n',
            encoding='utf-8',
        )
        for missing in (False, True):
            if missing:
                self.config.unlink()
            result=self.launch()
            self.assertEqual(result.returncode,1)
            self.assertIn('기존 로컬 인증 설정',result.stdout)
            self.assertNotIn('준비 확인 중',result.stdout)
            self.assertNotIn(FAKE_KEY,result.stdout+result.stderr)

    def test_actual_entry_port_conflict_is_readable_without_traceback(self):
        self.actual_entry_with_fake_dependencies("raise OSError(10048,'private-value-must-not-leak')")
        # errno is portable EADDRINUSE; WinError 10048 is tested separately above.
        bridge=self.package/'pc_worker_bridge.py'
        bridge.write_text(bridge.read_text(encoding='utf-8').replace('OSError(10048',f'OSError({errno.EADDRINUSE}'),encoding='utf-8')
        result=self.launch()
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertIn('이미 사용 중',result.stdout)
        self.assertNotIn('Traceback',result.stdout+result.stderr)
        self.assertNotIn('private-value-must-not-leak',result.stdout+result.stderr)

    def test_batch_waits_for_acknowledgment_after_failure(self):
        (self.root/'scripts'/'run_pc_worker.py').write_text('raise SystemExit(9)\n',encoding='utf-8')
        command='"'+os.environ['COMSPEC']+'" /d /s /c ""'+str(self.root/'start_pc_worker.cmd')+'""'
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,encoding='utf-8',errors='replace',env=self.env,cwd=ROOT.parent)
        lines=queue.Queue()
        def read_lines():
            for line in process.stdout:lines.put(line)
        reader=threading.Thread(target=read_lines,daemon=True);reader.start()
        try:
            output=''
            for _ in range(30):
                output+=lines.get(timeout=5)
                if '아무 키' in output:break
            self.assertIn('아무 키',output)
            self.assertIsNone(process.poll(),'Error window must stay open until acknowledgment')
            process.stdin.write('\n');process.stdin.flush()
            self.assertEqual(process.wait(timeout=5),9)
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=5)
            reader.join(timeout=2)
            process.stdin.close();process.stdout.close()

    def test_launcher_passes_fixed_public_project_and_runs_once_from_any_directory(self):
        result=self.launch(
            "import sys\nfrom pathlib import Path\n"
            f"assert sys.argv[1:4]==['--project-ref',{DESKTOP_PROJECT!r},'--local-config']\n"
            f"assert Path(sys.argv[4]).resolve()==Path({str(self.config)!r})\n"
            f"assert sys.argv[5]=='--worker-root' and Path(sys.argv[6]).resolve()==Path({str(self.release)!r})\n"
            "assert len(sys.argv)==7\nprint('FAKE_READY_ONCE')\n"
        )
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(result.stdout.count('FAKE_READY_ONCE'),1)
        self.assertIn('[종료]',result.stdout)
        self.assertIn('아무 키',result.stdout)

    def test_worker_failure_keeps_error_visible_without_retry(self):
        result=self.launch("print('FAKE_FAILURE_ONCE')\nraise SystemExit(7)\n")
        self.assertEqual(result.returncode,7,result.stdout+result.stderr)
        self.assertEqual(result.stdout.count('FAKE_FAILURE_ONCE'),1)
        self.assertIn('자동으로 다시 실행하지 않습니다',result.stdout)
        self.assertIn('아무 키',result.stdout)

    def test_worker_missing(self):
        result=self.launch()
        self.assertEqual(result.returncode,1)
        self.assertIn('실행 파일을 찾지 못했습니다',result.stdout)
        self.assertIn('아무 키',result.stdout)

    def test_python_missing(self):
        env={**self.env,'PATH':str(Path(os.environ['SystemRoot'])/'System32')}
        result=self.launch(env=env)
        self.assertEqual(result.returncode,1)
        self.assertIn('Python을 찾지 못했습니다',result.stdout)
        self.assertIn('아무 키',result.stdout)


if __name__=='__main__':unittest.main()
