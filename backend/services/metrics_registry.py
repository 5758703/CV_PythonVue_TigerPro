"""简易进程内指标（Prometheus text 导出）。"""
from __future__ import annotations

import threading
import time
from collections import defaultdict

_lock = threading.Lock()
_counters: dict[str, float] = defaultdict(float)
_started = time.time()


def incr(name: str, value: float = 1.0, **labels):
    key = name
    if labels:
        parts = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        key = f"{name}{{{parts}}}"
    with _lock:
        _counters[key] += value


def observe_latency(name: str, ms: float, **labels):
    incr(name + "_count", 1, **labels)
    incr(name + "_sum_ms", ms, **labels)


def render_prometheus() -> str:
    lines = [
        "# HELP tigerpro_up TigerPro process up",
        "# TYPE tigerpro_up gauge",
        "tigerpro_up 1",
        "# HELP tigerpro_uptime_seconds Process uptime",
        "# TYPE tigerpro_uptime_seconds gauge",
        f"tigerpro_uptime_seconds {time.time() - _started:.1f}",
    ]
    with _lock:
        items = sorted(_counters.items())
    for k, v in items:
        # k may already include labels
        if "{" in k:
            metric, rest = k.split("{", 1)
            lines.append(f"{metric}{{{rest} {v}")
        else:
            lines.append(f"{k} {v}")
    return "\n".join(lines) + "\n"


def snapshot() -> dict:
    with _lock:
        return {"uptimeSec": round(time.time() - _started, 1), "counters": dict(_counters)}
