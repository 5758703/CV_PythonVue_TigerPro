"""一键安装 Tencent YOLO-Master 推理依赖（MoE 检测等必需）。

用法（在 backend 目录）：
    python scripts/setup_yolo_master.py
"""
from __future__ import annotations

import os
import subprocess
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.join(_BACKEND, "uploads", "models", "third_party", "YOLO-Master")
_REPO_URL = "https://github.com/Tencent/YOLO-Master.git"


def main() -> int:
    os.chdir(_BACKEND)
    if not os.path.isdir(_REPO):
        os.makedirs(os.path.dirname(_REPO), exist_ok=True)
        print(f"Cloning {_REPO_URL} -> {_REPO}")
        subprocess.check_call(["git", "clone", "--depth", "1", _REPO_URL, _REPO])
    else:
        print(f"Repo exists: {_REPO}")

    print("Installing editable package (pip install -e .)...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", "."], cwd=_REPO)

    sys.path.insert(0, _REPO)
    import importlib

    importlib.import_module("ultralytics.nn.modules.moe")
    print("OK: ultralytics.nn.modules.moe available")
    print("请重启后端服务后再进行 YOLO-Master 在线测试。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
