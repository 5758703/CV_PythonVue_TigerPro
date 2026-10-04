"""Clients for official services and local CPU-only llama.cpp services.

T3PO_URL points to the official FastAPI application, not vLLM's /v1 endpoint.
No model weights or upstream Python packages are loaded into the Flask process.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
import uuid
import wave

from flask import current_app
import requests

REMOTE_LIBRARIES = frozenset(('confucius-r2t2', 'confucius-t3po'))


def service_configuration(library: str) -> tuple[str, str | None]:
    """Read-only prerequisite check; does not claim upstream health."""
    backend = inference_backend(library)
    prefix = 'CONFUCIUS_R2T2' if library == 'confucius-r2t2' else 'CONFUCIUS_T3PO'
    if backend not in ('official', 'llama-cpu'):
        return '', f'{prefix}_BACKEND must be official or llama-cpu'
    key = ('CONFUCIUS_R2T2_WS_URL' if library == 'confucius-r2t2'
           else 'CONFUCIUS_T3PO_URL')
    if backend == 'llama-cpu':
        key = prefix + '_CPU_URL'
    url = str(current_app.config.get(key) or '').strip().rstrip('/')
    schemes = ('ws', 'wss') if library == 'confucius-r2t2' and backend == 'official' else ('http', 'https')
    try:
        parsed = urlsplit(url)
        parsed.port  # Validate malformed ports without connecting.
    except ValueError:
        return '', f'{key} must be configured with a valid service URL'
    if not url or parsed.scheme not in schemes or not parsed.hostname or parsed.username or parsed.password:
        return '', f'{key} must be configured with a valid service URL'
    if parsed.query or parsed.fragment:
        return '', f'{key} must not contain a query or fragment'
    if backend == 'llama-cpu':
        import ipaddress
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname.lower() == 'localhost'
        if not loopback:
            return '', f'{key} must use a local loopback address for offline CPU inference'
    if library == 'confucius-r2t2' and backend == 'official' and not current_app.config.get('CONFUCIUS_R2T2_SECRET_KEY'):
        return '', 'CONFUCIUS_R2T2_SECRET_KEY is required'
    return url, None


def inference_backend(library: str) -> str:
    prefix = 'CONFUCIUS_R2T2' if library == 'confucius-r2t2' else 'CONFUCIUS_T3PO'
    return str(current_app.config.get(prefix + '_BACKEND') or 'official').strip().lower()


def _configured_url(library: str) -> str:
    url, reason = service_configuration(library)
    if reason:
        raise ValueError(reason)
    return url


def translate(text: str, *, direction='zh2en', latency_mode='native') -> dict:
    """Feed and flush one isolated translation session; preserve event boundaries."""
    if direction not in ('zh2en', 'en2zh'):
        raise ValueError('direction must be zh2en or en2zh')
    if latency_mode not in ('low', 'native', 'high'):
        raise ValueError('latencyMode must be low, native or high')
    if not isinstance(text, str) or not text.strip() or len(text) > 20000:
        raise ValueError('text must contain 1 to 20000 characters')
    url = _configured_url('confucius-t3po')
    if inference_backend('confucius-t3po') == 'llama-cpu':
        from services.confucius_cpu import translate_cpu
        return translate_cpu(url, text, direction, latency_mode)
    timeout = float(current_app.config.get('CONFUCIUS_TIMEOUT_SECONDS', 120))
    headers = {}
    api_key = current_app.config.get('CONFUCIUS_T3PO_API_KEY')
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    try:
        response = requests.post(url + '/api/v1/translate', json={
            'text': text, 'direction': direction, 'latency_mode': latency_mode, 'end': True,
        }, headers=headers, timeout=(10, timeout), allow_redirects=False)
        response.raise_for_status()
        data = response.json()
        events = data['events']
        if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
            raise ValueError('invalid events')
        increments = [event['text'] for event in events if event.get('type') == 'translation']
        if any(not isinstance(text, str) for text in increments):
            raise ValueError('invalid translation')
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        raise RuntimeError('T3PO 服务调用失败，请检查官方服务地址、状态和响应协议') from exc
    return {'text': ''.join(increments), 'events': events, 'direction': direction,
            'latencyMode': latency_mode}


def parse_asr_message(raw: str) -> dict | None:
    try:
        data = json.loads(raw)
        if data.get('status') == 'connected':
            return None
        if data.get('status') != 'success' or not isinstance(data.get('msg'), dict):
            raise ValueError('unsuccessful response')
        msg = data['msg']
        if not isinstance(msg.get('text', ''), str):
            raise ValueError('invalid text')
        return {'text': msg.get('text', ''), 'reset': msg.get('reset') is True}
    except (ValueError, TypeError, AttributeError) as exc:
        raise RuntimeError('R2T2 服务返回错误或不兼容的响应') from exc


async def _transcribe_pcm(url, secret, pcm, language, timeout):
    from websockets import connect
    from websockets.exceptions import ConnectionClosedOK

    events = []
    sent_eos = False
    async with connect(url, open_timeout=10, close_timeout=5, ping_interval=None) as socket:
        await socket.send(json.dumps({
            'channels': 1, 'sample_rate': 16000, 'requestId': str(uuid.uuid4()),
            'language': language, 'use_vad': False, 'secret_key': secret, 'mode': 'slow',
        }))
        handshake = json.loads(await asyncio.wait_for(socket.recv(), timeout))
        if not isinstance(handshake, dict) or handshake.get('status') != 'connected':
            raise RuntimeError('R2T2 服务拒绝连接，请检查密钥和服务状态')

        async def send():
            nonlocal sent_eos
            for start in range(0, len(pcm), 5120):  # 160 ms, PCM16LE
                await socket.send(pcm[start:start + 5120])
                await asyncio.sleep(0)
            await socket.send('YOUDAO_ONETIME_ASR_STREAM_EOS')
            sent_eos = True

        async def receive():
            while True:
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout)
                except ConnectionClosedOK:
                    if not sent_eos or not events or not events[-1]['reset']:
                        raise RuntimeError('R2T2 连接提前结束，未收到完整转写结果')
                    return
                event = parse_asr_message(raw)
                if event is not None:
                    events.append(event)

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    return events


def transcribe(audio_path: str, *, language='auto') -> dict:
    url = _configured_url('confucius-r2t2')
    languages = {'auto': 'zhen', 'zh': 'Chinese', 'en': 'English',
                 'Chinese': 'Chinese', 'English': 'English', 'zhen': 'zhen'}
    if language not in languages:
        raise ValueError('language must be auto, zh, en, Chinese, English or zhen')
    language = languages[language]
    from services.moss_mtd import extract_audio_wav
    with tempfile.TemporaryDirectory(prefix='confucius-') as folder:
        wav_path = str(Path(folder) / 'audio.wav')
        extract_audio_wav(audio_path, wav_path, sampling_rate=16000)
        with wave.open(wav_path, 'rb') as audio:
            pcm = audio.readframes(audio.getnframes())
        if not pcm:
            raise ValueError('audio is empty')
        if inference_backend('confucius-r2t2') == 'llama-cpu':
            from services.confucius_cpu import transcribe_cpu
            return transcribe_cpu(url, Path(wav_path).read_bytes(), language)
    from websockets.exceptions import WebSocketException
    try:
        events = asyncio.run(_transcribe_pcm(
            url, current_app.config['CONFUCIUS_R2T2_SECRET_KEY'], pcm, language,
            float(current_app.config.get('CONFUCIUS_TIMEOUT_SECONDS', 120)),
        ))
    except (OSError, TimeoutError, ValueError, WebSocketException) as exc:
        raise RuntimeError('R2T2 服务连接失败或超时，请检查服务地址和状态') from exc
    return {'text': ''.join(event['text'] for event in events), 'language': language,
            'emotion': None, 'events': [], 'increments': events}
