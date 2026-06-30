"""摄像头 MJPEG 流：用 ffmpeg 读本地视频(循环)或 rtsp 源，转裸 MJPEG，按帧封装为 multipart。

按需按路：每个 HTTP stream 连接 spawn 一个 ffmpeg；客户端断开(GeneratorExit) -> kill。
"""
import os
import re
import subprocess

from flask import current_app

_SOI = b"\xff\xd8"   # JPEG 起始
_EOI = b"\xff\xd9"   # JPEG 结束
BOUNDARY = b"frame"


def build_ffmpeg_cmd(ffmpeg_exe, source_type, source, width, fps):
    """构造 ffmpeg 命令(参数列表)。file 源循环+实时；rtsp 源走 tcp。输出裸 MJPEG 到 stdout。"""
    common_in = ["-hide_banner", "-loglevel", "error"]
    if source_type == "rtsp":
        src = ["-rtsp_transport", "tcp", "-i", source]
    elif source_type == "device":  # 本机摄像头(Windows DirectShow)，source 为设备名
        src = ["-f", "dshow", "-i", f"video={source}"]
    else:  # file：循环 + 按真实速率，模拟直播
        src = ["-stream_loop", "-1", "-re", "-i", source]
    return [
        ffmpeg_exe, *common_in, *src,
        "-vf", f"scale={width}:-2",
        "-r", str(fps),
        "-f", "mjpeg", "-q:v", "7",
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


def _resolve_source(camera):
    """file 源相对路径 -> 绝对路径(限定 UPLOAD_FOLDER 内防穿越)；rtsp/device 源原样返回。"""
    if camera.source_type in ("rtsp", "device"):
        return camera.source
    base = os.path.abspath(current_app.config["UPLOAD_FOLDER"])
    p = os.path.abspath(os.path.join(base, camera.source or ""))
    if not p.startswith(base):
        raise ValueError("非法的视频路径")
    return p


def mjpeg_stream(camera):
    """生成 multipart MJPEG 字节流；按需 spawn ffmpeg，结束/断开时 kill。"""
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    source = _resolve_source(camera)
    cmd = build_ffmpeg_cmd(exe, camera.source_type, source,
                           camera.resolution or 640, camera.fps or 15)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, bufsize=0)

    def _chunks():
        while True:
            data = proc.stdout.read(4096)
            if not data:
                return
            yield data

    try:
        for frame in iter_jpeg_frames(_chunks()):
            yield (b"--" + BOUNDARY + b"\r\n"
                   b"Content-Type: image/jpeg\r\n"
                   b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                   + frame + b"\r\n")
    finally:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
