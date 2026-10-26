"""Local-only CPU inference for uploaded audio files.

SDK imports are lazy. A single lock spans loading and inference; the one-entry
cache is emptied *before* loading a different model to bound resident weights.
Streaming models consume file chunks here, not a microphone or websocket.

API contracts: sherpa-onnx v1.13.3 online/offline_recognizer.py;
moonshine-voice 0.1.5 Transcriber/Stream; faster-whisper WhisperModel.
"""
from __future__ import annotations

import gc
import importlib
import math
from pathlib import Path
import re
import subprocess
from threading import RLock

import numpy as np

from services.bounded_cache import BoundedCache

_MODEL_CACHE = BoundedCache(1)
_INFERENCE_LOCK = RLock()
_SAMPLE_RATE = 16000
_CHUNK_SAMPLES = 3200
_MAX_AUDIO_SECONDS = {'qwen3': 60, 'parakeet': 120, 'zipformer': 600, 'moonshine': 600, 'faster-whisper': 600}
_MOONSHINE_FILES = (
    'adapter.ort', 'cross_kv.ort', 'decoder_kv.ort', 'encoder.ort',
    'frontend.model.ort', 'frontend.weights.ort', 'streaming_config.json', 'tokenizer.bin',
)
_MOONSHINE_ARCHES = {
    'tiny-streaming': 'TINY_STREAMING',
    'small-streaming': 'SMALL_STREAMING',
    'medium-streaming': 'MEDIUM_STREAMING',
}
_LANGUAGE_NAMES = dict(zip(
    ('chinese english cantonese arabic german french spanish portuguese indonesian '
     'italian korean russian thai vietnamese japanese turkish hindi malay dutch '
     'swedish danish finnish polish czech filipino persian greek hungarian '
     'macedonian romanian').split(),
    'zh en yue ar de fr es pt id it ko ru th vi ja tr hi ms nl sv da fi pl cs fil fa el hu mk ro'.split(),
))


def _dependency(module_name: str, package: str):
    try:
        return importlib.import_module(module_name)
    except (ImportError, OSError) as exc:
        raise ValueError(f'CPU ASR requires {package}; install the CPU ASR runtime dependencies. {exc}') from exc


def _require_assets(root: Path, filenames):
    missing = [name for name in filenames if not (root / name).is_file()]
    if missing:
        raise ValueError(f'Local model assets are incomplete in {root}: {", ".join(missing)}. Download this model first.')


def _decode_audio(path: str, *, max_seconds: int = 600) -> np.ndarray:
    """Bound decoded PCM before buffering; caller rejects the extra second."""
    audio = Path(path).resolve()
    if not audio.is_file():
        raise ValueError(f'Audio file does not exist: {audio}')
    ffmpeg = _dependency('imageio_ffmpeg', 'imageio-ffmpeg')
    try:
        process = subprocess.run(
            [ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error', '-i', str(audio),
             '-vn', '-af', 'aresample=16000:out_chlayout=mono:rematrix_maxval=1.0',
             '-ac', '1', '-ar', str(_SAMPLE_RATE), '-t', str(max_seconds + 1), '-f', 'f32le',
             '-acodec', 'pcm_f32le', 'pipe:1'],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except (OSError, RuntimeError) as exc:
        raise ValueError(f'Unable to decode audio with imageio-ffmpeg: {exc}') from exc
    if process.returncode:
        detail = process.stderr.decode('utf-8', errors='replace')[-1500:]
        raise ValueError(f'Unable to decode audio: {detail}')
    if not process.stdout or len(process.stdout) % 4:
        raise ValueError('Audio contains no decodable samples.')
    samples = np.frombuffer(process.stdout, dtype='<f4').astype(np.float32, copy=True)
    if not np.isfinite(samples).all():
        raise ValueError('Audio contains invalid non-finite samples.')
    return samples


def _load_model(engine: str, root: Path, threads: int, model_arch: str | None):
    if engine == 'faster-whisper':
        # WhisperModel otherwise calls Tokenizer.from_pretrained even with
        # local_files_only=True when tokenizer.json is missing.
        _require_assets(root, ('model.bin', 'config.json', 'tokenizer.json'))
        sdk = _dependency('faster_whisper', 'faster-whisper')
        return sdk.WhisperModel(str(root), device='cpu', compute_type='int8',
                                cpu_threads=threads, num_workers=1, local_files_only=True)
    if engine == 'moonshine':
        _require_assets(root, _MOONSHINE_FILES)
        sdk = _dependency('moonshine_voice', 'moonshine-voice>=0.1.5')
        arch = getattr(sdk.ModelArch, _MOONSHINE_ARCHES[model_arch])
        # 0.1.5 exposes provider selection, but no thread-count option.
        return sdk.Transcriber(model_path=str(root), model_arch=arch, options={'ort_provider': 'cpu'})
    sdk = _dependency('sherpa_onnx', 'sherpa-onnx>=1.13.3')
    common = dict(num_threads=threads, provider='cpu', sample_rate=_SAMPLE_RATE,
                  decoding_method='greedy_search')
    if engine == 'qwen3':
        _require_assets(root, ('conv_frontend.onnx', 'encoder.int8.onnx', 'decoder.int8.onnx',
                              'tokenizer/vocab.json', 'tokenizer/merges.txt', 'tokenizer/tokenizer_config.json'))
        factory = getattr(sdk.OfflineRecognizer, 'from_qwen3_asr', None)
        if factory is None:
            raise ValueError('Qwen3 CPU ASR requires sherpa-onnx>=1.13.3 with from_qwen3_asr support.')
        return factory(conv_frontend=str(root / 'conv_frontend.onnx'),
                       encoder=str(root / 'encoder.int8.onnx'), decoder=str(root / 'decoder.int8.onnx'),
                       tokenizer=str(root / 'tokenizer'), feature_dim=128,
                       max_new_tokens=512, max_total_len=2048, **common)
    decoder = 'decoder.onnx' if engine == 'zipformer' else 'decoder.int8.onnx'
    _require_assets(root, ('encoder.int8.onnx', decoder, 'joiner.int8.onnx', 'tokens.txt'))
    transducer = dict(encoder=str(root / 'encoder.int8.onnx'), decoder=str(root / decoder),
                      joiner=str(root / 'joiner.int8.onnx'), tokens=str(root / 'tokens.txt'),
                      feature_dim=80, **common)
    if engine == 'zipformer':
        return sdk.OnlineRecognizer.from_transducer(enable_endpoint_detection=False, **transducer)
    # The official NeMo TDT export carries duration metadata in its ONNX
    # joiner. sherpa dispatches its TDT decoder via nemo_transducer, not an
    # invented Python tdt/max_duration setting.
    return sdk.OfflineRecognizer.from_transducer(model_type='nemo_transducer', **transducer)


def _model(engine, root, threads, model_arch):
    key = (engine, str(root), threads, model_arch)
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached
    # Clear before creating the new instance (LRU eviction after creation
    # would temporarily retain two multi-GB models).
    for old_key in list(_MODEL_CACHE):
        previous = _MODEL_CACHE.pop(old_key)
        close = getattr(previous, 'close', None)
        if close is not None:
            close()
        del previous
    gc.collect()
    instance = _load_model(engine, root, threads, model_arch)
    _MODEL_CACHE[key] = instance
    return instance


def _language(value):
    if not value:
        return None
    normalized = str(value).strip().lower()
    return _LANGUAGE_NAMES.get(normalized, normalized) if normalized != 'auto' else None


def _result(text, language, segments, backend, timestamp_kind=None):
    result = dict(text=text.strip(), language=_language(language), emotion=None,
                  events=[], segments=segments, timestampsAvailable=bool(segments), backend=backend)
    if timestamp_kind and segments:
        result['timestampKind'] = timestamp_kind
    return result


def _token_result(result, language, backend):
    """Token starts are metadata; they cannot become valid subtitle intervals."""
    tokens = list(getattr(result, 'tokens', []) or [])
    timestamps = list(getattr(result, 'timestamps', []) or [])
    offset = float(getattr(result, 'start_time', 0.0) or 0.0)
    valid_tokens, valid_times = [], []
    if len(tokens) == len(timestamps):
        for token, timestamp in zip(tokens, timestamps):
            timestamp = float(timestamp) + offset
            if math.isfinite(timestamp) and timestamp >= 0:
                valid_tokens.append(str(token))
                valid_times.append(timestamp)
    payload = _result(str(result.text), getattr(result, 'lang', '') or language, [], backend)
    if valid_times:
        payload.update(tokens=valid_tokens, timestamps=valid_times, timestampKind='token-start')
    return payload


def _run_zipformer(model, samples):
    stream = model.create_stream()
    for offset in range(0, len(samples), _CHUNK_SAMPLES):
        stream.accept_waveform(_SAMPLE_RATE, samples[offset:offset + _CHUNK_SAMPLES])
        while model.is_ready(stream):
            model.decode_stream(stream)
    # Official online-decode-files.py adds .66 s of tail before input_finished.
    stream.accept_waveform(_SAMPLE_RATE, np.zeros(10560, dtype=np.float32))
    stream.input_finished()
    while model.is_ready(stream):
        model.decode_stream(stream)
    return _token_result(model.get_result_all(stream), 'zh', 'sherpa-onnx-cpu')


def _run_moonshine(model, samples):
    stream = model.create_stream()
    errors = []
    def listener(event):
        error = getattr(event, 'error', None)
        if error is not None:
            errors.append(error)
    stream.add_listener(listener)
    try:
        stream.start()
        for offset in range(0, len(samples), _CHUNK_SAMPLES):
            stream.add_audio(samples[offset:offset + _CHUNK_SAMPLES].tolist(), sample_rate=_SAMPLE_RATE)
            if errors:
                raise RuntimeError(f'Moonshine streaming inference failed: {errors[0]}') from errors[0]
        # stop() flushes buffered trailing audio and returns its final Transcript.
        transcript = stream.stop()
        if errors:
            raise RuntimeError(f'Moonshine streaming inference failed: {errors[0]}') from errors[0]
        if transcript is None:
            raise RuntimeError('Moonshine failed to return a final transcript after flushing audio.')
        segments, texts = [], []
        for line in transcript.lines:
            text = line.text.strip()
            if not text:
                continue
            texts.append(text)
            start, duration = float(line.start_time), float(line.duration)
            if math.isfinite(start) and math.isfinite(duration) and start >= 0 and duration >= 0:
                segments.append({'start': start, 'end': start + duration, 'text': text})
        return _result(' '.join(texts), 'en', segments, 'moonshine-voice-cpu', 'line')
    finally:
        stream.close()


def transcribe(engine: str, model_dir: str, audio_path: str, *, threads: int = 4,
               language: str = 'auto', model_arch: str | None = None) -> dict:
    """Transcribe a file with local weights and explicit CPU providers.

    Qwen3/Parakeet have no forced-language argument in the pinned sherpa API;
    only ``auto`` is accepted for them. Zipformer weights here are Chinese and
    the published Moonshine streaming weights are English. For these fixed
    models, auto means use the model language rather than claim detection.
    """
    if engine not in {'zipformer', 'faster-whisper', 'parakeet', 'moonshine', 'qwen3'}:
        raise ValueError(f'Unknown CPU ASR engine: {engine}')
    if isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= 256:
        raise ValueError('threads must be an integer between 1 and 256.')
    if not isinstance(language, str) or not re.fullmatch(r'[a-z]{2,3}|auto', language):
        raise ValueError('language must be auto or a lower-case language code.')
    if engine in {'qwen3', 'parakeet'} and language != 'auto':
        raise ValueError(f'{engine} CPU API supports automatic language recognition only; use language=auto.')
    fixed_language = {'zipformer': 'zh', 'moonshine': 'en'}.get(engine)
    if fixed_language and language not in {'auto', fixed_language}:
        raise ValueError(f'{engine} local model supports language={fixed_language} or auto.')
    if engine == 'moonshine' and model_arch not in _MOONSHINE_ARCHES:
        raise ValueError('model_arch must be tiny-streaming, small-streaming or medium-streaming.')
    root = Path(model_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f'model_dir must be an existing local model directory: {root}')
    if not Path(audio_path).is_file():
        raise ValueError(f'Audio file does not exist: {audio_path}')
    maximum = _MAX_AUDIO_SECONDS[engine]
    # Decode at most maximum+1 seconds to detect oversize input without
    # allocating PCM for the entire (potentially hours-long) compressed file.
    samples = _decode_audio(audio_path, max_seconds=maximum)
    if len(samples) > maximum * _SAMPLE_RATE:
        raise ValueError(f'{engine} CPU ASR supports audio up to {maximum} seconds; split this file into shorter recordings.')
    with _INFERENCE_LOCK:
        model = _model(engine, root, threads, model_arch)
        if engine == 'zipformer':
            return _run_zipformer(model, samples)
        if engine == 'moonshine':
            return _run_moonshine(model, samples)
        if engine == 'faster-whisper':
            pieces, info = model.transcribe(samples, language=None if language == 'auto' else language,
                                            beam_size=5, word_timestamps=False)
            segments = [{'start': float(piece.start), 'end': float(piece.end), 'text': piece.text.strip()}
                        for piece in pieces if piece.text.strip()]
            return _result(' '.join(piece['text'] for piece in segments), info.language,
                           segments, 'faster-whisper-cpu', 'segment')
        stream = model.create_stream()
        stream.accept_waveform(_SAMPLE_RATE, samples)
        model.decode_stream(stream)
        return _token_result(stream.result, None, 'sherpa-onnx-cpu')
