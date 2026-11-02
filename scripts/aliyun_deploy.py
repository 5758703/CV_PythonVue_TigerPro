#!/usr/bin/env python3
"""Deploy Tiger AI to Aliyun via SSH/SFTP (paramiko)."""
from __future__ import annotations

import os
import sys
import time
import tarfile
import tempfile
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get("DEPLOY_HOST", "8.217.205.108")
USER = os.environ.get("DEPLOY_USER", "root")
PASSWORD = os.environ.get("DEPLOY_PASSWORD", "Tiger@2024Tiger@2024")
REMOTE_DIR = os.environ.get("DEPLOY_REMOTE_DIR", "/opt/CV_PythonVue_TigerPro")

EXCLUDE_DIR_NAMES = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".idea",
    ".vscode",
    ".cache",
    ".claude",
    ".history",
    ".superpowers",
    ".playwright-mcp",
    "agent-transcripts",
}
EXCLUDE_PATH_PREFIXES = (
    "backend/uploads/",
    "backend/weights/",
    "backend/.tmp_",
    "backend/yolo_dataset/",
    "backend/tmp_plate_debug_out/",
    "docs/assets/demos/",
)


def should_exclude(rel: str) -> bool:
    parts = Path(rel).parts
    if any(p in EXCLUDE_DIR_NAMES for p in parts):
        return True
    norm = rel.replace("\\", "/")
    return any(norm.startswith(p) for p in EXCLUDE_PATH_PREFIXES)


def connect() -> paramiko.SSHClient:
    sock = __import__("socket").create_connection((HOST, 22), timeout=30)
    transport = paramiko.Transport(sock)
    transport.banner_timeout = 60
    transport.start_client(timeout=30)
    transport.auth_password(USER, PASSWORD)
    client = paramiko.SSHClient()
    client._transport = transport  # noqa: SLF001
    return client


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 600, check: bool = True) -> tuple[int, str, str]:
    print(f"\n$ {cmd}")
    chan = client.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    out_chunks: list[str] = []
    err_chunks: list[str] = []
    while True:
        if chan.recv_ready():
            data = chan.recv(65536).decode("utf-8", "replace")
            out_chunks.append(data)
            sys.stdout.write(data)
            sys.stdout.flush()
        if chan.recv_stderr_ready():
            data = chan.recv_stderr(65536).decode("utf-8", "replace")
            err_chunks.append(data)
            sys.stderr.write(data)
            sys.stderr.flush()
        if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
            break
        time.sleep(0.05)
    code = chan.recv_exit_status()
    out = "".join(out_chunks)
    err = "".join(err_chunks)
    if check and code != 0:
        raise RuntimeError(f"command failed ({code}): {cmd}\n{err or out}")
    return code, out, err


def make_archive() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="tiger-deploy-"))
    archive = tmp / "tigerpro.tar.gz"
    print(f"Creating archive {archive} ...")
    count = 0
    with tarfile.open(archive, "w:gz") as tar:
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            if should_exclude(rel):
                continue
            # skip huge media / binaries in docs
            if path.suffix.lower() in {".mp4", ".gif", ".pt", ".onnx", ".gguf", ".whl"} and not rel.startswith("deploy/"):
                if path.stat().st_size > 2_000_000:
                    continue
            tar.add(path, arcname=f"CV_PythonVue_TigerPro/{rel}")
            count += 1
            if count % 500 == 0:
                print(f"  packed {count} files...")
    print(f"Archive ready: {archive} ({archive.stat().st_size / 1e6:.1f} MB, {count} files)")
    return archive


def sftp_put(client: paramiko.SSHClient, local: Path, remote: str) -> None:
    sftp = paramiko.SFTPClient.from_transport(client.get_transport())
    print(f"Uploading {local} -> {remote}")
    # ensure parent
    run(client, f"mkdir -p $(dirname {remote})", check=True)
    size = local.stat().st_size
    sent = {"n": 0}

    def cb(transferred, total):
        if transferred - sent["n"] > 5_000_000 or transferred == total:
            sent["n"] = transferred
            print(f"  upload {transferred / 1e6:.1f}/{total / 1e6:.1f} MB")

    sftp.put(str(local), remote, callback=cb)
    sftp.close()
    print(f"Upload done ({size / 1e6:.1f} MB)")


def main() -> int:
    print(f"Connecting to {USER}@{HOST} ...")
    client = connect()
    print("SSH authenticated")

    run(client, "uname -a; cat /etc/os-release | head -6; nproc; free -h; df -h /")

    # Install Docker if missing
    code, out, _ = run(client, "command -v docker && docker --version || echo NO_DOCKER", check=False)
    if "NO_DOCKER" in out or code != 0:
        print("Installing Docker...")
        run(
            client,
            "curl -fsSL https://get.docker.com | sh && systemctl enable --now docker",
            timeout=900,
        )
    run(client, "docker --version; docker compose version")

    # 小内存机器：确保有足够 swap，避免构建/拉 torch 时 OOM
    run(
        client,
        r"""
set -e
SWAPFILE=/swapfile_tiger
NEED_GB=8
if [ "$(swapon --show --noheadings | wc -l)" -eq 0 ] || [ "$(awk '/SwapTotal/{print int($2/1024/1024)}' /proc/meminfo)" -lt 6 ]; then
  echo "Configuring ${NEED_GB}G swap..."
  swapoff "$SWAPFILE" 2>/dev/null || true
  rm -f "$SWAPFILE"
  fallocate -l ${NEED_GB}G "$SWAPFILE" || dd if=/dev/zero of="$SWAPFILE" bs=1M count=$((NEED_GB*1024))
  chmod 600 "$SWAPFILE"
  mkswap "$SWAPFILE"
  swapon "$SWAPFILE"
  grep -q "$SWAPFILE" /etc/fstab || echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab
fi
free -h
swapon --show
# 停掉占用 80 端口的旧服务（若有）
if ss -lntp 2>/dev/null | grep -q ':80 '; then
  systemctl stop nginx 2>/dev/null || true
  systemctl stop httpd 2>/dev/null || true
  docker ps --format '{{.ID}} {{.Ports}}' | awk '/0.0.0.0:80|->/ {print $1}' | xargs -r docker stop || true
fi
# 清理悬空镜像腾磁盘
docker system prune -f || true
df -h /
""",
        timeout=600,
    )

    archive = make_archive()
    remote_tar = "/tmp/tigerpro.tar.gz"
    sftp_put(client, archive, remote_tar)

    run(
        client,
        f"rm -rf {REMOTE_DIR} && mkdir -p /opt && tar -xzf {remote_tar} -C /opt "
        f"&& ls -la {REMOTE_DIR} | head -30 && test -f {REMOTE_DIR}/deploy/docker-compose.yml",
        timeout=300,
    )

    # Ensure .env exists (uploaded in archive)
    run(client, f"test -f {REMOTE_DIR}/deploy/.env && echo env_ok")

    # Free disk / pull base images first
    run(client, "docker system df || true", check=False)

    print("\n=== Building and starting stack (this can take a long time) ===")
    run(
        client,
        f"cd {REMOTE_DIR} && docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build",
        timeout=7200,
    )

    run(
        client,
        f"cd {REMOTE_DIR} && docker compose -f deploy/docker-compose.yml --env-file deploy/.env ps",
        timeout=120,
    )

    # Wait for health
    for i in range(36):
        code, out, _ = run(
            client,
            "curl -fsS http://127.0.0.1/api/health || true",
            timeout=30,
            check=False,
        )
        if '"code": 0' in out or '"code":0' in out or "code" in out and "0" in out:
            print("Health check OK")
            break
        print(f"Waiting for backend... ({i+1})")
        time.sleep(10)
    else:
        run(
            client,
            f"cd {REMOTE_DIR} && docker compose -f deploy/docker-compose.yml --env-file deploy/.env logs --tail=80 backend",
            check=False,
        )

    run(client, "curl -sI http://127.0.0.1/ | head -5; curl -sI http://127.0.0.1/console/ | head -5", check=False)
    print("\nDeploy finished.")
    print(f"Portal:  http://{HOST}/")
    print(f"Admin:   http://{HOST}/console/")
    print(f"API:     http://{HOST}/api/health")
    client.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("DEPLOY_FAILED:", exc, file=sys.stderr)
        raise
