#!/usr/bin/env python3
import socket
import time
import paramiko

HOST = "8.217.205.108"
PASSWORD = "Tiger@2024Tiger@2024"
CMD = r"""
set -e
echo '=== host ==='
nproc; free -h; df -h /; swapon --show || true
echo '=== docker ==='
docker --version
docker compose version || true
docker ps -a
docker images
du -sh /var/lib/docker 2>/dev/null || true
echo '=== listen ==='
ss -lntp 2>/dev/null | head -30 || netstat -lntp 2>/dev/null | head -30 || true
echo '=== disk hotspots ==='
du -sh /opt /root /var/lib/docker /usr 2>/dev/null | sort -hr | head
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
            chan.settimeout(180)
            chan.exec_command(CMD)
            out = b""
            err = b""
            while True:
                if chan.recv_ready():
                    out += chan.recv(65536)
                if chan.recv_stderr_ready():
                    err += chan.recv_stderr(65536)
                if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                    break
                time.sleep(0.05)
            print(out.decode("utf-8", "replace"))
            if err:
                print("STDERR:", err.decode("utf-8", "replace"))
            print("exit", chan.recv_exit_status())
            t.close()
            return
        except Exception as e:
            print(f"retry {attempt}: {type(e).__name__}: {e}")
            time.sleep(4)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
