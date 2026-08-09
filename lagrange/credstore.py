"""
Windows Credential Manager, via advapi32.

Antigravity keeps its OAuth token here rather than in a file, so this module is
the foundation everything else stands on. Lagrange stores its own copies in the
same vault, which means no secret is ever written to disk in the clear.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class CredentialError(Exception):
    pass


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
    """
    Target names of generic credentials.

    Used to rediscover Antigravity's entry if it is ever renamed, so a rename
    upstream degrades to a slower startup instead of a dead tool.
    """
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
