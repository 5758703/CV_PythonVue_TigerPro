"""Persistent one-model ASR subprocess; never import native SDKs in the app.

Each model switch replaces the process, unloading its native DLLs as well as
its weights. In particular, CV/PyTorch, sherpa and CTranslate2 do not share an
OpenMP runtime in the backend process.
"""
from __future__ import annotations

import atexit
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
from threading import RLock, Thread
import uuid

_BACKEND = Path(__file__).resolve().parents[1]
_WORKER_SCRIPT = _BACKEND / 'scripts' / 'cpu_asr_worker.py'
_LOG_DIR = _BACKEND / 'runtime' / 'cpu-asr-worker-logs'
_RESPONSE_PREFIX = '__CPU_ASR_RESPONSE_V1__:'
_EOF = object()
_LOCK = RLock()
_WORKER = None


class _Worker:
    def __init__(self, key):
        self.key = key
        self.responses = queue.Queue()
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.log_path = _LOG_DIR / f'worker-{os.getpid()}-{uuid.uuid4().hex}.log'
        self.log = self.log_path.open('ab', buffering=0)
        environment = dict(os.environ)
        # Anaconda NumPy loads threaded MKL while CTranslate2 ships a different
        # Intel OpenMP DLL. Sequential MKL avoids that real, reproduced crash;
        # CTranslate2 inference still uses its explicit cpu_threads setting.
        # This is child-only and does not permit duplicate OpenMP runtimes.
        environment['MKL_THREADING_LAYER'] = 'SEQUENTIAL'
        environment.pop('KMP_DUPLICATE_LIB_OK', None)
        try:
            self.process = subprocess.Popen(
                [sys.executable, '-u', '-X', 'utf8', str(_WORKER_SCRIPT)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                text=True, encoding='utf-8', errors='replace', bufsize=1,
                cwd=str(_BACKEND), env=environment,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except OSError as exc:
            self.log.close()
            raise RuntimeError(f'Unable to start CPU ASR worker: {exc}') from exc
        self.reader = Thread(target=self._read, name='cpu-asr-response-reader', daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                if line.startswith(_RESPONSE_PREFIX):
                    try:
                        self.responses.put(json.loads(line[len(_RESPONSE_PREFIX):]))
                    except ValueError:
                        self.responses.put({'protocolError': 'invalid response JSON'})
                else:
                    self.log.write(line.encode('utf-8', errors='replace'))
        except (OSError, ValueError) as exc:
            self.responses.put({'protocolError': f'stdout reader failed: {exc}'})
        finally:
            self.responses.put(_EOF)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.reader.join(timeout=1)
        for pipe in (self.process.stdin, self.process.stdout):
            if pipe is not None:
                pipe.close()
        self.log.close()


def _cleanup():
    global _WORKER
    with _LOCK:
        if _WORKER is not None:
            _WORKER.close()
            _WORKER = None


atexit.register(_cleanup)


def transcribe_isolated(engine: str, model_dir: str, audio_path: str, *, threads: int = 4,
                        language: str = 'auto', model_arch: str | None = None,
                        timeout: float = 1800) -> dict:
    """Execute CPU ASR safely; retain one process only for this exact model.

    SDK validation errors remain ValueErrors. Native exit, malformed protocol
    and deadlines become RuntimeErrors including the worker's diagnostic log.
    A later request can start a fresh worker; no other model is substituted.
    """
    global _WORKER
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be a positive finite number of seconds.')
    directory = str(Path(model_dir).expanduser().resolve())
    key = (engine, directory, threads, model_arch)
    with _LOCK:
        if _WORKER is not None and (_WORKER.key != key or _WORKER.process.poll() is not None):
            _cleanup()
        if _WORKER is None:
            _WORKER = _Worker(key)
        worker = _WORKER
        request_id = uuid.uuid4().hex
        request = dict(version=1, id=request_id, engine=engine, model_dir=directory,
                       audio_path=str(Path(audio_path).expanduser().resolve()), threads=threads,
                       language=language, model_arch=model_arch)
        try:
            worker.process.stdin.write(json.dumps(request, ensure_ascii=False) + '\n')
            worker.process.stdin.flush()
        except (OSError, ValueError) as exc:
            _cleanup()
            raise RuntimeError(f'CPU ASR worker request failed. See {worker.log_path}: {exc}') from exc
        try:
            response = worker.responses.get(timeout=timeout)
        except queue.Empty as exc:
            _cleanup()
            raise RuntimeError(f'CPU ASR worker timed out after {timeout} seconds. See {worker.log_path}') from exc
        if response is _EOF:
            try:
                code = worker.process.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                code = worker.process.poll()
            _cleanup()
            raise RuntimeError(f'CPU ASR worker exited unexpectedly (exit code {code}). See {worker.log_path}')
        if not isinstance(response, dict) or response.get('id') != request_id or 'ok' not in response:
            _cleanup()
            raise RuntimeError(f'CPU ASR worker protocol error. See {worker.log_path}')
        if not response['ok']:
            error = response.get('error') or {}
            message = str(error.get('message') or 'CPU ASR worker inference failed.')
            if error.get('type') == 'ValueError':
                raise ValueError(message)
            raise RuntimeError(f'{message} See {worker.log_path}')
        result = response.get('result')
        if not isinstance(result, dict):
            _cleanup()
            raise RuntimeError(f'CPU ASR worker protocol error: result must be an object. See {worker.log_path}')
        return result
