"""
audio_output.py – Sortie audio par défaut de macOS (CoreAudio via ctypes).

Quand un mode Son démarre, on bascule la sortie vers le périphérique
« Ambilight » (sortie multiple : enceintes + BlackHole) pour que BlackHole
reçoive la musique ; quand plus aucun mode Son ne tourne, on remet la sortie
d'avant (sauf si l'utilisateur l'a changée entre-temps).
"""

import ctypes
import threading
from ctypes import byref, c_uint32, c_void_p, sizeof

TARGET_NAME = "Ambilight"


def _fourcc(s: str) -> int:
    return int.from_bytes(s.encode("ascii"), "big")


class _Addr(ctypes.Structure):
    _fields_ = [("selector", c_uint32), ("scope", c_uint32), ("element", c_uint32)]


_SYSTEM = 1
_GLOBAL = _fourcc("glob")
_OUTPUT = _fourcc("outp")
_DEVICES = _fourcc("dev#")
_DEFAULT_OUT = _fourcc("dOut")
_NAME = _fourcc("lnam")
_STREAMS = _fourcc("stm#")
_UTF8 = 0x08000100

try:
    _ca = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
    _cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    _ca.AudioObjectGetPropertyDataSize.argtypes = [c_uint32, ctypes.POINTER(_Addr), c_uint32, c_void_p, ctypes.POINTER(c_uint32)]
    _ca.AudioObjectGetPropertyData.argtypes = [c_uint32, ctypes.POINTER(_Addr), c_uint32, c_void_p, ctypes.POINTER(c_uint32), c_void_p]
    _ca.AudioObjectSetPropertyData.argtypes = [c_uint32, ctypes.POINTER(_Addr), c_uint32, c_void_p, c_uint32, c_void_p]
    _cf.CFStringGetCString.argtypes = [c_void_p, ctypes.c_char_p, ctypes.c_long, c_uint32]
    _cf.CFRelease.argtypes = [c_void_p]
    CA_OK = True
except OSError:
    CA_OK = False


def _get_size(obj: int, sel: int, scope: int = _GLOBAL) -> int:
    size = c_uint32(0)
    if _ca.AudioObjectGetPropertyDataSize(obj, byref(_Addr(sel, scope, 0)), 0, None, byref(size)) != 0:
        return 0
    return size.value


def _device_ids() -> list[int]:
    n = _get_size(_SYSTEM, _DEVICES) // 4
    if n == 0:
        return []
    arr = (c_uint32 * n)()
    size = c_uint32(sizeof(arr))
    if _ca.AudioObjectGetPropertyData(_SYSTEM, byref(_Addr(_DEVICES, _GLOBAL, 0)), 0, None, byref(size), arr) != 0:
        return []
    return list(arr)


def _name(dev: int) -> str:
    ref = c_void_p()
    size = c_uint32(sizeof(ref))
    if _ca.AudioObjectGetPropertyData(dev, byref(_Addr(_NAME, _GLOBAL, 0)), 0, None, byref(size), byref(ref)) != 0 or not ref:
        return ""
    buf = ctypes.create_string_buffer(256)
    ok = _cf.CFStringGetCString(ref, buf, 256, _UTF8)
    _cf.CFRelease(ref)
    return buf.value.decode("utf-8", "replace") if ok else ""


def _is_output(dev: int) -> bool:
    return _get_size(dev, _STREAMS, _OUTPUT) > 0


def default_output() -> int:
    dev = c_uint32(0)
    size = c_uint32(4)
    _ca.AudioObjectGetPropertyData(_SYSTEM, byref(_Addr(_DEFAULT_OUT, _GLOBAL, 0)), 0, None, byref(size), byref(dev))
    return dev.value


def _set_default_output(dev: int) -> bool:
    val = c_uint32(dev)
    return _ca.AudioObjectSetPropertyData(_SYSTEM, byref(_Addr(_DEFAULT_OUT, _GLOBAL, 0)), 0, None, 4, byref(val)) == 0


def find_output(name: str) -> int | None:
    for dev in _device_ids():
        if _is_output(dev) and _name(dev).strip().lower() == name.lower():
            return dev
    return None


class OutputRouter:
    """Bascule vers « Ambilight » pendant les modes Son, puis restaure."""

    def __init__(self):
        self._lock = threading.Lock()
        self._previous: int | None = None
        self._switched_to: int | None = None
        self.target_exists = False

    def current_name(self) -> str:
        if not CA_OK:
            return ""
        try:
            return _name(default_output())
        except Exception:
            return ""

    def engage(self) -> str:
        """Retourne un message d'état (vide si tout va bien)."""
        if not CA_OK:
            return "CoreAudio indisponible"
        with self._lock:
            try:
                target = find_output(TARGET_NAME)
                self.target_exists = target is not None
                if target is None:
                    return f"sortie « {TARGET_NAME} » introuvable"
                cur = default_output()
                if cur == target:
                    return ""
                if _set_default_output(target):
                    self._previous, self._switched_to = cur, target
                    print(f"[audio] sortie → {TARGET_NAME} (avant : {_name(cur)})")
                    return ""
                return "impossible de changer la sortie audio"
            except Exception as e:
                return f"sortie audio : {e}"

    def restore(self):
        if not CA_OK:
            return
        with self._lock:
            prev, switched = self._previous, self._switched_to
            self._previous = self._switched_to = None
            if prev is None or switched is None:
                return
            try:
                # On ne touche à rien si l'utilisateur a changé de sortie entre-temps.
                if default_output() == switched and prev in _device_ids():
                    _set_default_output(prev)
                    print(f"[audio] sortie restaurée → {_name(prev)}")
            except Exception:
                pass
