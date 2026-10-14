"""C ABI bridge. ctypes.CDLL releases the GIL during native inference."""
from __future__ import annotations

import ctypes as ct
import os
from collections import OrderedDict
from pathlib import Path
import sys
import threading
import time

import cv2
import numpy as np

_cache_lock = threading.Lock()
_sessions: OrderedDict[tuple, NativeReidSession] = OrderedDict()
_MAX_SESSIONS = 8


def library_path() -> Path:
    name = "reid_runtime.dll" if os.name == "nt" else ("libreid_runtime.dylib" if sys.platform == "darwin" else "libreid_runtime.so")
    return Path(os.environ.get("REID_CPP_LIBRARY") or Path(__file__).resolve().parents[1] / "runtime" / "reid_cpp" / name).resolve()


def ort_library_path() -> Path:
    configured = os.environ.get("REID_CPP_ORT_LIBRARY")
    if configured:
        return Path(configured).resolve()
    import onnxruntime
    folder = Path(onnxruntime.__file__).resolve().parent / "capi"
    if os.name == "nt":
        candidate = folder / "onnxruntime.dll"
    else:
        candidates = sorted(folder.glob("libonnxruntime.*"))
        candidate = next((p for p in candidates if ".so" in p.name or p.suffix == ".dylib"), folder / "libonnxruntime.so")
    if not candidate.is_file():
        raise RuntimeError("ORT shared library unavailable; set REID_CPP_ORT_LIBRARY to the SDK runtime")
    return candidate


class NativeReidSession:
    def __init__(self, model_path, *, threads=2):
        self._handle = None
        self._condition = threading.Condition()
        self._active = 0
        self._closing = False
        self.model_path = str(Path(model_path).resolve())
        self.threads = int(threads)
        path = library_path()
        if not path.is_file():
            raise RuntimeError(f"ReID C++ library unavailable: {path}; run scripts/build_reid_cpp.py")
        if not 1 <= self.threads <= 64:
            raise ValueError("REID_CPP_THREADS must be between 1 and 64")
        # Load by absolute path; the core independently loads the configured ORT.
        self._lib = ct.CDLL(str(path))
        self._lib.reid_abi_version.restype = ct.c_int
        if self._lib.reid_abi_version() != 1:
            raise RuntimeError("unsupported ReID C++ ABI version")
        self._lib.reid_create.argtypes = [ct.c_char_p, ct.c_char_p, ct.c_int, ct.c_char_p, ct.c_size_t]
        self._lib.reid_create.restype = ct.c_void_p
        self._lib.reid_destroy.argtypes = [ct.c_void_p]
        self._lib.reid_destroy.restype = None
        self._lib.reid_shape.argtypes = [ct.c_void_p] + [ct.POINTER(ct.c_int)] * 4 + [ct.c_char_p, ct.c_size_t]
        self._lib.reid_shape.restype = ct.c_int
        self._lib.reid_infer.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_size_t, ct.c_int,
                                       ct.c_void_p, ct.c_size_t, ct.c_char_p, ct.c_size_t]
        self._lib.reid_infer.restype = ct.c_int
        error = ct.create_string_buffer(4096)
        self._handle = self._lib.reid_create(str(ort_library_path()).encode("utf-8"),
                                            self.model_path.encode("utf-8"), self.threads, error, len(error))
        if not self._handle:
            raise RuntimeError(error.value.decode("utf-8", errors="replace"))
        w, h, dim, dynamic = (ct.c_int() for _ in range(4))
        if self._lib.reid_shape(self._handle, ct.byref(w), ct.byref(h), ct.byref(dim), ct.byref(dynamic), error, len(error)):
            self.close()
            raise RuntimeError(error.value.decode("utf-8", errors="replace"))
        self.width, self.height, self.dim, self.dynamic_batch = w.value, h.value, dim.value, bool(dynamic.value)

    def extract(self, crops) -> np.ndarray:
        crops = list(crops)
        if not crops:
            return np.empty((0, self.dim), dtype=np.float32)
        with self._condition:
            if self._closing or not self._handle:
                raise RuntimeError("ReID C++ session is closed")
            self._active += 1
        try:
            results = []
            for start in range(0, len(crops), 64):
                batch = crops[start:start + 64]
                resized = []
                for crop in batch:
                    if not isinstance(crop, np.ndarray) or crop.dtype != np.uint8 or crop.ndim != 3 or crop.shape[2] != 3 or not crop.size:
                        raise ValueError("ReID requires non-empty HWC BGR uint8 crops")
                    resized.append(cv2.resize(crop, (self.width, self.height), interpolation=cv2.INTER_LINEAR))
                bgr = np.ascontiguousarray(np.stack(resized), dtype=np.uint8)
                output = np.empty((len(batch), self.dim), dtype=np.float32)
                error = ct.create_string_buffer(4096)
                code = self._lib.reid_infer(self._handle, bgr.ctypes.data, bgr.nbytes, len(batch),
                                            output.ctypes.data, output.size, error, len(error))
                if code:
                    raise RuntimeError(error.value.decode("utf-8", errors="replace"))
                results.append(output)
            return np.concatenate(results, axis=0) if len(results) > 1 else results[0]
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def close(self):
        with self._condition:
            self._closing = True
            while self._active:
                self._condition.wait()
            if self._handle:
                self._lib.reid_destroy(self._handle)
                self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def __del__(self):
        # Eviction drops only the cache reference; in-flight callers own theirs.
        if getattr(self, "_handle", None):
            self.close()


def get_session(model_path) -> NativeReidSession:
    path = Path(model_path).resolve()
    stat = path.stat()
    threads = int(os.environ.get("REID_CPP_THREADS", "2"))
    key = (str(path), stat.st_mtime_ns, stat.st_size, threads, str(library_path()), str(ort_library_path()))
    with _cache_lock:
        session = _sessions.get(key)
        if session is not None:
            _sessions.move_to_end(key)
            return session
        session = NativeReidSession(path, threads=threads)
        for stale in [k for k in _sessions if k[0] == str(path)]:
            del _sessions[stale]
        _sessions[key] = session
        while len(_sessions) > _MAX_SESSIONS:
            _sessions.popitem(last=False)
        return session


def extract_batch(model_path, crops):
    started = time.perf_counter()
    session = get_session(model_path)
    features = session.extract(crops)
    return features, {
        "backend": "reid-cpp-ort", "provider": "onnxruntime-cpp-cpu",
        "onnx": Path(model_path).name, "modelVersion": Path(model_path).name,
        "inputSize": [session.width, session.height], "dim": session.dim,
        "batchSize": len(features), "dynamicBatch": session.dynamic_batch,
        "threads": session.threads, "latencyMs": round((time.perf_counter() - started) * 1000, 2),
    }
