"""
Credential storage: Windows Credential Manager on Windows (via advapi32),
and secure file-based storage on Linux / ChromeOS / POSIX.

Antigravity on Windows keeps its OAuth token in Windows Credential Manager under
'gemini:antigravity'. On Linux / ChromeOS, Antigravity keeps its token in
'~/.gemini/antigravity-cli/antigravity-oauth-token'.

Lagrange preserves this convention: on Windows it uses the vault, and on Linux
it maps the live entry to '~/.gemini/antigravity-cli/antigravity-oauth-token'
and stores additional accounts under '~/.lagrange/credentials/' with mode 0600.
"""

from __future__ import annotations

import os
import sys

class CredentialError(Exception):
    pass


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", _FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _PCREDENTIAL = ctypes.POINTER(_CREDENTIAL)

    _advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                    ctypes.POINTER(_PCREDENTIAL)]
    _advapi32.CredReadW.restype = wintypes.BOOL
    _advapi32.CredWriteW.argtypes = [_PCREDENTIAL, wintypes.DWORD]
    _advapi32.CredWriteW.restype = wintypes.BOOL
    _advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _advapi32.CredDeleteW.restype = wintypes.BOOL
    _advapi32.CredEnumerateW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD),
                                         ctypes.POINTER(ctypes.POINTER(_PCREDENTIAL))]
    _advapi32.CredEnumerateW.restype = wintypes.BOOL
    _advapi32.CredFree.argtypes = [ctypes.c_void_p]
    _advapi32.CredFree.restype = None

    def read(target: str) -> bytes | None:
        """Raw blob for a target, or None when the entry does not exist."""
        ptr = _PCREDENTIAL()
        if not _advapi32.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
            err = ctypes.get_last_error()
            if err == ERROR_NOT_FOUND:
                return None
            raise CredentialError(f"CredRead({target}): {ctypes.WinError(err)}")
        try:
            cred = ptr.contents
            return ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        finally:
            _advapi32.CredFree(ctypes.cast(ptr, ctypes.c_void_p))

    def write(target: str, blob: bytes, username: str = "") -> None:
        buf = ctypes.create_string_buffer(blob, len(blob))
        cred = _CREDENTIAL()
        cred.Flags = 0
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = target
        cred.Comment = None
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.AttributeCount = 0
        cred.Attributes = None
        cred.TargetAlias = None
        cred.UserName = username or None
        if not _advapi32.CredWriteW(ctypes.byref(cred), 0):
            raise CredentialError(f"CredWrite({target}): {ctypes.WinError(ctypes.get_last_error())}")

    def delete(target: str) -> bool:
        if not _advapi32.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            if ctypes.get_last_error() == ERROR_NOT_FOUND:
                return False
            raise CredentialError(f"CredDelete({target}): {ctypes.WinError(ctypes.get_last_error())}")
        return True

    def enumerate_targets(filter_pattern: str | None = None) -> list[str]:
        """Target names of generic credentials."""
        count = wintypes.DWORD()
        array = ctypes.POINTER(_PCREDENTIAL)()
        if not _advapi32.CredEnumerateW(filter_pattern, 0, ctypes.byref(count),
                                        ctypes.byref(array)):
            err = ctypes.get_last_error()
            if err == ERROR_NOT_FOUND:
                return []
            raise CredentialError(f"CredEnumerate: {ctypes.WinError(err)}")
        try:
            return [array[i].contents.TargetName or "" for i in range(count.value)]
        finally:
            _advapi32.CredFree(ctypes.cast(array, ctypes.c_void_p))

else:
    # Linux / ChromeOS / POSIX secure file store
    import re
    import tempfile

    _LINUX_LIVE_TOKEN = os.path.expanduser("~/.gemini/antigravity-cli/antigravity-oauth-token")
    _CRED_DIR = os.path.expanduser("~/.lagrange/credentials")

    def _target_to_path(target: str) -> str:
        if target in ("gemini:antigravity", "antigravity"):
            return _LINUX_LIVE_TOKEN
        if "/" in target:
            return os.path.expanduser(target)
        os.makedirs(_CRED_DIR, mode=0o700, exist_ok=True)
        safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", target) + ".json"
        return os.path.join(_CRED_DIR, safe)

    def read(target: str) -> bytes | None:
        path = _target_to_path(target)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except OSError as e:
            raise CredentialError(f"read({target}): {e}") from e

    def write(target: str, blob: bytes, username: str = "") -> None:
        path = _target_to_path(target)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, mode=0o700, exist_ok=True)
        try:
            fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".tmp-cred-")
            with os.fdopen(fd, "wb") as fh:
                fh.write(blob)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, path)
        except OSError as e:
            raise CredentialError(f"write({target}): {e}") from e

    def delete(target: str) -> bool:
        path = _target_to_path(target)
        if not os.path.exists(path):
            return False
        try:
            os.remove(path)
            return True
        except OSError as e:
            raise CredentialError(f"delete({target}): {e}") from e

    def enumerate_targets(filter_pattern: str | None = None) -> list[str]:
        targets = []
        if os.path.exists(_LINUX_LIVE_TOKEN):
            targets.append("gemini:antigravity")
        if os.path.isdir(_CRED_DIR):
            for fname in os.listdir(_CRED_DIR):
                if fname.endswith(".json"):
                    targets.append(fname[:-5])
        return targets
