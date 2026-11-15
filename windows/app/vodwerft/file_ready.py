"""Prüft, ob eine Datei noch von einem Programm zum Schreiben geöffnet ist (Kopiervorgang läuft noch)."""
import ctypes
import os


def unlocked(path):
    if os.name != "nt":
        return True
    kernel = ctypes.windll.kernel32
    handle_type = ctypes.c_void_p
    kernel.CreateFileW.restype = handle_type
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, handle_type]
    kernel.CloseHandle.argtypes = [handle_type]
    # Other readers are harmless. An open writer still prevents this check.
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
    if handle == handle_type(-1).value:
        return False
    kernel.CloseHandle(handle)
    return True
