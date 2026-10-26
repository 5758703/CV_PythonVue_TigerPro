"""Standalone CPU ASR JSON-lines worker. No Flask app, database or Torch import."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import sysconfig
import traceback

RESPONSE_PREFIX = '__CPU_ASR_RESPONSE_V1__:'


def serve(source, destination, transcribe):
    """Handle requests serially and reject native-runtime model switches."""
    model_key = None
    for line in source:
        request = {}
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or request.get('version') != 1:
                raise ValueError('Unsupported CPU ASR request protocol.')
            key = (request['engine'], request['model_dir'], request['threads'], request.get('model_arch'))
            if model_key is not None and model_key != key:
                raise ValueError('CPU ASR model switch requires a new worker process.')
            model_key = key
            result = transcribe(request['engine'], request['model_dir'], request['audio_path'],
                                threads=request['threads'], language=request.get('language', 'auto'),
                                model_arch=request.get('model_arch'))
            response = dict(id=request.get('id'), ok=True, result=result)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            response = dict(id=request.get('id') if isinstance(request, dict) else None,
                            ok=False, error=dict(type=type(exc).__name__, message=str(exc)))
        # Some SDKs write logs without a trailing newline. Start a fresh line
        # so those diagnostics cannot swallow the framed response.
        destination.write('\n' + RESPONSE_PREFIX + json.dumps(response, ensure_ascii=False) + '\n')
        destination.flush()


def main():
    backend = Path(__file__).resolve().parents[1]
    extra = backend / 'runtime' / f'cpu-asr-python-{sys.implementation.cache_tag}-{sysconfig.get_platform()}'
    sys.path.insert(0, str(backend))
    if extra.is_dir():
        sys.path.insert(0, str(extra))
    # Resolve only the adapter and its chosen SDK, never the application or
    # registry imports. The ABI path matches services.cpu_asr.EXTRA_PACKAGES.
    from services.cpu_asr_engines import transcribe
    serve(sys.stdin, sys.stdout, transcribe)


if __name__ == '__main__':
    main()
