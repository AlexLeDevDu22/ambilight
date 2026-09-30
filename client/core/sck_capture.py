"""
sck_capture.py – Capture d'écran via ScreenCaptureKit (macOS 12.3+).

Le GPU réduit directement l'écran à une petite image (≈ 320 px de large) et
ne livre une image que lorsque l'écran change : beaucoup moins de charge pour
WindowServer que CGWindowListCreateImage (qui recompose tout l'écran à
chaque appel).
"""

import threading

import numpy as np

import objc
import CoreMedia
import Quartz
import ScreenCaptureKit as SCK
from Foundation import NSObject

try:
    import libdispatch
    _queue = libdispatch.dispatch_queue_create(b"ambilight.sck", None)
except Exception:
    _queue = None

OUT_W = 320


class _Output(NSObject):
    def initWithOwner_(self, owner):
        self = objc.super(_Output, self).init()
        if self is not None:
            self.owner = owner
        return self

    def stream_didOutputSampleBuffer_ofType_(self, stream, sample, kind):
        if kind != SCK.SCStreamOutputTypeScreen:
            return
        try:
            self.owner._on_sample(sample)
        except Exception:
            pass

    def stream_didStopWithError_(self, stream, error):
        self.owner._on_stop(error)


class SCKCapture:
    def __init__(self, screen_index: int = 0, fps: int = 30, timeout: float = 3.0):
        self.screen_index = screen_index
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._stream = None
        self.error: str | None = None
        ready = threading.Event()
        result = {}

        def got_content(content, error):
            result["content"], result["error"] = content, error
            ready.set()

        SCK.SCShareableContent.getShareableContentWithCompletionHandler_(got_content)
        if not ready.wait(timeout) or result.get("content") is None:
            raise RuntimeError(f"ScreenCaptureKit indisponible ({result.get('error')})")
        displays = list(result["content"].displays())
        if not displays:
            raise RuntimeError("aucun écran")
        display = displays[min(screen_index, len(displays) - 1)]

        w, h = display.width(), display.height()
        self.native_w = int(w)
        out_h = max(2, int(round(OUT_W * h / w)))
        cfg = SCK.SCStreamConfiguration.alloc().init()
        cfg.setWidth_(OUT_W)
        cfg.setHeight_(out_h)
        cfg.setMinimumFrameInterval_(CoreMedia.CMTimeMake(1, fps))
        cfg.setPixelFormat_(Quartz.kCVPixelFormatType_32BGRA)
        cfg.setShowsCursor_(False)
        cfg.setQueueDepth_(3)

        flt = SCK.SCContentFilter.alloc().initWithDisplay_excludingWindows_(display, [])
        self._output = _Output.alloc().initWithOwner_(self)
        self._stream = SCK.SCStream.alloc().initWithFilter_configuration_delegate_(flt, cfg, self._output)
        ok, err = self._stream.addStreamOutput_type_sampleHandlerQueue_error_(
            self._output, SCK.SCStreamOutputTypeScreen, _queue, None)
        if not ok:
            raise RuntimeError(f"ScreenCaptureKit : {err}")

        started = threading.Event()

        def on_start(error):
            result["start_error"] = error
            started.set()

        self._stream.startCaptureWithCompletionHandler_(on_start)
        if not started.wait(timeout) or result.get("start_error") is not None:
            raise RuntimeError(f"capture refusée ({result.get('start_error')})")

    def _on_sample(self, sample):
        pb = CoreMedia.CMSampleBufferGetImageBuffer(sample)
        if pb is None:
            return  # image inchangée (frame "idle")
        Quartz.CVPixelBufferLockBaseAddress(pb, Quartz.kCVPixelBufferLock_ReadOnly)
        try:
            w = Quartz.CVPixelBufferGetWidth(pb)
            h = Quartz.CVPixelBufferGetHeight(pb)
            bpr = Quartz.CVPixelBufferGetBytesPerRow(pb)
            base = Quartz.CVPixelBufferGetBaseAddress(pb)
            buf = base.as_buffer(bpr * h)
            arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, bpr)[:, : w * 4].reshape(h, w, 4)
            frame = arr[:, :, 2::-1].copy()  # BGRA → RGB
        finally:
            Quartz.CVPixelBufferUnlockBaseAddress(pb, Quartz.kCVPixelBufferLock_ReadOnly)
        with self._lock:
            self._frame = frame

    def _on_stop(self, error):
        self.error = str(error)

    def capture(self) -> np.ndarray | None:
        with self._lock:
            return self._frame

    def close(self):
        if self._stream is not None:
            done = threading.Event()
            self._stream.stopCaptureWithCompletionHandler_(lambda e: done.set())
            done.wait(1.0)
            self._stream = None
