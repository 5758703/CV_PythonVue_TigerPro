"""MOSS-Transcribe-Diarize 本地推理辅助（不依赖 GitHub 官方包）。

官方辅助包未上 PyPI，且国内环境常无法 `pip install git+https://github.com/...`。
这里复现其 inference_utils 中转写所需的最小路径：构造消息、加载音频、generate。
"""
from __future__ import annotations

import copy
import subprocess
from pathlib import Path
from typing import Any, Callable

import numpy as np
import torch

DEFAULT_PROMPT = (
    "请将音频转写为文本，每一段需以起始时间戳和说话人编号"
    "（[S01]、[S02]、[S03]…）开头，正文为对应的语音内容，"
    "并在段末标注结束时间戳，以清晰标明该段语音范围。"
)


def resolve_device(device: str) -> torch.device:
    if device == "auto":
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    resolved = torch.device(device)
    if resolved.type == "cuda" and not torch.cuda.is_available():
        return torch.device("cpu")
    return resolved


def extract_audio_wav(media_path: str, out_wav: str, sampling_rate: int = 16000) -> str:
    """用 ffmpeg 从音/视频抽出单声道 WAV（供 ASR 统一入口）。"""
    import imageio_ffmpeg

    sr = int(sampling_rate or 16000)
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        exe, "-y", "-nostdin", "-threads", "1", "-i", str(media_path),
        "-vn", "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le",
        "-hide_banner", "-loglevel", "error", str(out_wav),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0 or not Path(out_wav).is_file() or Path(out_wav).stat().st_size <= 0:
        err = proc.stderr.decode("utf-8", "ignore")[:300]
        raise RuntimeError(f"视频抽音失败（请确认文件含音轨）：{err or 'unknown'}")
    return out_wav


def load_audio_waveform(audio: str | np.ndarray, sampling_rate: int) -> np.ndarray:
    if isinstance(audio, np.ndarray):
        wave = np.asarray(audio, dtype=np.float32)
        if wave.ndim > 1:
            wave = np.mean(wave, axis=-1)
        return wave
    import imageio_ffmpeg

    sr = int(sampling_rate or 16000)
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        exe, "-nostdin", "-threads", "1", "-i", str(audio),
        "-ac", "1", "-ar", str(sr), "-f", "f32le", "-hide_banner",
        "-loglevel", "error", "pipe:1",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"音频解码失败：{proc.stderr.decode('utf-8', 'ignore')[:200]}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def process_audio_info(messages: list[dict[str, Any]], sampling_rate: int) -> list[np.ndarray]:
    audios = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            continue
        for item in content or []:
            if item.get("type") != "audio":
                continue
            audio = item.get("audio") or item.get("audio_url") or item.get("url") or item.get("path")
            if audio is None:
                raise ValueError("Audio content must include audio, audio_url, url, or path.")
            audios.append(load_audio_waveform(audio, sampling_rate=sampling_rate))
    return audios


def build_transcription_messages(audio_path: str | Path, prompt: str = DEFAULT_PROMPT) -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "audio", "audio": str(audio_path)},
                {"type": "text", "text": prompt.strip() or DEFAULT_PROMPT},
            ],
        }
    ]


def prepare_inputs(processor, messages, *, max_length: int = 131072, device: torch.device | None = None):
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    sr = int(getattr(processor.feature_extractor, "sampling_rate", 16000) or 16000)
    audios = process_audio_info(messages, sampling_rate=sr)
    audio_kwargs = {"device": str(device)} if device is not None and device.type == "cuda" else {}
    return processor(
        text=text,
        audio=audios,
        max_length=max_length,
        audio_kwargs=audio_kwargs,
        return_tensors="pt",
    )


def generate_transcription(
    model,
    processor,
    messages,
    *,
    max_length: int = 131072,
    max_new_tokens: int | None = None,
    do_sample: bool = False,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    device: torch.device | None = None,
    dtype: torch.dtype | None = None,
    input_callback: Callable[[int], None] | None = None,
    token_callback: Callable[[int], None] | None = None,
    attention_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del token_callback, attention_report  # 本地路径不依赖官方 attention/streamer
    device = device or next(model.parameters()).device
    dtype = dtype or next(model.parameters()).dtype
    context = (
        torch.amp.autocast("cuda", dtype=dtype)
        if device.type == "cuda" and dtype in (torch.float16, torch.bfloat16)
        else torch.no_grad()
    )
    with context:
        inputs = prepare_inputs(processor, messages, max_length=max_length, device=device).to(device)

    prompt_len = int(inputs["attention_mask"][0].sum().item())
    if input_callback is not None:
        input_callback(prompt_len)
    generation_config = copy.deepcopy(model.generation_config)
    if max_new_tokens is not None:
        generation_config.max_new_tokens = max_new_tokens
    generation_config.do_sample = do_sample
    if do_sample and temperature is not None:
        generation_config.temperature = temperature
    if do_sample and top_p is not None:
        generation_config.top_p = top_p
    if do_sample and top_k is not None:
        generation_config.top_k = top_k
    generate_kwargs = {
        "input_ids": inputs["input_ids"],
        "attention_mask": inputs["attention_mask"],
        "input_features": inputs["input_features"],
        "audio_feature_lengths": inputs["audio_feature_lengths"],
        "audio_chunk_mapping": inputs["audio_chunk_mapping"],
        "generation_config": generation_config,
    }
    with torch.inference_mode(), (
        torch.amp.autocast("cuda", dtype=dtype)
        if device.type == "cuda" and dtype in (torch.float16, torch.bfloat16)
        else torch.no_grad()
    ):
        outputs = model.generate(**generate_kwargs)

    generated_ids = outputs[0][prompt_len:]
    text = processor.tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
    return {
        "text": text,
        "prompt_len": prompt_len,
        "generated_tokens": int(generated_ids.numel()),
    }
