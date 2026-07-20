"""训练取消：落盘标志与内存标志。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.training import (  # noqa: E402
    clear_cancel,
    is_cancelled,
    request_cancel,
    _cancel_flag_path,
)


def test_cancel_flag_file_roundtrip(tmp_path):
    jid = 99
    assert not is_cancelled(jid, tmp_path)
    request_cancel(jid, tmp_path)
    assert is_cancelled(jid, tmp_path)
    assert _cancel_flag_path(jid, tmp_path).is_file()
    # 模拟跨进程：仅清内存，磁盘标志仍在
    from services import training as T
    with T._cancel_lock:
        T._cancel_flags.pop(jid, None)
    assert is_cancelled(jid, tmp_path)
    clear_cancel(jid, tmp_path)
    assert not is_cancelled(jid, tmp_path)
    assert not _cancel_flag_path(jid, tmp_path).is_file()
