"""MOSS-Music GGUF through HOT-Step's audio/DeepStack-aware ace-caption CLI.

Ordinary llama.cpp and Transformers GGUF loaders cannot run this audio tower.
No remote inference or automatic model download is performed by analyze().
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

from flask import current_app, has_app_context

MODEL_KEY = 'moss-music-8b-instruct-gguf'
REPO_ID = 'scragnog/MOSS-Music-8B-Instruct-GGUF'
WEIGHT_FILES = ('moss-lm-q8_0.gguf', 'moss-aud-f16.gguf')
MODEL_FIELDS = dict(
    model_name='MOSS-Music 8B Instruct GGUF（歌词 / 音乐理解）', category='音乐理解',
    task='audio-text-to-text', library='moss-music-gguf', version='q8_0',
    source_url=f'https://huggingface.co/{REPO_ID}',
    description='音乐理解与歌词转写；需 HOT-Step ace-caption 音频/DeepStack 引擎。'
                'CPU Q8 语言模型 + FP16 音频编码器约 10.43GB；建议 32GB 内存。普通语音转写优先 SenseVoice ONNX。',
    status='0')
_run_lock = threading.Lock()


def _config(key, default):
    return current_app.config.get(key, default) if has_app_context() else default


def model_directory(model_dir=None):
    if model_dir:
        path = Path(model_dir)
        return path.parent if path.is_file() else path
    root = _config('MODEL_FOLDER', Path(__file__).resolve().parents[1] / 'uploads' / 'models')
    return Path(root) / MODEL_KEY


def _executable():
    default = Path(__file__).resolve().parents[1] / 'runtime' / 'hot-step' / (
        'ace-caption.exe' if os.name == 'nt' else 'ace-caption')
    configured = str(_config('MOSS_MUSIC_EXECUTABLE', '') or default)
    return str(Path(configured).resolve()) if Path(configured).is_file() else shutil.which(configured)


def _gguf_present(path):
    try:
        with path.open('rb') as f:
            return f.read(4) == b'GGUF' and path.stat().st_size > 24
    except OSError:
        return False


def runtime_status(model_dir=None):
    directory = model_directory(model_dir)
    missing = []
    if not any(_gguf_present(directory / name) for name in (WEIGHT_FILES[0], 'moss-lm-f16.gguf')):
        missing.append(WEIGHT_FILES[0])
    if not _gguf_present(directory / WEIGHT_FILES[1]):
        missing.append(WEIGHT_FILES[1])
    if not _executable():
        missing.append('ace-caption（运行 scripts/prepare_moss_music.py --runtime-only）')
    return {
        'runtimeReady': not missing,
        'runtimeMessage': '缺少：' + '、'.join(missing) if missing else 'MOSS-Music CPU 文件已就绪（尚未验证推理）',
        'maxAudioSeconds': int(_config('MOSS_MUSIC_MAX_SECONDS', 60)),
    }


def download_weights(folder, token=None):
    """Download Q8 LM + FP16 audio tower only; never fetch the redundant FP16 LM."""
    from huggingface_hub import hf_hub_download
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    missing = [name for name in WEIGHT_FILES if not _gguf_present(folder / name)]
    # The pair is about 10.43 GB. Check before starting a download that cannot fit.
    needed = sum(8_710_000_000 if name == WEIGHT_FILES[0] else 1_720_000_000 for name in missing)
    if missing and shutil.disk_usage(folder).free < needed + 512 * 1024**2:
        raise ValueError('MOSS-Music 磁盘空间不足：Q8 模型 + 音频编码器约 10.43 GB，请至少准备 11 GB 可用空间')
    for name in WEIGHT_FILES:
        if name in missing:
            hf_hub_download(repo_id=REPO_ID, filename=name, local_dir=str(folder), token=token)
        if not _gguf_present(folder / name):
            raise ValueError(f'MOSS-Music 权重无效：{name}')
    return sum((folder / name).stat().st_size for name in WEIGHT_FILES)


def _prepare_wav(source, work):
    try:
        with wave.open(str(source), 'rb') as f:
            if f.getnchannels() == 1 and f.getframerate() == 16000 and f.getsampwidth() == 2:
                return Path(source), f.getnframes() / f.getframerate()
    except (wave.Error, EOFError):
        pass
    import imageio_ffmpeg
    out = work / 'input.wav'
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-nostdin', '-hide_banner', '-loglevel', 'error',
           '-threads', '1', '-i', str(source), '-vn', '-ac', '1', '-ar', '16000',
           '-c:a', 'pcm_s16le', str(out)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
                          **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
    if proc.returncode != 0:
        raise ValueError('音频转换失败，请检查媒体文件是否含有效音轨')
    with wave.open(str(out), 'rb') as f:
        return out, f.getnframes() / f.getframerate()


def analyze(audio_path, *, model_dir=None, mode='lyrics'):
    if mode not in ('lyrics', 'prose', 'mm3'):
        raise ValueError('MOSS-Music 模式须为 lyrics / prose / mm3')
    state = runtime_status(model_dir)
    if not state['runtimeReady']:
        raise ValueError(state['runtimeMessage'])
    if not _run_lock.acquire(blocking=False):
        raise ValueError('MOSS-Music 正在推理，请等待当前任务完成')
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix='moss_music_') as tmp:
            work = Path(tmp)
            source, seconds = _prepare_wav(Path(audio_path).resolve(), work)
            limit = max(1, min(420, state['maxAudioSeconds']))
            if seconds <= 0 or seconds > limit:
                raise ValueError(f'MOSS-Music CPU 当前支持 0–{limit} 秒音频，请先切分（不会自动截断）')
            output = work / 'out.txt'
            cmd = [_executable(), '--models', str(model_directory(model_dir).resolve()),
                   '--src-audio', str(source), '--mode', mode, '-o', str(output),
                   '--max-tokens', str(max(1, min(4096, int(_config('MOSS_MUSIC_MAX_TOKENS', 512))))),
                   '--max-seconds', str(limit), '--encoder-window', '400',
                   '--temperature', '0', '--rep-penalty', '1.0', '--freq-penalty', '0.3']
            env = os.environ.copy()
            env.update(GGML_BACKEND='CPU', GGML_N_THREADS=str(max(1, int(_config(
                'MOSS_MUSIC_THREADS', max(1, (os.cpu_count() or 2) // 2))))))
            try:
                proc = subprocess.run(cmd, cwd=str(Path(cmd[0]).parent), env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      encoding='utf-8', errors='replace',
                                      timeout=float(_config('MOSS_MUSIC_TIMEOUT_SECONDS', 1800)),
                                      **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError('MOSS-Music CPU 推理超时，请缩短音频或减少输出长度') from exc
            if proc.returncode:
                raise RuntimeError(f'ace-caption 推理失败：{proc.stderr[-1000:]}')
            text = output.read_text(encoding='utf-8').strip() if output.is_file() else ''
            if not text:
                raise RuntimeError('ace-caption 未生成文本，请检查运行时版本与权重')
            elapsed = time.perf_counter() - started
            return dict(text=text, language=None, emotion=None, events=[], segments=[],
                        timestampsAvailable=False, mode=mode, backend='hot-step-cpu',
                        durationSeconds=seconds, elapsedSeconds=round(elapsed, 3),
                        rtf=round(elapsed / seconds, 4))
    finally:
        _run_lock.release()
