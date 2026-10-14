"""Current-user Windows DPAPI storage. No plaintext fallback or import-time IO."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from ingest.chatgpt_plan_protocol import ProbeError


class WindowsProtection:
    def __init__(self):
        if os.name != 'nt':
            raise ProbeError('plan_secure_store_unsupported')
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        class Blob(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
        self.Blob = Blob
        pointer = ctypes.POINTER(Blob)
        self.crypt.CryptProtectData.argtypes = [pointer,wintypes.LPCWSTR,pointer,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,pointer]
        self.crypt.CryptProtectData.restype = wintypes.BOOL
        self.crypt.CryptUnprotectData.argtypes = [pointer,ctypes.c_void_p,pointer,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,pointer]
        self.crypt.CryptUnprotectData.restype = wintypes.BOOL
        self.kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel.LocalFree.restype = ctypes.c_void_p
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE,wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]

    def _transform(self, value, *, decrypt):
        source = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        incoming, outgoing = self.Blob(len(value),source), self.Blob()
        try:
            fn = self.crypt.CryptUnprotectData if decrypt else self.crypt.CryptProtectData
            # UI_FORBIDDEN; deliberately no LOCAL_MACHINE flag.
            if not fn(ctypes.byref(incoming),None,None,None,None,1,ctypes.byref(outgoing)):
                raise ProbeError('plan_secure_store_unavailable')
            return ctypes.string_at(outgoing.data,outgoing.size)
        finally:
            ctypes.memset(source,0,len(value))
            if outgoing.data:
                ctypes.memset(outgoing.data,0,outgoing.size)
                self.kernel.LocalFree(outgoing.data)

    def protect(self, value):
        return self._transform(value,decrypt=False)

    def unprotect(self, value):
        return self._transform(value,decrypt=True)

    @contextmanager
    def lock(self, key):
        handle = self.kernel.CreateMutexW(None,False,'Local\\Machimoa.PlanAuth.'+key)
        if not handle:
            raise ProbeError('plan_auth_lock_unavailable')
        acquired = False
        try:
            status = self.kernel.WaitForSingleObject(handle,30000)
            acquired = status in (0,0x80)
            # Abandoned owner may have sent a rotating refresh. Do not proceed.
            if status != 0:
                raise ProbeError('plan_auth_lock_unavailable')
            yield
        finally:
            if acquired:
                self.kernel.ReleaseMutex(handle)
            self.kernel.CloseHandle(handle)


class WindowsPlanStore:
    """One explicitly selected local registration, shared across worktrees/sources."""
    def __init__(self, *, path=None, protection=None):
        if path is None:
            root = os.environ.get('LOCALAPPDATA')
            if os.name != 'nt' or not root or not Path(root).is_absolute():
                raise ProbeError('plan_secure_store_unsupported')
            path = Path(root)/'Machimoa'/'WorkerAuth'/'plan-v1.bin'
        self.path = Path(path)
        self.protection = protection or WindowsProtection()

    def __repr__(self):
        return 'WindowsPlanStore(credentials=redacted)'

    def lock(self):
        key = hashlib.sha256(str(self.path.absolute()).casefold().encode()).hexdigest()
        return self.protection.lock(key)

    def _check_path(self):
        if any(p.is_symlink() for p in [self.path,*self.path.parents]):
            raise ProbeError('plan_secure_store_unavailable')

    def load(self):
        try:
            self._check_path()
            try:
                size = self.path.stat().st_size
            except FileNotFoundError:
                return None
            if size > 131072:
                raise ValueError()
            raw = self.protection.unprotect(self.path.read_bytes())
            value = json.loads(raw)
            if not isinstance(value,dict):
                raise ValueError()
            return value
        except ProbeError:
            raise
        except Exception:
            raise ProbeError('plan_secure_store_unavailable') from None

    def save(self, record):
        temporary = self.path.with_name(self.path.name+'.'+uuid4().hex+'.new')
        try:
            self._check_path()
            raw = json.dumps(record,separators=(',',':')).encode()
            if len(raw) > 65536:
                raise ValueError()
            protected = self.protection.protect(raw)
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with temporary.open('xb') as file:
                file.write(protected)
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(self.path)
        except ProbeError:
            raise
        except Exception:
            raise ProbeError('plan_secure_store_unavailable') from None
        finally:
            # Only this invocation's encrypted temporary file, never other state.
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass  # Already encrypted; never replace the original failure.
