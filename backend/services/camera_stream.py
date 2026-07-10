"""摄像头 MJPEG 流：用 ffmpeg 读本地视频(循环)或 rtsp 源，转裸 MJPEG，按帧封装为 multipart。

按需按路：每个 HTTP stream 连接 spawn 一个 ffmpeg；客户端断开(GeneratorExit) -> kill。
"""
import os
import re
import subprocess
import threading
import time

from flask import current_app

_SOI = b"\xff\xd8"   # JPEG 起始
_EOI = b"\xff\xd9"   # JPEG 结束
BOUNDARY = b"frame"


def build_ffmpeg_cmd(ffmpeg_exe, source_type, source, width, fps):
    """构造 ffmpeg 命令(参数列表)。file 源循环；rtsp 源走 tcp。输出裸 MJPEG 到 stdout。"""
    common_in = ["-hide_banner", "-loglevel", "error"]
    if source_type == "rtsp":
        src = ["-rtsp_transport", "tcp", "-i", source]
    elif source_type == "device":  # 本机摄像头(Windows DirectShow)，source 为设备名
        src = ["-f", "dshow", "-i", f"video={source}"]
    else:
        # 本地文件：循环播放，由输出 -r 控制帧率（不用 -re，避免首帧极慢或卡死）
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
                    buf = buf[start:]   # 丢弃 SOI 前垃圾，保留半帧
                break
            end += 2
            yield buf[start:end]
            buf = buf[end:]


def parse_dshow_video_names(stderr_text):
    """从 ffmpeg -list_devices 的 stderr 文本里解析视频设备名列表。"""
    return re.findall(r'"([^"]+)"\s*\(video\)', stderr_text or "")


def list_dshow_devices(ffmpeg_exe=None):
    """枚举本机 DirectShow 视频设备名（Windows）。ffmpeg 将设备清单打到 stderr 且退出码非 0，属正常。"""
    import imageio_ffmpeg
    exe = ffmpeg_exe or imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run([exe, "-hide_banner", "-list_devices", "true",
                           "-f", "dshow", "-i", "dummy"],
                          capture_output=True, text=True, errors="ignore")
    return parse_dshow_video_names(proc.stderr)


def _resolve_source(camera, upload_folder=None):
    """file 源相对路径 -> 绝对路径(限定 UPLOAD_FOLDER 内防穿越)；rtsp/device 源原样返回。"""
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
    """检查摄像头来源是否可用（列表展示 / 保存校验 / 开流前检查）。"""
    if not camera.source:
        return False
    try:
        if camera.source_type == "file":
            _resolve_source(camera, upload_folder)
            return True
        if camera.source_type == "rtsp":
            return camera.source.startswith("rtsp://")
        if camera.source_type == "device":
            return bool(camera.source.strip())
    except (ValueError, FileNotFoundError, OSError):
        return False
    return False


def _drain_stderr(proc, bucket):
    """后台读 stderr，避免 PIPE 塞满导致 ffmpeg 死锁。"""
    try:
        if proc.stderr:
            bucket.append(proc.stderr.read())
    except Exception:  # noqa: BLE001
        pass


def _first_jpeg_from_buf(buf):
    """从缓冲区提取第一帧完整 JPEG，无则返回 None。"""
    start = buf.find(_SOI)
    if start < 0:
        return None, buf
    end = buf.find(_EOI, start + 2)
    if end < 0:
        return None, buf[start:] if start > 0 else buf
    return buf[start:end + 2], buf[end + 2:]


def probe_file_mjpeg(camera, upload_folder=None, timeout=18):
    """预检本地视频能否产出 MJPEG 帧；失败返回错误信息字符串，成功返回 None。"""
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
        # 只保留最后几行关键信息
        lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
        return lines[-1] if lines else err
    return "无法从视频生成 MJPEG 帧（请确认 MP4 可播放，或降低分辨率/帧率）"


def mjpeg_stream(source_type, source, width=640, fps=15):
    """生成 multipart MJPEG 字节流；按需 spawn ffmpeg，结束/断开时 kill。

    source 须为已解析的绝对路径(file)或 rtsp/device 地址；勿在生成器内访问 Flask 上下文。
    """
    import imageio_ffmpeg
    import logging
    log = logging.getLogger(__name__)
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
            yield (b"--" + BOUNDARY + b"\r\n"
                   b"Content-Type: image/jpeg\r\n"
                   b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                   + frame + b"\r\n")
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
