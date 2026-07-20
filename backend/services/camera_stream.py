"""摄像头 MJPEG 流：ffmpeg 读本地视频(循环)/RTSP/本机设备 → 裸 MJPEG multipart。

7×24 监控墙：同一摄像头多路订阅共享一个 ffmpeg（SharedMjpegHub），断线自动重启拉流。
按需：无订阅者时宽限期后释放进程。
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from typing import Generator

from flask import current_app

_SOI = b"\xff\xd8"
_EOI = b"\xff\xd9"
BOUNDARY = b"frame"
log = logging.getLogger(__name__)

# 共享拉流：key -> SharedMjpegHub
_hubs: dict[str, "SharedMjpegHub"] = {}
_hubs_lock = threading.Lock()
_HUB_IDLE_SEC = 8.0
# FFmpeg 5+ 用 -timeout（微秒）；旧版用 -stimeout。探测一次后缓存。
_rtsp_timeout_args_cache: list[str] | None = None


def _rtsp_io_timeout_args(ffmpeg_exe) -> list[str]:
    """RTSP socket I/O 超时参数；兼容新旧 ffmpeg，避免 Unrecognized option。"""
    global _rtsp_timeout_args_cache
    if _rtsp_timeout_args_cache is not None:
        return list(_rtsp_timeout_args_cache)
    help_text = ""
    try:
        r = subprocess.run(
            [ffmpeg_exe, "-hide_banner", "-h", "demuxer=rtsp"],
            capture_output=True,
            text=True,
            errors="ignore",
            timeout=15,
        )
        help_text = (r.stdout or "") + (r.stderr or "")
    except Exception:  # noqa: BLE001
        help_text = ""
    # 优先新选项；旧构建才回退 stimeout
    if re.search(r"(?m)^\s*-timeout\s", help_text):
        _rtsp_timeout_args_cache = ["-timeout", "5000000"]
    elif re.search(r"(?m)^\s*-stimeout\s", help_text):
        _rtsp_timeout_args_cache = ["-stimeout", "5000000"]
    else:
        _rtsp_timeout_args_cache = []
    return list(_rtsp_timeout_args_cache)


def build_ffmpeg_cmd(ffmpeg_exe, source_type, source, width, fps):
    """构造 ffmpeg 命令。file 源循环；rtsp 源走 tcp + 超时；输出裸 MJPEG。"""
    common_in = ["-hide_banner", "-loglevel", "error"]
    if source_type == "rtsp":
        # timeout 微秒；断流后由 Hub 重启进程，配合监控墙前端重连
        src = [
            "-rtsp_transport", "tcp",
            *_rtsp_io_timeout_args(ffmpeg_exe),
            "-i", source,
        ]
    elif source_type == "device":
        src = ["-f", "dshow", "-i", f"video={source}"]
    else:
        src = [
            "-stream_loop", "-1",
            "-fflags", "+genpts",
            "-i", source,
        ]
    w = max(160, min(int(width or 640), 1920))
    f = max(1, min(int(fps or 15), 30))
    return [
        ffmpeg_exe, *common_in, *src,
        "-an",
        "-vf", f"scale={w}:-2:flags=fast_bilinear,format=yuvj420p",
        "-r", str(f),
        "-c:v", "mjpeg",
        "-f", "mjpeg", "-q:v", "5",
        "pipe:1",
    ]


def iter_jpeg_frames(chunks):
    """从字节块迭代里按 SOI/EOI 切出完整 JPEG 帧。"""
    buf = b""
    for chunk in chunks:
        if not chunk:
            continue
        buf += chunk
        while True:
            start = buf.find(_SOI)
            if start < 0:
                break
            end = buf.find(_EOI, start + 2)
            if end < 0:
                if start > 0:
                    buf = buf[start:]
                break
            end += 2
            yield buf[start:end]
            buf = buf[end:]


def parse_dshow_video_names(stderr_text):
    return re.findall(r'"([^"]+)"\s*\(video\)', stderr_text or "")


def list_dshow_devices(ffmpeg_exe=None):
    import imageio_ffmpeg
    exe = ffmpeg_exe or imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run(
        [exe, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
        capture_output=True, text=True, errors="ignore",
    )
    return parse_dshow_video_names(proc.stderr)


def _resolve_source(camera, upload_folder=None):
    if camera.source_type in ("rtsp", "device"):
        return camera.source
    base = os.path.abspath(upload_folder or current_app.config["UPLOAD_FOLDER"])
    p = os.path.abspath(os.path.join(base, camera.source or ""))
    if not p.startswith(base):
        raise ValueError("非法的视频路径")
    if not os.path.isfile(p):
        raise FileNotFoundError(f"视频文件不存在：{camera.source}")
    return p


def check_source_ready(camera, upload_folder=None):
    if not camera.source:
        return False
    try:
        if camera.source_type == "file":
            _resolve_source(camera, upload_folder)
            return True
        if camera.source_type == "rtsp":
            return str(camera.source).startswith("rtsp://")
        if camera.source_type == "device":
            return bool(str(camera.source).strip())
    except (ValueError, FileNotFoundError, OSError):
        return False
    return False


def _drain_stderr(proc, bucket):
    try:
        if proc.stderr:
            bucket.append(proc.stderr.read())
    except Exception:  # noqa: BLE001
        pass


def _first_jpeg_from_buf(buf):
    start = buf.find(_SOI)
    if start < 0:
        return None, buf
    end = buf.find(_EOI, start + 2)
    if end < 0:
        return None, buf[start:] if start > 0 else buf
    return buf[start:end + 2], buf[end + 2:]


def probe_file_mjpeg(camera, upload_folder=None, timeout=18):
    if camera.source_type != "file":
        return None
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    source = _resolve_source(camera, upload_folder)
    cmd = build_ffmpeg_cmd(exe, "file", source, camera.resolution or 640, camera.fps or 15)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    err_bucket = []
    threading.Thread(target=_drain_stderr, args=(proc, err_bucket), daemon=True).start()
    buf = b""
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            chunk = proc.stdout.read(4096)
            if chunk:
                buf += chunk
                frame, buf = _first_jpeg_from_buf(buf)
                if frame:
                    return None
            elif proc.poll() is not None:
                break
            else:
                time.sleep(0.05)
    finally:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass
    err = b"".join(err_bucket).decode("utf-8", errors="ignore").strip()
    if err:
        lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
        return lines[-1] if lines else err
    return "无法从视频生成 MJPEG 帧（请确认 MP4 可播放，或降低分辨率/帧率）"


def probe_rtsp_mjpeg(camera, upload_folder=None, timeout=12):
    """探活 RTSP：短时拉流直到拿到一帧 JPEG；失败返回错误信息。"""
    if camera.source_type != "rtsp":
        return None
    if not check_source_ready(camera, upload_folder):
        return "RTSP 地址无效"
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    source = _resolve_source(camera, upload_folder)
    cmd = build_ffmpeg_cmd(exe, "rtsp", source, camera.resolution or 640, camera.fps or 10)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    err_bucket = []
    threading.Thread(target=_drain_stderr, args=(proc, err_bucket), daemon=True).start()
    buf = b""
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            chunk = proc.stdout.read(4096)
            if chunk:
                buf += chunk
                frame, buf = _first_jpeg_from_buf(buf)
                if frame:
                    return None
            elif proc.poll() is not None:
                break
            else:
                time.sleep(0.05)
    finally:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass
    err = b"".join(err_bucket).decode("utf-8", errors="ignore").strip()
    if err:
        lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
        return lines[-1] if lines else err
    return "无法连接 RTSP 或超时未收到画面"


def _pack_frame(frame: bytes) -> bytes:
    return (
        b"--" + BOUNDARY + b"\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
        + frame + b"\r\n"
    )


def _request_disconnected() -> bool:
    """Flask 请求是否已断开（切走监控墙后尽快释放 hub）。"""
    try:
        from flask import has_request_context, request
        if has_request_context():
            return bool(getattr(request, "is_disconnected", False))
    except Exception:  # noqa: BLE001
        pass
    return False


class SharedMjpegHub:
    """单路摄像头共享拉流：多 HTTP 订阅者共用一个 ffmpeg，进程退出自动重启。"""

    def __init__(self, key: str, source_type: str, source: str, width: int, fps: int):
        self.key = key
        self.source_type = source_type
        self.source = source
        self.width = width
        self.fps = fps
        self.clients = 0
        self.latest: bytes | None = None
        self.frame_seq = 0
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._proc = None
        self._last_warn_at = 0.0
        # 拉流失败世代号：增长后结束当前 HTTP，便于切页后不再空挂订阅
        self._epoch = 0
        self._thread = threading.Thread(target=self._run, name=f"cam-hub-{key}", daemon=True)
        self._idle_timer: threading.Timer | None = None
        self._thread.start()

    def _warn_throttled(self, msg: str, *args):
        now = time.time()
        if now - self._last_warn_at < 20:
            return
        self._last_warn_at = now
        log.warning(msg, *args)

    def _kill_proc(self):
        proc = self._proc
        if not proc:
            return
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass
        self._proc = None

    def _bump_epoch(self):
        with self._cond:
            self._epoch += 1
            self._cond.notify_all()

    def _wait_for_clients(self) -> bool:
        """无人订阅时挂起，不拉起 ffmpeg。返回 False 表示 hub 已 stop。"""
        with self._cond:
            while self.clients <= 0 and not self._stop.is_set():
                self._cond.wait(timeout=1.0)
        return not self._stop.is_set()

    def _run(self):
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        backoff = 1.0
        while not self._stop.is_set():
            # 必须先有订阅者再拉流，避免切页后空转刷日志
            if not self._wait_for_clients():
                break
            err_bucket: list[bytes] = []
            cmd = build_ffmpeg_cmd(exe, self.source_type, self.source, self.width, self.fps)
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            except Exception as e:  # noqa: BLE001
                self._warn_throttled("camera hub spawn failed %s: %s", self.key, e)
                self._bump_epoch()
                time.sleep(min(backoff, 15))
                backoff = min(backoff * 1.5, 15)
                continue
            self._proc = proc
            threading.Thread(target=_drain_stderr, args=(proc, err_bucket), daemon=True).start()
            got = False

            def _chunks():
                while not self._stop.is_set():
                    with self._cond:
                        if self.clients <= 0:
                            return
                    data = proc.stdout.read(4096) if proc.stdout else b""
                    if not data:
                        return
                    yield data

            try:
                for frame in iter_jpeg_frames(_chunks()):
                    if self._stop.is_set():
                        break
                    with self._cond:
                        if self.clients <= 0:
                            break
                    got = True
                    with self._cond:
                        self.latest = frame
                        self.frame_seq += 1
                        self._cond.notify_all()
            finally:
                self._kill_proc()
            if self._stop.is_set():
                break
            with self._cond:
                idle = self.clients <= 0
            if idle:
                continue
            err = b"".join(err_bucket).decode("utf-8", errors="ignore").strip()
            if err:
                self._warn_throttled("camera hub ffmpeg exit %s: %s", self.key, err[-300:])
            elif not got:
                self._warn_throttled("camera hub no frame %s", self.key)
            # 无帧失败：结束当前 HTTP，等前端退避重连；切页后不再订阅
            if not got:
                self._bump_epoch()
            time.sleep(min(backoff, 8))
            backoff = min(backoff * 1.5, 8) if not got else 1.0

    def subscribe(self) -> Generator[bytes, None, None]:
        with self._cond:
            self.clients += 1
            start_epoch = self._epoch
            self._cond.notify_all()
            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
        last_seq = -1
        try:
            while not self._stop.is_set():
                if _request_disconnected():
                    break
                with self._cond:
                    if self._epoch != start_epoch:
                        break
                    self._cond.wait(timeout=1.0)
                    if self._epoch != start_epoch:
                        break
                    if self.latest is None or self.frame_seq == last_seq:
                        continue
                    frame = self.latest
                    last_seq = self.frame_seq
                yield _pack_frame(frame)
        finally:
            with self._cond:
                self.clients = max(0, self.clients - 1)
                gone = self.clients <= 0
                self._cond.notify_all()
            if gone:
                self._kill_proc()
                self._schedule_idle_stop()

    def _schedule_idle_stop(self):
        if self._idle_timer:
            self._idle_timer.cancel()

        def _idle():
            with _hubs_lock:
                hub = _hubs.get(self.key)
                if hub is not self:
                    return
                with self._cond:
                    if self.clients > 0:
                        return
                self.stop()
                _hubs.pop(self.key, None)

        self._idle_timer = threading.Timer(_HUB_IDLE_SEC, _idle)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def stop(self):
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        self._kill_proc()


def mjpeg_stream_shared(camera_id, source_type, source, width=640, fps=15):
    """多路共享 MJPEG（监控墙 7×24 推荐）。"""
    key = f"{camera_id}:{source_type}:{source}:{int(width or 640)}:{int(fps or 15)}"
    with _hubs_lock:
        hub = _hubs.get(key)
        if hub is None or hub._stop.is_set():
            hub = SharedMjpegHub(key, source_type, source, width or 640, fps or 15)
            _hubs[key] = hub
    yield from hub.subscribe()


def mjpeg_stream(source_type, source, width=640, fps=15):
    """单连接独占 ffmpeg（兼容旧预览）；结束/断开时 kill。"""
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = build_ffmpeg_cmd(exe, source_type, source, width or 640, fps or 15)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    err_bucket = []
    threading.Thread(target=_drain_stderr, args=(proc, err_bucket), daemon=True).start()

    def _chunks():
        while True:
            data = proc.stdout.read(4096)
            if not data:
                if proc.poll() is not None:
                    err = b"".join(err_bucket).decode("utf-8", errors="ignore").strip()
                    if err:
                        log.warning("camera ffmpeg exit: %s", err)
                return
            yield data

    try:
        yielded = False
        for frame in iter_jpeg_frames(_chunks()):
            yielded = True
            yield _pack_frame(frame)
        if not yielded:
            err = b"".join(err_bucket).decode("utf-8", errors="ignore").strip()
            if err:
                log.warning("camera ffmpeg no frame: %s", err)
    finally:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass
