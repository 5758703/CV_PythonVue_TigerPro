"""Windows 桌面屏幕 → RTSP 推流（ffmpeg gdigrab + MediaMTX 等）。

由后端在本机拉起 ffmpeg 子进程，将桌面画面推送到 RTSP 服务；
管理台通过「网络摄像头（RTSP）」拉流预览。
"""
from __future__ import annotations

import logging
import platform
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

_state_lock = threading.Lock()
_push_proc: subprocess.Popen | None = None
_push_meta: dict[str, Any] = {}
_stderr_bucket: list[bytes] = []


def is_windows() -> bool:
    return platform.system().lower() == "windows"


def _sanitize_stream_name(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]", "", (name or "").strip())
    return s or "desktop"


def _get_ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def build_screen_push_cmd(
    *,
    rtsp_url: str,
    fps: int = 15,
    width: int | None = 640,
    capture: str = "desktop",
    offset_x: int = 0,
    offset_y: int = 0,
    video_size: str | None = None,
    draw_mouse: bool = True,
    ffmpeg_exe: str | None = None,
) -> list[str]:
    """构造 Windows gdigrab → libx264 → RTSP 推流命令。"""
    if not is_windows():
        raise RuntimeError("屏幕 RTSP 推流仅支持 Windows 本机")
    exe = ffmpeg_exe or _get_ffmpeg_exe()
    f = max(1, min(int(fps or 15), 30))
    grab = ["-f", "gdigrab", "-framerate", str(f)]
    if capture == "region" and video_size:
        grab.extend([
            "-offset_x", str(max(0, int(offset_x))),
            "-offset_y", str(max(0, int(offset_y))),
            "-video_size", video_size,
        ])
    grab.extend(["-draw_mouse", "1" if draw_mouse else "0", "-i", "desktop"])

    vf_parts: list[str] = []
    if width and int(width) > 0:
        w = max(160, min(int(width), 1920))
        vf_parts.append(f"scale={w}:-2:flags=fast_bilinear")
    vf = ",".join(vf_parts) if vf_parts else None

    cmd = [
        exe, "-hide_banner", "-loglevel", "warning",
        *grab,
        "-an",
    ]
    if vf:
        cmd.extend(["-vf", vf])
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-g", str(f * 2),
        "-f", "rtsp",
        rtsp_url,
    ])
    return cmd


def build_rtsp_url(host: str, port: int, stream_name: str) -> str:
    h = (host or "localhost").strip() or "localhost"
    p = max(1, min(int(port or 8554), 65535))
    name = _sanitize_stream_name(stream_name)
    return f"rtsp://{h}:{p}/{name}"


def _drain_stderr(proc: subprocess.Popen, bucket: list[bytes]) -> None:
    try:
        if proc.stderr:
            bucket.append(proc.stderr.read())
    except Exception:  # noqa: BLE001
        pass


def _kill_proc_tree(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    pid = proc.pid
    if is_windows():
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=8,
            )
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
    else:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    try:
        proc.wait(timeout=3)
    except Exception:  # noqa: BLE001
        pass


def _proc_alive(proc: subprocess.Popen | None) -> bool:
    return proc is not None and proc.poll() is None


@dataclass
class ScreenPushStatus:
    supported: bool
    running: bool
    platform: str
    rtsp_url: str | None = None
    stream_name: str | None = None
    fps: int | None = None
    width: int | None = None
    pid: int | None = None
    started_at: float | None = None
    last_error: str | None = None
    command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "supported": self.supported,
            "running": self.running,
            "platform": self.platform,
            "rtspUrl": self.rtsp_url,
            "streamName": self.stream_name,
            "fps": self.fps,
            "width": self.width,
            "pid": self.pid,
            "startedAt": self.started_at,
            "lastError": self.last_error,
            "command": self.command,
        }


def get_status() -> ScreenPushStatus:
    global _push_proc, _push_meta, _stderr_bucket
    with _state_lock:
        alive = _proc_alive(_push_proc)
        if _push_proc and not alive:
            err = b"".join(_stderr_bucket).decode("utf-8", errors="ignore").strip()
            if err:
                _push_meta["last_error"] = err[-500:]
            _push_proc = None
        return ScreenPushStatus(
            supported=is_windows(),
            running=alive,
            platform=platform.system(),
            rtsp_url=_push_meta.get("rtsp_url"),
            stream_name=_push_meta.get("stream_name"),
            fps=_push_meta.get("fps"),
            width=_push_meta.get("width"),
            pid=_push_proc.pid if alive and _push_proc else None,
            started_at=_push_meta.get("started_at"),
            last_error=_push_meta.get("last_error"),
            command=_push_meta.get("command"),
        )


def preview_command(
    *,
    rtsp_host: str = "localhost",
    rtsp_port: int = 8554,
    stream_name: str = "desktop",
    fps: int = 15,
    width: int = 640,
    capture: str = "desktop",
) -> dict[str, Any]:
    """返回可复制的手动 ffmpeg 命令（不启动进程）。"""
    if not is_windows():
        return {
            "supported": False,
            "platform": platform.system(),
            "message": "屏幕 RTSP 推流仅支持 Windows",
        }
    rtsp_url = build_rtsp_url(rtsp_host, rtsp_port, stream_name)
    cmd = build_screen_push_cmd(
        rtsp_url=rtsp_url,
        fps=fps,
        width=width,
        capture=capture,
    )
    return {
        "supported": True,
        "platform": platform.system(),
        "rtspUrl": rtsp_url,
        "streamName": _sanitize_stream_name(stream_name),
        "command": " ".join(f'"{p}"' if " " in p else p for p in cmd),
        "commandArgs": cmd,
        "mediamtxHint": "推流前请先启动 MediaMTX（默认 RTSP 端口 8554）",
    }


def start_push(
    *,
    rtsp_host: str = "localhost",
    rtsp_port: int = 8554,
    stream_name: str = "desktop",
    fps: int = 15,
    width: int = 640,
    capture: str = "desktop",
    offset_x: int = 0,
    offset_y: int = 0,
    video_size: str | None = None,
) -> ScreenPushStatus:
    global _push_proc, _push_meta, _stderr_bucket
    if not is_windows():
        raise RuntimeError("屏幕 RTSP 推流仅支持 Windows 本机")

    rtsp_url = build_rtsp_url(rtsp_host, rtsp_port, stream_name)
    safe_name = _sanitize_stream_name(stream_name)
    cmd = build_screen_push_cmd(
        rtsp_url=rtsp_url,
        fps=fps,
        width=width,
        capture=capture,
        offset_x=offset_x,
        offset_y=offset_y,
        video_size=video_size,
    )
    cmd_str = " ".join(f'"{p}"' if " " in p else p for p in cmd)

    with _state_lock:
        if _proc_alive(_push_proc):
            raise RuntimeError(f"已有推流任务在运行（{_push_meta.get('rtsp_url')}），请先停止")

        _stderr_bucket = []
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if is_windows() else 0,
            )
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"启动 ffmpeg 推流失败：{e}") from e

        threading.Thread(
            target=_drain_stderr, args=(proc, _stderr_bucket), daemon=True,
        ).start()
        _push_proc = proc
        _push_meta = {
            "rtsp_url": rtsp_url,
            "stream_name": safe_name,
            "fps": int(fps),
            "width": int(width),
            "started_at": time.time(),
            "last_error": None,
            "command": cmd_str,
        }

        # 稍等确认进程未立即退出
        time.sleep(0.6)
        if proc.poll() is not None:
            err = b"".join(_stderr_bucket).decode("utf-8", errors="ignore").strip()
            _push_proc = None
            msg = err[-500:] if err else "ffmpeg 推流进程已退出，请确认 MediaMTX 已启动且端口可达"
            _push_meta["last_error"] = msg
            raise RuntimeError(msg)

    log.info("screen RTSP push started: %s pid=%s", rtsp_url, proc.pid)
    return get_status()


def stop_push() -> ScreenPushStatus:
    global _push_proc, _push_meta
    with _state_lock:
        if _push_proc:
            _kill_proc_tree(_push_proc)
            _push_proc = None
    log.info("screen RTSP push stopped")
    return get_status()
