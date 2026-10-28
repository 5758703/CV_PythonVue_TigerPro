"""Piper TTS：官方 rhasspy/piper-voices 四档（x_low/low/medium/high）目录与推理。

目录约 177+ 语音、58 语种；按 quality 分档。权重托管于
https://huggingface.co/rhasspy/piper-voices 。

推理路径：本地下载 .onnx + .onnx.json → onnxruntime.InferenceSession 直接加载；
音素化使用 piper 自带的 espeak 桥（不经 PiperVoice 高层封装跑图）。
"""
from __future__ import annotations

import io
import json
import os
import threading
import urllib.error
import urllib.request
from typing import Any

QUALITIES = ("x_low", "low", "medium", "high")

QUALITY_META = {
    "x_low": {
        "label": "极速",
        "model_key": "piper-x_low",
        "model_name": "Piper TTS x_low（极速）",
        "default_voice": "zh_CN-huayan-x_low",
        "hint": "16kHz，体积最小、推理最快，适合边缘与低延迟播报。",
    },
    "low": {
        "label": "快速",
        "model_key": "piper-low",
        "model_name": "Piper TTS low（快速）",
        "default_voice": "en_US-amy-low",
        "hint": "16kHz，速度快，通用英文播报推荐。",
    },
    "medium": {
        "label": "均衡",
        "model_key": "piper-medium",
        "model_name": "Piper TTS medium（推荐）",
        "default_voice": "zh_CN-huayan-medium",
        "hint": "22.05kHz，音质与速度均衡；中文默认推荐。",
    },
    "high": {
        "label": "高音质",
        "model_key": "piper-high",
        "model_name": "Piper TTS high（高音质）",
        "default_voice": "en_US-lessac-high",
        "hint": "22.05kHz，音质最好、更慢，适合展示与录制。",
    },
}

_HF_REPO = "rhasspy/piper-voices"
_HF_BASES = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main",
    "https://hf-mirror.com/rhasspy/piper-voices/resolve/main",
)

_lock = threading.Lock()
_catalog_cache: dict[str, Any] | None = None
# onnx_path -> {"session": InferenceSession, "config": dict, "input_names": set[str]}
_session_cache: dict[str, dict[str, Any]] = {}
_espeak_phonemizer = None


def quality_of_model_key(model_key: str | None) -> str | None:
    key = (model_key or "").strip().lower()
    for q, meta in QUALITY_META.items():
        if key == meta["model_key"] or key.endswith(f"-{q}") or key.endswith(f"_{q}"):
            return q
    if key.startswith("piper-"):
        tail = key[6:]
        if tail in QUALITY_META:
            return tail
    return None


def default_voice_for_quality(quality: str) -> str:
    return QUALITY_META[quality]["default_voice"]


def _voices_json_path(folder: str | None = None) -> str | None:
    if folder:
        p = os.path.join(folder, "voices.json")
        if os.path.isfile(p):
            return p
    return None


def _download_bytes(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "TigerPro-Piper/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def ensure_voices_catalog(folder: str) -> dict[str, Any]:
    """下载/加载官方 voices.json 到模型目录（幂等）。"""
    global _catalog_cache
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "voices.json")
    if not os.path.isfile(path) or os.path.getsize(path) < 1024:
        last_err: Exception | None = None
        for base in _HF_BASES:
            try:
                raw = _download_bytes(f"{base}/voices.json")
                data = json.loads(raw.decode("utf-8"))
                with open(path, "wb") as f:
                    f.write(raw)
                _catalog_cache = data
                return data
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as e:
                last_err = e
        if last_err:
            raise RuntimeError(f"无法获取 Piper voices.json：{last_err}") from last_err
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _catalog_cache = data
    return data


def load_catalog(folder: str | None = None) -> dict[str, Any]:
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache
    path = _voices_json_path(folder)
    if path:
        with open(path, encoding="utf-8") as f:
            _catalog_cache = json.load(f)
            return _catalog_cache
    # 无本地目录时尝试缓存到临时常见位置失败则直拉
    if folder:
        return ensure_voices_catalog(folder)
    last_err: Exception | None = None
    for base in _HF_BASES:
        try:
            raw = _download_bytes(f"{base}/voices.json")
            _catalog_cache = json.loads(raw.decode("utf-8"))
            return _catalog_cache
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"无法加载 Piper 语音目录：{last_err}") from last_err


def catalog_stats(folder: str | None = None) -> dict[str, Any]:
    data = load_catalog(folder)
    langs = set()
    by_q: dict[str, int] = {q: 0 for q in QUALITIES}
    for item in data.values():
        q = item.get("quality")
        if q in by_q:
            by_q[q] += 1
        lang = item.get("language") or {}
        code = lang.get("code") or lang.get("family")
        if code:
            langs.add(code)
    return {
        "voices": len(data),
        "languages": len(langs),
        "byQuality": by_q,
    }


def list_voices(quality: str | None = None, folder: str | None = None) -> list[dict[str, Any]]:
    data = load_catalog(folder)
    rows = []
    for key, item in data.items():
        q = item.get("quality")
        if quality and q != quality:
            continue
        lang = item.get("language") or {}
        rows.append({
            "key": key,
            "name": item.get("name"),
            "quality": q,
            "numSpeakers": int(item.get("num_speakers") or 1),
            "languageCode": lang.get("code"),
            "languageFamily": lang.get("family"),
            "languageName": lang.get("name_english") or lang.get("name_native"),
            "country": lang.get("country_english"),
        })
    rows.sort(key=lambda r: (
        QUALITIES.index(r["quality"]) if r["quality"] in QUALITIES else 99,
        r.get("languageCode") or "",
        r.get("key") or "",
    ))
    return rows


def list_voice_keys(quality: str | None = None, folder: str | None = None) -> list[str]:
    return [r["key"] for r in list_voices(quality=quality, folder=folder)]


def _voice_rel_files(entry: dict[str, Any]) -> tuple[str, str]:
    files = entry.get("files") or {}
    onnx = next((k for k in files if k.endswith(".onnx") and not k.endswith(".onnx.json")), None)
    cfg = next((k for k in files if k.endswith(".onnx.json")), None)
    if not onnx or not cfg:
        raise ValueError("语音条目缺少 .onnx / .onnx.json")
    return onnx, cfg


def voice_local_paths(folder: str, voice_key: str) -> tuple[str, str]:
    onnx = os.path.join(folder, f"{voice_key}.onnx")
    cfg = os.path.join(folder, f"{voice_key}.onnx.json")
    return onnx, cfg


def ensure_voice(folder: str, voice_key: str, catalog: dict[str, Any] | None = None) -> tuple[str, str]:
    """确保某语音 onnx+json 已落到 folder，返回绝对路径。"""
    os.makedirs(folder, exist_ok=True)
    catalog = catalog or ensure_voices_catalog(folder)
    if voice_key not in catalog:
        raise ValueError(f"未知 Piper 语音：{voice_key}")
    onnx_path, cfg_path = voice_local_paths(folder, voice_key)
    if os.path.isfile(onnx_path) and os.path.isfile(cfg_path) and os.path.getsize(onnx_path) > 1024:
        return onnx_path, cfg_path
    onnx_rel, cfg_rel = _voice_rel_files(catalog[voice_key])
    last_err: Exception | None = None
    for base in _HF_BASES:
        try:
            for rel, dest in ((onnx_rel, onnx_path), (cfg_rel, cfg_path)):
                if os.path.isfile(dest) and os.path.getsize(dest) > 64:
                    continue
                raw = _download_bytes(f"{base}/{rel}", timeout=600)
                with open(dest, "wb") as f:
                    f.write(raw)
            if os.path.isfile(onnx_path) and os.path.isfile(cfg_path):
                return onnx_path, cfg_path
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"下载 Piper 语音失败 {voice_key}：{last_err}") from last_err


def download_quality_bundle(folder: str, quality: str) -> tuple[str, int]:
    """拉取该档默认语音 + voices.json，返回 (rel_hint_unused_local, total_size)。"""
    if quality not in QUALITY_META:
        raise ValueError(f"非法 Piper 档位：{quality}")
    catalog = ensure_voices_catalog(folder)
    voice_key = default_voice_for_quality(quality)
    ensure_voice(folder, voice_key, catalog=catalog)
    # 同档其余语音可按需懒加载；此处只保证默认可用
    size = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            fp = os.path.join(root, name)
            if os.path.isfile(fp):
                size += os.path.getsize(fp)
    return folder, size


def _load_voice_config(cfg_path: str) -> dict[str, Any]:
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)


def _get_ort_session(onnx_path: str, cfg_path: str) -> dict[str, Any]:
    """用 onnxruntime 直接加载本地 .onnx，按路径缓存。"""
    with _lock:
        cached = _session_cache.get(onnx_path)
        if cached is not None:
            return cached
        try:
            import onnxruntime as ort
        except ImportError as e:
            raise RuntimeError("Piper 推理需安装 onnxruntime") from e
        if not os.path.isfile(onnx_path):
            raise FileNotFoundError(f"缺少本地 ONNX 权重：{onnx_path}")
        sess = ort.InferenceSession(
            onnx_path,
            providers=["CPUExecutionProvider"],
        )
        config = _load_voice_config(cfg_path)
        entry = {
            "session": sess,
            "config": config,
            "input_names": {i.name for i in sess.get_inputs()},
        }
        _session_cache[onnx_path] = entry
        return entry


def _get_espeak_phonemizer():
    global _espeak_phonemizer
    if _espeak_phonemizer is not None:
        return _espeak_phonemizer
    try:
        from piper.voice import EspeakPhonemizer
    except ImportError as e:
        raise RuntimeError(
            "Piper 音素化需 piper-tts（含 espeak 桥）：pip install \"piper-tts[zh]==1.8.0\""
        ) from e
    _espeak_phonemizer = EspeakPhonemizer()
    return _espeak_phonemizer


def _phonemize_text(config: dict[str, Any], text: str) -> list[list[str]]:
    """文本 → 按句音素。官方 Piper 语音多为 espeak；TEXT 类型按码点。"""
    phoneme_type = (config.get("phoneme_type") or "espeak").lower()
    if phoneme_type in ("text", "codepoints"):
        import unicodedata

        return [list(unicodedata.normalize("NFD", text))]
    espeak = config.get("espeak") or {}
    voice = espeak.get("voice") or "en-us"
    return _get_espeak_phonemizer().phonemize(voice, text)


def _phonemes_to_ids(config: dict[str, Any], phonemes: list[str]) -> list[int]:
    """音素 → 模型输入 id（含 BOS/^ PAD/_ EOS/$）。"""
    id_map = config.get("phoneme_id_map") or {}
    bos = (id_map.get("^") or [1])[0]
    eos = (id_map.get("$") or [2])[0]
    pad = (id_map.get("_") or [0])[0]
    ids = [bos, pad]
    for ph in phonemes:
        mapped = id_map.get(ph)
        if not mapped:
            continue
        for pid in mapped:
            ids.append(int(pid))
            ids.append(pad)
    ids.append(eos)
    return ids


def _run_onnx(
    entry: dict[str, Any],
    phoneme_ids: list[int],
    *,
    speaker_id: int | None = None,
) -> Any:
    import numpy as np

    config = entry["config"]
    sess = entry["session"]
    names = entry["input_names"]
    infer = config.get("inference") or {}
    noise_scale = float(infer.get("noise_scale", 0.667))
    length_scale = float(infer.get("length_scale", 1.0))
    noise_w = float(infer.get("noise_w", infer.get("noise_w_scale", 0.8)))

    phoneme_ids_array = np.expand_dims(np.asarray(phoneme_ids, dtype=np.int64), 0)
    phoneme_ids_lengths = np.asarray([phoneme_ids_array.shape[1]], dtype=np.int64)
    scales = np.asarray([noise_scale, length_scale, noise_w], dtype=np.float32)
    feeds: dict[str, Any] = {
        "input": phoneme_ids_array,
        "input_lengths": phoneme_ids_lengths,
        "scales": scales,
    }
    num_speakers = int(config.get("num_speakers") or 1)
    if num_speakers > 1 and "sid" in names:
        sid = 0 if speaker_id is None else int(speaker_id)
        feeds["sid"] = np.asarray([sid], dtype=np.int64)
    # 仅喂模型实际存在的输入名
    feeds = {k: v for k, v in feeds.items() if k in names}
    outputs = sess.run(None, feeds)
    audio = np.asarray(outputs[0], dtype=np.float32).reshape(-1)
    return audio


def synthesize(
    folder: str,
    text: str,
    *,
    voice_key: str | None = None,
    quality: str | None = None,
    speaker_id: int | None = None,
) -> dict[str, Any]:
    """本地下载权重 + onnxruntime 直接推理，返回 WAV(base64)。"""
    import base64
    import wave

    import numpy as np

    text = (text or "").strip()
    if not text:
        raise ValueError("请输入待合成文本")
    catalog = ensure_voices_catalog(folder)
    q = quality
    if voice_key:
        entry = catalog.get(voice_key)
        if entry is None:
            raise ValueError(f"未知 Piper 语音：{voice_key}")
        q = entry.get("quality") or q
    if not q:
        q = "medium"
    if not voice_key:
        voice_key = default_voice_for_quality(q)
    onnx_path, cfg_path = ensure_voice(folder, voice_key, catalog=catalog)
    runtime = _get_ort_session(onnx_path, cfg_path)
    config = runtime["config"]

    chunks: list[Any] = []
    for phonemes in _phonemize_text(config, text):
        if not phonemes:
            continue
        ids = _phonemes_to_ids(config, phonemes)
        if len(ids) < 3:
            continue
        audio = _run_onnx(runtime, ids, speaker_id=speaker_id)
        if audio.size:
            chunks.append(audio)
    if not chunks:
        raise ValueError("合成结果为空")
    arr = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    max_val = float(np.max(np.abs(arr))) if arr.size else 0.0
    if max_val > 1e-8:
        arr = arr / max_val
    arr = np.clip(arr, -1.0, 1.0).astype(np.float32)
    audio_cfg = config.get("audio") or {}
    sr = int(audio_cfg.get("sample_rate") or 22050)
    pcm = (arr * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return {
        "audio": base64.b64encode(buf.getvalue()).decode(),
        "sampleRate": sr,
        "speaker": voice_key,
        "quality": q,
        "engine": "onnxruntime",
    }
