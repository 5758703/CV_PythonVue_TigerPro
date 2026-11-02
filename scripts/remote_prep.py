#!/usr/bin/env python3
"""Prepare Aliyun host: swap, free disk, stop heavy services before Docker build."""
import socket
import time
import paramiko

HOST = "8.217.205.108"
PASSWORD = "Tiger@2024Tiger@2024"
CMD = r"""
set -e
echo '=== /root top ==='
du -sh /root/* 2>/dev/null | sort -hr | head -20
echo '=== /usr top ==='
du -sh /usr/* 2>/dev/null | sort -hr | head -10

# 扩容 swap 到 8G
SWAPFILE=/swapfile_tiger
if [ ! -f "$SWAPFILE" ] || [ "$(stat -c%s "$SWAPFILE" 2>/dev/null || echo 0)" -lt $((8*1024*1024*1024)) ]; then
  echo 'Creating 8G swap...'
  swapoff /swapfile 2>/dev/null || true
  swapoff "$SWAPFILE" 2>/dev/null || true
  rm -f "$SWAPFILE"
  fallocate -l 8G "$SWAPFILE" || dd if=/dev/zero of="$SWAPFILE" bs=1M count=8192
  chmod 600 "$SWAPFILE"
  mkswap "$SWAPFILE"
  swapon "$SWAPFILE"
  grep -q "$SWAPFILE" /etc/fstab || echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab
fi
# 保留原 /swapfile 也可开着
swapon /swapfile 2>/dev/null || true
free -h
swapon --show

# 构建期暂停 ollama 省内存
systemctl stop ollama 2>/dev/null || true
pkill -f ollama 2>/dev/null || true
sleep 1
free -h

# 清理 apt / journal / docker 悬空
apt-get clean 2>/dev/null || yum clean all 2>/dev/null || true
journalctl --vacuum-size=200M 2>/dev/null || true
docker system prune -af 2>/dev/null || true
df -h /
"""


def main():
    for attempt in range(4):
        try:
            sock = socket.create_connection((HOST, 22), timeout=30)
            t = paramiko.Transport(sock)
            t.banner_timeout = 60
            t.start_client(timeout=30)
            t.auth_password("root", PASSWORD)
            chan = t.open_session()
            chan.settimeout(600)
            chan.exec_command(CMD)
            while True:
                if chan.recv_ready():
                    print(chan.recv(65536).decode("utf-8", "replace"), end="")
                if chan.recv_stderr_ready():
                    print(chan.recv_stderr(65536).decode("utf-8", "replace"), end="")
                if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                    break
                time.sleep(0.05)
            code = chan.recv_exit_status()
            print("exit", code)
            t.close()
            raise SystemExit(code)
        except SystemExit:
            raise
        except Exception as e:
            print(f"retry {attempt}: {type(e).__name__}: {e}")
            time.sleep(4)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
