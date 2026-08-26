"""克隆 VLM-FO1 官方仓库到 uploads/models/third_party/VLM-FO1。

用法（在 backend 目录）:
  python scripts/setup_vlm_fo1.py
  pip install -r uploads/models/third_party/VLM-FO1/requirements.txt
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "uploads", "models", "third_party", "VLM-FO1")
REPO = "https://github.com/om-ai-lab/VLM-FO1.git"


def main() -> int:
    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    if os.path.isdir(os.path.join(DEST, "vlm_fo1")):
        print(f"already present: {DEST}")
        return 0
    if os.path.isdir(DEST) and not os.listdir(DEST):
        os.rmdir(DEST)
    print(f"cloning {REPO} -> {DEST}")
    r = subprocess.run(["git", "clone", "--depth", "1", REPO, DEST], check=False)
    if r.returncode != 0:
        print("git clone failed; set VLM_FO1_ROOT manually after clone", file=sys.stderr)
        return r.returncode
    req = os.path.join(DEST, "requirements.txt")
    print("next:")
    print(f"  pip install -r {req}")
    print("  # 然后在模型管理拉取 omlab/VLM-FO1-3B-v01 权重")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
