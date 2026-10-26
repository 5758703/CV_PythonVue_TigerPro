"""CPU ASR catalog, local assets and inference dispatch for the management UI."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import sys
import sysconfig
import tarfile
import tempfile
import threading
import time

from flask import current_app, has_app_context

BACKEND = Path(__file__).resolve().parents[1]
EXTRA_PACKAGES = BACKEND / 'runtime' / f'cpu-asr-python-{sys.implementation.cache_tag}-{sysconfig.get_platform()}'
if EXTRA_PACKAGES.is_dir() and str(EXTRA_PACKAGES) not in sys.path:
    sys.path.insert(0, str(EXTRA_PACKAGES))

_RELEASE = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/'
_MOON_FILES = ('adapter.ort', 'cross_kv.ort', 'decoder_kv.ort', 'encoder.ort',
               'frontend.model.ort', 'frontend.weights.ort', 'streaming_config.json', 'tokenizer.bin')
CPU_ASR_MODELS = {
    'paraformer-zh': dict(
        name='Paraformer-zh 中英语音识别（CPU）', engine='paraformer', library='funasr',
        source='https://huggingface.co/funasr/paraformer-zh', repo='funasr/paraformer-zh',
        files=('model.pt', 'config.yaml', 'am.mvn', 'tokens.json'), expanded_bytes=1_000_000_000,
        dependencies=('funasr', 'torchaudio'), languages=('auto',), streaming=False,
        hint='普通话 / 中英混合；非自回归文件转写，沿用现有 Paraformer 权重。'),
    'streaming-zipformer-zh-int8': dict(
        name='Streaming Zipformer 中文 INT8（CPU）', engine='zipformer', library='sherpa-onnx-asr',
        source=_RELEASE+'sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30.tar.bz2',
        archive_bytes=132_634_597, expanded_bytes=180_000_000,
        files=('encoder.int8.onnx', 'decoder.onnx', 'joiner.int8.onnx', 'tokens.txt'),
        dependencies=('sherpa_onnx',), languages=('auto',), streaming=True,
        hint='中文流式 Transducer；上传文件分块解码并刷新末尾音频。'),
    'faster-whisper-small-int8': dict(
        name='faster-whisper Small INT8（CPU / 多语种）', engine='faster-whisper', library='faster-whisper',
        source='https://huggingface.co/Systran/faster-whisper-small', repo='Systran/faster-whisper-small',
        files=('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'), expanded_bytes=510_000_000,
        dependencies=('faster_whisper', 'ctranslate2', 'av'),
        languages=('auto', 'zh', 'en', 'ja', 'ko', 'de', 'fr', 'es'), streaming=False,
        hint='多语种文件转写；CTranslate2 CPU INT8 计算，磁盘权重采用上游 Small 转换包。'),
    'parakeet-tdt-0p6b-v3-int8': dict(
        name='Parakeet TDT 0.6B v3 INT8（CPU / 欧洲语言）', engine='parakeet', library='sherpa-onnx-asr',
        source=_RELEASE+'sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2',
        archive_bytes=487_170_055, expanded_bytes=700_000_000,
        files=('encoder.int8.onnx', 'decoder.int8.onnx', 'joiner.int8.onnx', 'tokens.txt'),
        dependencies=('sherpa_onnx',), languages=('auto',), streaming=False,
        hint='25 种欧洲语言（含英语），自动识别；不支持中文，请按录音语言选择。'),
    'qwen3-asr-0p6b-int8': dict(
        name='Qwen3-ASR 0.6B INT8（CPU / 多语种与方言）', engine='qwen3', library='sherpa-onnx-asr',
        source=_RELEASE+'sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25.tar.bz2',
        archive_bytes=878_702_423, expanded_bytes=1_050_000_000,
        files=('conv_frontend.onnx', 'encoder.int8.onnx', 'decoder.int8.onnx',
               'tokenizer/vocab.json', 'tokenizer/merges.txt', 'tokenizer/tokenizer_config.json'),
        dependencies=('sherpa_onnx',), languages=('auto',), streaming=False,
        hint='30 种语言及 22 种中文方言；官方 sherpa-onnx INT8 导出，输出文本无可靠字幕时间戳。'),
}
for _size, _bytes in [('tiny', 45_233_659), ('small', 142_300_974), ('medium', 269_141_623)]:
    CPU_ASR_MODELS[f'moonshine-{_size}-streaming'] = dict(
        name=f'Moonshine {_size.title()} Streaming（CPU / 英文）', engine='moonshine',
        library='moonshine-streaming', arch=f'{_size}-streaming',
        source='https://github.com/moonshine-ai/moonshine', files=_MOON_FILES,
        expanded_bytes=_bytes, dependencies=('moonshine_voice',), languages=('en',), streaming=True,
        hint=f'Moonshine {_size.title()} 英文流式模型；本页支持上传文件分块识别，不提供实时麦克风入口。')

CPU_MODEL_KEYS = tuple(CPU_ASR_MODELS)
CPU_LIBRARIES = ('sherpa-onnx-asr', 'faster-whisper', 'moonshine-streaming')
_download_lock = threading.Lock()


def get_spec(key, library=None):
    spec = CPU_ASR_MODELS.get(key)
    return spec if spec and (library is None or library == spec['library']) else None


def _config(key, default):
    return current_app.config.get(key, default) if has_app_context() else default


def model_directory(key, model_dir=None):
    if key not in CPU_ASR_MODELS:
        raise ValueError('不支持的 CPU 语音模型')
    if model_dir:
        path = Path(model_dir)
        return path.parent if path.is_file() else path
    root = Path(_config('MODEL_FOLDER', BACKEND / 'uploads' / 'models')).resolve()
    target = (root / key).resolve()
    if not target.is_relative_to(root):
        raise ValueError('模型目录包含越界链接')
    return target


def _has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _missing_files(spec, folder):
    if spec['engine'] == 'moonshine':
        from services.moonshine_assets import missing_files
        return missing_files(spec['arch'], str(folder))
    root = folder.resolve()
    missing = []
    for name in spec['files']:
        path = folder / name
        try:
            valid = path.resolve().is_relative_to(root) and path.is_file() and path.stat().st_size > 0
        except OSError:
            valid = False
        if not valid:
            missing.append(name)
    return missing


def runtime_status(key, model_dir=None, *, dependency_probe=None):
    spec = CPU_ASR_MODELS[key]
    missing = _missing_files(spec, model_directory(key, model_dir))
    probe = dependency_probe or _has_module
    dependencies = [name for name in (*spec['dependencies'], 'imageio_ffmpeg') if not probe(name)]
    reasons = []
    if missing:
        reasons.append('缺少权重：' + '、'.join(missing))
    if dependencies:
        reasons.append('缺少依赖：' + '、'.join(dependencies) + '（请准备 CPU ASR 运行环境）')
    return dict(runtimeReady=not reasons,
                runtimeMessage='；'.join(reasons) if reasons else '本地权重和 CPU 依赖已齐备',
                asrCpu=True, asrStreaming=spec['streaming'], asrHint=spec['hint'],
                maxAudioSeconds=(None if spec['engine'] == 'paraformer' else {'qwen3': 60, 'parakeet': 120}.get(spec['engine'], 600)),
                asrLanguages=[{'value': lang, 'label': {
                    'auto': '自动识别', 'zh': '中文', 'en': '英文', 'ja': '日文', 'ko': '韩文',
                    'yue': '粤语', 'de': '德文', 'fr': '法文', 'es': '西班牙文',
                }[lang]} for lang in spec['languages']])


def seed_cpu_asr_models():
    """Register once; preserve user metadata, disabled state and custom bindings."""
    from extensions import db
    from models import AiModel
    changed = False
    for key, spec in CPU_ASR_MODELS.items():
        model = AiModel.query.filter_by(model_key=key).first()
        if model is None:
            model = AiModel(model_key=key, model_name=spec['name'], category='语音识别',
                            task='automatic-speech-recognition', library=spec['library'],
                            source_url=spec['source'], description=spec['hint'], status='0', version='cpu')
            db.session.add(model)
            changed = True
        folder = model_directory(key)
        if not model.file_path and not _missing_files(spec, folder):
            model.file_path = f'models/{key}'
            model.file_size = sum((folder / name).stat().st_size for name in spec['files'])
            changed = True
    if changed:
        db.session.commit()
    return changed


def _extract_archive(archive, target_dir, required):
    """Extract only declared data files; never invoke tar extraction on arbitrary paths."""
    target = Path(target_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    required = set(required)
    with tarfile.open(archive, 'r|bz2') as tar:
        for entry in tar:
            path = PurePosixPath(entry.name)
            if path.is_absolute() or PureWindowsPath(entry.name).is_absolute() or '..' in path.parts or '\\' in entry.name:
                raise ValueError('模型压缩包包含不安全路径')
            if entry.issym() or entry.islnk():
                raise ValueError('模型压缩包不允许链接')
            if not entry.isfile() or len(path.parts) < 2:
                continue
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            sample = relative.startswith('test_wavs/') and relative.endswith('.wav') and entry.size < 2_000_000
            if relative not in required and not sample:
                continue
            out = (target / relative).resolve()
            if not out.is_relative_to(target):
                raise ValueError('模型压缩包路径越界')
            out.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(entry) as source, out.open('wb') as dest:
                shutil.copyfileobj(source, dest)
    missing = [name for name in required if not (target / name).is_file() or not (target / name).stat().st_size]
    if missing:
        raise ValueError('压缩包缺少必要模型文件：' + '、'.join(sorted(missing)))


def download_model(key, folder=None, *, token=None):
    import requests
    spec = CPU_ASR_MODELS[key]
    target = model_directory(key, folder)
    managed = Path(_config('MODEL_FOLDER', BACKEND / 'uploads' / 'models')) / key
    if os.path.abspath(target) == os.path.abspath(managed):
        target = model_directory(key)  # Validate even when callers pass the managed path explicitly.
    if target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()):
        raise ValueError('模型下载目录包含越界链接')
    target.mkdir(parents=True, exist_ok=True)
    with _download_lock:
        if spec['engine'] == 'moonshine':
            from services.moonshine_assets import download_model as moon_download
            return moon_download(spec['arch'], str(target))
        if 'repo' in spec:
            from services.cpu_asr_hf_assets import download_hf_files
            return download_hf_files(spec['repo'], str(target), spec['files'], token=token)
        if not _missing_files(spec, target):
            return sum((target / name).stat().st_size for name in spec['files'])
        needed = spec['expanded_bytes'] + spec.get('archive_bytes', 0) + 128 * 1024**2
        if shutil.disk_usage(target).free < needed:
            raise ValueError(f'{spec["name"]} 磁盘空间不足，下载准备至少需要约 {needed / 1024**3:.2f} GiB')
        if 'source' in spec:
            with tempfile.TemporaryDirectory(prefix='.cpu_asr_', dir=target.parent) as tmp:
                temporary = Path(tmp).resolve()
                if not temporary.is_relative_to(target.parent.resolve()):
                    raise ValueError('模型下载临时目录无效')
                archive = temporary / 'model.tar.bz2'
                total = 0
                with requests.get(spec['source'], stream=True, timeout=(30, 120)) as response:
                    response.raise_for_status()
                    with archive.open('wb') as output:
                        for chunk in response.iter_content(1024**2):
                            output.write(chunk)
                            total += len(chunk)
                            if total % (64 * 1024**2) == 0:
                                print(f'{key}: {total // 1024**2} MiB downloaded', flush=True)
                if total != spec['archive_bytes']:
                    raise ValueError('模型压缩包长度不符，未发布不完整权重')
                extracted = temporary / 'extracted'
                _extract_archive(archive, extracted, spec['files'])
                for source in extracted.rglob('*'):
                    if source.is_file():
                        destination = target / source.relative_to(extracted)
                        if not destination.resolve().is_relative_to(target.resolve()):
                            raise ValueError('模型目标路径包含越界链接')
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(source, destination)
        missing = _missing_files(spec, target)
        if missing:
            raise ValueError('模型下载不完整：' + '、'.join(missing))
        return sum((target / name).stat().st_size for name in spec['files'])


def _ensure_funasr_ffmpeg():
    """FunASR probes bare `ffmpeg`; expose the already bundled executable locally."""
    import imageio_ffmpeg
    source = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    folder = BACKEND / 'runtime' / 'cpu-asr-bin'
    if not folder.resolve().is_relative_to(BACKEND.resolve()):
        raise ValueError('CPU ASR ffmpeg 运行目录无效')
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    if target.is_symlink() or not target.resolve().is_relative_to(folder.resolve()):
        raise ValueError('CPU ASR ffmpeg 文件路径无效')
    if not target.is_file() or target.stat().st_size != source.stat().st_size:
        temporary = folder / f'.ffmpeg-{os.getpid()}-{threading.get_ident()}.tmp'
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    entries = os.environ.get('PATH', '').split(os.pathsep)
    if str(folder) not in entries:
        os.environ['PATH'] = os.pathsep.join([str(folder), *entries])


def transcribe(key, audio_path, *, model_dir=None, language='auto'):
    spec = CPU_ASR_MODELS[key]
    if language == 'auto' and spec['languages'] == ('en',):
        language = 'en'
    if language not in spec['languages']:
        raise ValueError('当前模型不支持所选语言')
    state = runtime_status(key, model_dir)
    if not state['runtimeReady']:
        raise ValueError(state['runtimeMessage'])
    started = time.perf_counter()
    directory = str(model_directory(key, model_dir))
    if spec['engine'] == 'paraformer':
        _ensure_funasr_ffmpeg()
        from inference import transcribe_audio
        result = transcribe_audio(directory, audio_path)
        result.setdefault('segments', [])
        result.setdefault('timestampsAvailable', bool(result['segments']))
    else:
        from services.cpu_asr_worker_client import transcribe_isolated as infer
        result = infer(spec['engine'], directory, str(audio_path),
                       threads=int(_config('CPU_ASR_THREADS', 4)), language=language,
                       model_arch=spec.get('arch'), timeout=int(_config('CPU_ASR_TIMEOUT_SECONDS', 1800)))
    result['elapsedSeconds'] = round(time.perf_counter() - started, 3)
    result['modelKey'] = key
    return result
