"""DeepSeek 客户端（OpenAI 兼容 chat/completions）。

仅供检测结果 AI 报告使用。强制 JSON 输出。失败抛 DeepSeekError，
由上层 report.py 捕获并降级。
"""
import json

import requests

from config import Config


class DeepSeekError(Exception):
    pass


def chat_json(system_prompt, user_prompt, timeout=60):
    """调 DeepSeek 返回解析后的 JSON dict。失败抛 DeepSeekError。"""
    url = f"{Config.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {Config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": Config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        "stream": False,
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except (requests.exceptions.RequestException, KeyError, IndexError,
            ValueError) as e:
        raise DeepSeekError(str(e)) from e
