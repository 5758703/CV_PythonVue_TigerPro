"""One-shot adapters for CPU llama-server, without importing GPU runtimes.

Protocol references:
netease-youdao/Confucius4-R2T2/r2t2_llama/llama_native_backend.py
netease-youdao/Confucius4-T3PO/inference/prompts.py
CPU requests return one final event, not simulated streaming increments.
"""
import base64
import re

from flask import current_app
import requests


def _complete(url, prefix, messages, **extra):
    # Accept both the server root and its /v1 base URL.
    endpoint = url if url.endswith('/v1') else url + '/v1'
    headers = {}
    key = current_app.config.get(prefix + '_CPU_API_KEY')
    if key:
        headers['Authorization'] = f'Bearer {key}'
    try:
        # Ignore system HTTP proxies so localhost inference never leaves this PC.
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(endpoint + '/chat/completions', json={
                'model': current_app.config.get(prefix + '_CPU_MODEL') or
                         ('Confucius4-R2T2' if prefix.endswith('R2T2') else 'Confucius4-T3PO'),
                'messages': messages, 'temperature': 0, 'stream': False,
                'max_tokens': int(current_app.config.get(prefix + '_CPU_MAX_TOKENS', 4096)),
                **extra,
            }, headers=headers, timeout=(10, float(current_app.config.get('CONFUCIUS_CPU_TIMEOUT_SECONDS', 900))),
                allow_redirects=False)
        response.raise_for_status()
        choice = response.json()['choices'][0]
        if choice.get('finish_reason') != 'stop':
            raise ValueError('generation did not finish; increase context/max_tokens or shorten input')
        text = choice['message']['content']
        if not isinstance(text, str):
            raise ValueError('invalid completion content')
        return text.strip()
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        raise RuntimeError('Confucius CPU 推理失败，请检查 llama-server 状态、上下文长度和输出限制') from exc


def translate_cpu(url, text, direction, latency_mode):
    if latency_mode != 'native':
        raise ValueError('CPU 整段翻译仅支持 latencyMode=native；low/high 需要官方流式服务')
    languages = 'Chinese-to-English' if direction == 'zh2en' else 'English-to-Chinese'
    # Keep the model's interleaved-history interface; this endpoint supplies a
    # complete input, so explicitly ask for a final translation rather than WAIT.
    prompt = (
        f'You are a professional {languages} simultaneous interpreter. '
        'Ignore ASR fillers, stutters and repetitions. Output the translation directly '
        'without explanations or extra markers. The history format is '
        'source_text¦translated_text§source_text¦translated_text§.\n\n'
        f'<STREAMING_HISTORY>\n\n\n<CURRENT_INPUT>\n{text}\n\n'
        'The input is complete. Translate all of the current input now; do not wait for more input.'
    )
    output = _complete(url, 'CONFUCIUS_T3PO', [
        {'role': 'system', 'content': 'You are a helpful assistant.'},
        {'role': 'user', 'content': prompt},
    ])
    output = output.replace('<|im_end|>', '').strip()
    if not output or re.fullmatch(r'<?\s*(WAIT|TRANS)\s*>?', output, re.IGNORECASE):
        raise RuntimeError('T3PO CPU 返回 WAIT 或空译文，未完成翻译')
    output = re.sub(r'^(?:<\s*TRANS\s*>\s*|TRANS(?:\s*[:：]\s*|\s+))', '', output,
                    flags=re.IGNORECASE).strip()
    if not output:
        raise RuntimeError('T3PO CPU 返回空译文，未完成翻译')
    return {'text': output, 'events': [{'type': 'translation', 'text': output}],
            'direction': direction, 'latencyMode': 'native', 'backend': 'llama-cpu'}


def transcribe_cpu(url, wav_bytes, language):
    # Canonical Qwen3-ASR audio prompt. The assistant prefix constrains language
    # without adding a text instruction to the audio user message.
    template = (
        "{% for m in messages %}{{ '<|im_start|>' + m.role + '\\n' }}"
        "{% if m.content is string %}{{ m.content }}"
        "{% else %}{% for c in m.content %}"
        "{% if c.type == 'text' %}{{ c.text }}"
        "{% elif c.type == 'input_audio' %}<|audio_start|><|audio_pad|><|audio_end|>"
        "{% endif %}{% endfor %}{% endif %}"
        "{% if m.role != 'assistant' %}<|im_end|>\n{% endif %}{% endfor %}"
        "{% if add_generation_prompt and messages[-1].role != 'assistant' %}"
        "{{ '<|im_start|>assistant\\n' }}{% endif %}"
    )
    messages = [{'role': 'system', 'content': ''}, {'role': 'user', 'content': [{
        'type': 'input_audio',
        'input_audio': {'data': base64.b64encode(wav_bytes).decode('ascii'), 'format': 'wav'},
    }]}]
    if language != 'zhen':
        messages.append({'role': 'assistant', 'content': f'language {language}<asr_text>'})
    output = _complete(url, 'CONFUCIUS_R2T2', messages, chat_template=template)
    detected = re.match(r'^language\s+(.*?)<asr_text>', output)
    if detected:
        language = detected.group(1).strip() or language
        output = output[detected.end():]
    output = output.replace('<|im_end|>', '').strip()
    if not output:
        raise RuntimeError('R2T2 CPU 返回空转写')
    return {'text': output, 'language': language, 'emotion': None, 'events': [],
            'increments': [{'text': output, 'reset': True}], 'backend': 'llama-cpu'}
