"""YOLO 推理服务：加载本地权重对图片做目标检测。

模型按权重绝对路径 + 文件 mtime 缓存，避免重复加载。
ultralytics / torch 体积大，全部惰性导入，加快应用启动。
"""
import base64
import json
import math
import os
import sys
import threading

import cv2
import numpy as np

_cache = {}            # abs_path -> (mtime, YOLO 实例)
_pipe_cache = {}       # (task, model_dir) -> transformers pipeline
_lock = threading.Lock()
ROBOFLOW_META_FILE = "roboflow_meta.json"
_ROBOFLOW_COLORS = {
    "Engine Flames": (0, 0, 255),      # 红色（BGR）
    "Rocket Body": (0, 255, 255),      # 黄色（BGR）
    "Space": (100, 200, 255),
}
_roboflow_session = None
_rocket_font_cache = {}
# 一级箭体参考高度（米），用于像素位移换算下降速度
ROCKET_STAGE_HEIGHT_M = float(os.getenv("ROCKET_STAGE_HEIGHT_M", "47"))


def _open_h264(dst_path, fps, w, h):
    """打开 H.264(faststart, yuv420p) 写入器；返回 (writer, even_w, even_h)。

    浏览器原生可播放 + 正确时长。mp4v(MPEG-4 Part2) 多数浏览器无法播放，故弃用。
    """
    import imageio.v2 as imageio
    ew, eh = w - (w % 2), h - (h % 2)  # H.264 需偶数尺寸
    writer = imageio.get_writer(
        dst_path, format="FFMPEG", mode="I", fps=float(fps) or 25.0,
        codec="libx264", pixelformat="yuv420p", macro_block_size=None,
        ffmpeg_params=["-movflags", "+faststart"],
    )
    return writer, ew, eh


def _write_bgr(writer, bgr, ew, eh):
    """写一帧（输入 BGR，裁到偶数尺寸并转 RGB）。"""
    writer.append_data(cv2.cvtColor(bgr[:eh, :ew], cv2.COLOR_BGR2RGB))


def load_roboflow_meta(abs_path):
    """读取权重同目录下的 Roboflow 元信息（存在则走云端推理）。"""
    folder = os.path.dirname(os.path.abspath(abs_path))
    meta_path = os.path.join(folder, ROBOFLOW_META_FILE)
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
        return data if data.get("model_id") else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def save_roboflow_meta(folder, model_id, classes=None):
    """写入 Roboflow 推理元信息（与权重同目录）。"""
    os.makedirs(folder, exist_ok=True)
    meta = {
        "model_id": model_id,
        "classes": classes or ["Engine Flames", "Rocket Body", "Space"],
        "inference": "serverless",
    }
    path = os.path.join(folder, ROBOFLOW_META_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return path


def _roboflow_api_key():
    return os.getenv("ROBOFLOW_API_KEY")


def _roboflow_http_session():
    global _roboflow_session
    if _roboflow_session is None:
        import requests
        _roboflow_session = requests.Session()
    return _roboflow_session


def _roboflow_preds_to_detections(preds):
    detections = []
    for i, p in enumerate(preds or []):
        cx, cy = float(p.get("x", 0)), float(p.get("y", 0))
        bw, bh = float(p.get("width", 0)), float(p.get("height", 0))
        x1, y1 = cx - bw / 2, cy - bh / 2
        x2, y2 = cx + bw / 2, cy + bh / 2
        detections.append({
            "className": p.get("class", "unknown"),
            "classId": i,
            "confidence": round(float(p.get("confidence", 0) or 0), 4),
            "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
        })
    return detections


def _bbox_center_xy(bbox):
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2, (y1 + y2) / 2


def _bbox_wh(bbox):
    x1, y1, x2, y2 = bbox
    return x2 - x1, y2 - y1


def _norm_class(name):
    return str(name or "").strip().lower()


def _is_rocket_body_class(name):
    n = _norm_class(name)
    return (
        n == "rocket body"
        or ("rocket" in n and "body" in n)
        or n in ("箭体", "火箭本体", "火箭", "rocket")
    )


def _is_engine_flames_class(name):
    n = _norm_class(name)
    return (
        n in ("engine flames", "engine_flames", "engine flame")
        or "flame" in n
        or n in ("火焰", "发动机火焰")
    )


def _is_rocket_tracking_classes(class_names):
    names = list(class_names or [])
    if not names:
        return False
    if any(_is_rocket_body_class(n) for n in names):
        return True
    if any(_is_engine_flames_class(n) for n in names):
        return True
    return any("rocket" in _norm_class(n) or "火箭" in str(n) for n in names)


def _is_rocket_tracking_model(model_key=None, class_names=None, model_id=None):
    """判断是否为火箭回收跟踪类模型（Roboflow 或本地自定义训练）。"""
    if model_id and "rocket-detect" in str(model_id).lower():
        return True
    key = _norm_class(model_key).replace("-", "_")
    if key and any(k in key for k in ("rocket", "china_rocket")):
        return True
    return _is_rocket_tracking_classes(class_names)


def _yolo_result_to_detections(result):
    """Ultralytics 单帧结果 → 统一 detections 结构。"""
    detections = []
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return detections
    names = getattr(result, "names", None) or {}
    for b in boxes:
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
        cid = int(b.cls[0]) if getattr(b, "cls", None) is not None else -1
        conf = float(b.conf[0]) if getattr(b, "conf", None) is not None else 0.0
        detections.append({
            "className": _safe_class_name(names, cid),
            "classId": cid,
            "confidence": round(conf, 4),
            "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
        })
    return detections


def _model_class_names(model):
    names = getattr(model, "names", None) or {}
    if isinstance(names, dict):
        return [str(names[k]) for k in sorted(names.keys())]
    return [str(n) for n in names]


def _apply_rocket_frame_overlay(frame, detections, tracker, img_w, img_h):
    """绘制检测框、十字丝与遥测面板，返回 (画面, 遥测指标)。"""
    plotted = _draw_roboflow_detections(frame, detections)
    plotted = _draw_rocket_body_crosshair(plotted, detections, img_w, img_h)
    metrics = tracker.update(detections)
    plotted = _draw_rocket_telemetry_overlay(plotted, metrics, img_w, img_h)
    return plotted, metrics


def _attach_rocket_telemetry_stats(result, speed_samples, is_rocket):
    if is_rocket and speed_samples:
        result["rocketTelemetry"] = {
            "avgDescentSpeed": round(sum(speed_samples) / len(speed_samples), 1),
            "maxDescentSpeed": round(max(speed_samples), 1),
            "rocketStageHeightM": ROCKET_STAGE_HEIGHT_M,
        }
    return result


def _refine_rocket_detect_detections(detections, img_w, img_h):
    """Rocket Detect 近景落台后处理：剔除平台钢架误检，并按火焰位置补全箭体框。"""
    flames = [d for d in detections if _is_engine_flames_class(d.get("className"))]
    bodies = [d for d in detections if _is_rocket_body_class(d.get("className"))]
    others = [
        d for d in detections
        if not _is_engine_flames_class(d.get("className"))
        and not _is_rocket_body_class(d.get("className"))
    ]

    max_dx = max(45.0, img_w * 0.12)
    flame_cxs = [_bbox_center_xy(f["bbox"])[0] for f in flames]
    kept_bodies = []

    for body in bodies:
        bcx, _ = _bbox_center_xy(body["bbox"])
        bw, _ = _bbox_wh(body["bbox"])
        # 着陆平台左右竖梁常被误检为箭体：窄条 + 靠边
        if bw < img_w * 0.04 and (bcx < img_w * 0.2 or bcx > img_w * 0.8):
            continue
        if flames:
            if any(abs(bcx - fcx) <= max_dx for fcx in flame_cxs):
                kept_bodies.append(body)
        elif img_w * 0.25 <= bcx <= img_w * 0.75:
            kept_bodies.append(body)

    if len(kept_bodies) > 1:
        if flames:
            primary_fcx = _bbox_center_xy(
                max(flames, key=lambda f: f["confidence"])["bbox"]
            )[0]
            kept_bodies.sort(
                key=lambda b: (
                    abs(_bbox_center_xy(b["bbox"])[0] - primary_fcx),
                    -b["confidence"],
                )
            )
            kept_bodies = [kept_bodies[0]]
        else:
            kept_bodies = [max(kept_bodies, key=lambda b: b["confidence"])]

    if flames and not kept_bodies:
        flame = max(flames, key=lambda f: f["confidence"])
        fx1, fy1, fx2, fy2 = flame["bbox"]
        fc_x, _ = _bbox_center_xy(flame["bbox"])
        flame_w, flame_h = fx2 - fx1, fy2 - fy1
        body_w = max(flame_w * 2.8, img_w * 0.055)
        body_h = max(flame_h * 8, img_h * 0.35)
        body_h = min(body_h, max(fy1 - img_h * 0.05, flame_h * 4))
        by2 = fy1 + flame_h * 0.15
        by1 = max(img_h * 0.05, by2 - body_h)
        kept_bodies.append({
            "className": "Rocket Body",
            "classId": -1,
            "confidence": round(float(flame["confidence"]) * 0.9, 4),
            "bbox": [
                round(fc_x - body_w / 2, 1),
                round(by1, 1),
                round(fc_x + body_w / 2, 1),
                round(by2, 1),
            ],
        })

    return others + flames + kept_bodies


def _rocket_overlay_font(size=18):
    if size in _rocket_font_cache:
        return _rocket_font_cache[size]
    from PIL import ImageFont
    win = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        os.path.join(win, "Fonts", "msyh.ttc"),
        os.path.join(win, "Fonts", "msyhbd.ttc"),
        os.path.join(win, "Fonts", "simhei.ttf"),
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                font = ImageFont.truetype(path, size)
                _rocket_font_cache[size] = font
                return font
            except OSError:
                continue
    font = ImageFont.load_default()
    _rocket_font_cache[size] = font
    return font


class _RocketTelemetryTracker:
    """根据逐帧箭体/火焰检测框估算下降速度与姿态角。"""

    def __init__(self, img_w, img_h, fps):
        self.img_w = img_w
        self.img_h = img_h
        self.fps = max(float(fps or 25.0), 1.0)
        self.prev_track_y = None
        self.prev_body_h = None
        self.speed_ema = None
        self.vert_ema = None
        self.horiz_ema = None
        self.alpha = 0.28

    @staticmethod
    def _pick_target(detections):
        bodies = [d for d in detections if _is_rocket_body_class(d.get("className"))]
        flames = [d for d in detections if _is_engine_flames_class(d.get("className"))]
        if bodies:
            return max(bodies, key=lambda d: d.get("confidence", 0))
        if flames:
            return max(flames, key=lambda d: d.get("confidence", 0))
        return None

    def _smooth(self, prev, value):
        if prev is None:
            return value
        return prev * (1 - self.alpha) + value * self.alpha

    def update(self, detections):
        target = self._pick_target(detections)
        if not target:
            return {
                "valid": bool(self.speed_ema is not None),
                "descent_speed": round(self.speed_ema or 0.0, 1),
                "vertical_angle": round(self.vert_ema or 0.0, 1),
                "horizontal_angle": round(self.horiz_ema or 0.0, 1),
            }

        x1, y1, x2, y2 = target["bbox"]
        cx = (x1 + x2) / 2
        track_y = y2
        bw = max(x2 - x1, 1.0)
        bh = max(y2 - y1, 1.0)

        vertical_angle = max(0.0, min(90.0, 90.0 - math.degrees(math.atan2(bw, bh))))
        horizontal_angle = abs(
            math.degrees(math.atan2(cx - self.img_w / 2, max(self.img_h - track_y, 1.0)))
        )

        descent_speed = 0.0
        if self.prev_track_y is not None:
            dy = track_y - self.prev_track_y
            ref_h = bh if _is_rocket_body_class(target.get("className")) else (self.prev_body_h or bh)
            m_per_px = ROCKET_STAGE_HEIGHT_M / max(ref_h, 1.0)
            if dy > 0:
                descent_speed = min(dy * self.fps * m_per_px, 80.0)

        self.prev_track_y = track_y
        if _is_rocket_body_class(target.get("className")):
            self.prev_body_h = bh

        self.speed_ema = self._smooth(self.speed_ema, descent_speed)
        self.vert_ema = self._smooth(self.vert_ema, vertical_angle)
        self.horiz_ema = self._smooth(self.horiz_ema, horizontal_angle)

        return {
            "valid": True,
            "descent_speed": round(self.speed_ema, 1),
            "vertical_angle": round(self.vert_ema, 1),
            "horizontal_angle": round(self.horiz_ema, 1),
        }


_CROSSHAIR_COLOR = (255, 0, 255)  # 鲜艳洋红（BGR）


def _pick_rocket_body(detections):
    bodies = [d for d in detections if _is_rocket_body_class(d.get("className"))]
    if not bodies:
        return None
    return max(bodies, key=lambda d: d.get("confidence", 0))


def _draw_dashed_line_bgr(img, p1, p2, color, thickness=2, dash_len=14, gap_len=10):
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])
    length = math.hypot(x2 - x1, y2 - y1)
    if length < 1:
        return
    dx, dy = (x2 - x1) / length, (y2 - y1) / length
    dist = 0.0
    draw = True
    while dist < length:
        seg = min((dash_len if draw else gap_len), length - dist)
        if draw:
            sx, sy = int(x1 + dx * dist), int(y1 + dy * dist)
            ex, ey = int(x1 + dx * (dist + seg)), int(y1 + dy * (dist + seg))
            cv2.line(img, (sx, sy), (ex, ey), color, thickness, cv2.LINE_AA)
        dist += seg
        draw = not draw


def _draw_rocket_body_crosshair(frame, detections, img_w, img_h):
    """以箭体检测框中心绘制虚线十字丝（水平宽 1/2 视频宽，垂直高 1/10 视频高）。"""
    body = _pick_rocket_body(detections)
    if not body:
        return frame
    x1, y1, x2, y2 = body["bbox"]
    cx = int((x1 + x2) / 2)
    cy = int((y1 + y2) / 2)
    thickness = max(2, int(min(img_w, img_h) * 0.003))
    h_half = img_w / 4
    v_half = img_h / 20
    canvas = frame
    _draw_dashed_line_bgr(
        canvas,
        (int(cx - h_half), cy),
        (int(cx + h_half), cy),
        _CROSSHAIR_COLOR,
        thickness,
    )
    _draw_dashed_line_bgr(
        canvas,
        (cx, int(cy - v_half)),
        (cx, int(cy + v_half)),
        _CROSSHAIR_COLOR,
        thickness,
    )
    cv2.circle(canvas, (cx, cy), max(3, thickness), _CROSSHAIR_COLOR, -1, cv2.LINE_AA)
    return canvas


def _draw_rocket_telemetry_overlay(frame, metrics, img_w, img_h):
    """在视频右上方绘制火箭遥测 HUD（科技感布局）。"""
    from PIL import Image, ImageDraw

    if metrics.get("valid"):
        lines = [
            f"下降速度：{metrics['descent_speed']:.1f}米/秒",
            f"垂直角度：{metrics['vertical_angle']:.1f}度",
            f"水平角度：{metrics['horizontal_angle']:.1f}度",
        ]
    else:
        lines = [
            "下降速度：--米/秒",
            "垂直角度：--度",
            "水平角度：--度",
        ]

    font_size = max(14, int(img_w * 0.024))
    title_size = max(13, int(font_size * 0.88))
    font = _rocket_overlay_font(font_size)
    font_title = _rocket_overlay_font(title_size)

    bg = (4, 12, 28, 205)
    border = (0, 196, 255, 210)
    accent = (0, 214, 255, 255)
    title_c = (72, 228, 255, 255)
    text_c = (235, 248, 255, 255)
    divider_c = (0, 150, 210, 110)

    pad_x = max(14, int(img_w * 0.024))
    pad_y = max(10, int(img_h * 0.012))
    line_h = max(26, int(font_size * 1.55))
    title_h = max(24, int(title_size * 1.65))
    accent_w = 3
    line_gap = max(5, int(font_size * 0.32))
    margin = max(12, int(img_w * 0.028))
    bracket = min(20, max(12, int(img_w * 0.028)))

    title = "◈ 火箭遥测"
    probe = Image.new("RGBA", (4, 4))
    probe_draw = ImageDraw.Draw(probe)
    title_bbox = probe_draw.textbbox((0, 0), title, font=font_title)
    inner_w = title_bbox[2] - title_bbox[0]
    for text in lines:
        lb = probe_draw.textbbox((0, 0), text, font=font)
        inner_w = max(inner_w, lb[2] - lb[0])

    box_w = inner_w + pad_x * 2 + accent_w + 10
    box_h = pad_y * 2 + title_h + line_gap + len(lines) * line_h + (len(lines) - 1) * line_gap

    x0 = max(0, img_w - box_w - margin)
    y0 = margin

    pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
    draw = ImageDraw.Draw(pil)

    draw.rectangle([x0, y0, x0 + box_w, y0 + box_h], fill=bg, outline=border, width=1)
    draw.rectangle([x0, y0, x0 + accent_w, y0 + box_h], fill=accent)

    def _corner_brackets(bx, by, bw, bh):
        t = 2
        b = bracket
        draw.line([(bx + b, by), (bx, by), (bx, by + b)], fill=accent, width=t)
        draw.line([(bx + bw - b, by), (bx + bw, by), (bx + bw, by + b)], fill=accent, width=t)
        draw.line([(bx, by + bh - b), (bx, by + bh), (bx + b, by + bh)], fill=accent, width=t)
        draw.line([(bx + bw, by + bh - b), (bx + bw, by + bh), (bx + bw - b, by + bh)], fill=accent, width=t)

    _corner_brackets(x0, y0, box_w, box_h)

    tx = x0 + pad_x + accent_w + 4
    ty = y0 + pad_y
    draw.text((tx, ty), title, font=font_title, fill=title_c)

    div_y = ty + title_h - 6
    draw.line([(tx, div_y), (x0 + box_w - pad_x, div_y)], fill=divider_c, width=1)
    draw.line([(tx, div_y + 1), (tx + 36, div_y + 1)], fill=accent, width=2)

    ry = div_y + line_gap + 2
    for text in lines:
        draw.text((tx + 1, ry + 1), text, font=font, fill=(20, 30, 45, 200))
        draw.text((tx, ry), text, font=font, fill=text_c)
        ry += line_h + line_gap

    status = "LIVE" if metrics.get("valid") else "STANDBY"
    status_bbox = draw.textbbox((0, 0), status, font=font_title)
    status_w = status_bbox[2] - status_bbox[0]
    sx = x0 + box_w - pad_x - status_w
    sy = y0 + pad_y
    draw.text((sx, sy), status, font=font_title, fill=accent if metrics.get("valid") else divider_c)

    return cv2.cvtColor(np.asarray(pil.convert("RGB")), cv2.COLOR_RGB2BGR)


def _predict_roboflow(model_id, image_bgr, conf=0.25):
    """调用 Roboflow serverless 推理，返回 detections 列表。"""
    api_key = _roboflow_api_key()
    if not api_key:
        raise ValueError("请在后端 .env 配置 ROBOFLOW_API_KEY 后重启服务")
    ok, buf = cv2.imencode(".jpg", image_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        raise ValueError("图片编码失败")
    # Roboflow legacy 模型的 confidence 参数并非 0~1 线性阈值，过高会导致整帧 0 检出；
    # 固定用较低 API 阈值取候选，再按用户 conf(0~1) 在本地过滤。
    sess = _roboflow_http_session()
    resp = sess.post(
        f"https://serverless.roboflow.com/{model_id}",
        params={"api_key": api_key, "confidence": 10, "overlap": 30},
        files={"file": ("frame.jpg", buf.tobytes(), "image/jpeg")},
        timeout=60,
    )
    resp.raise_for_status()
    min_conf = float(conf or 0.25)
    preds = [
        p for p in resp.json().get("predictions", [])
        if float(p.get("confidence", 0) or 0) >= min_conf
    ]
    detections = _roboflow_preds_to_detections(preds)
    h, w = image_bgr.shape[:2]
    if _is_rocket_tracking_model(model_id=model_id):
        detections = _refine_rocket_detect_detections(detections, w, h)
    return detections


def _draw_roboflow_detections(frame, detections):
    canvas = frame.copy()
    for d in detections:
        x1, y1, x2, y2 = [int(v) for v in d["bbox"]]
        name = d.get("className", "unknown")
        if _is_rocket_body_class(name):
            color = _ROBOFLOW_COLORS.get("Rocket Body", (0, 255, 255))
        elif _is_engine_flames_class(name):
            color = _ROBOFLOW_COLORS.get("Engine Flames", (0, 0, 255))
        else:
            color = _ROBOFLOW_COLORS.get(name, (0, 255, 0))
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        label = f"{name} {d.get('confidence', 0):.2f}"
        cv2.putText(canvas, label, (x1, max(16, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    return canvas


def detect_image_roboflow(abs_path, image_bytes, conf=0.25, draw=True, meta=None):
    """Roboflow Universe 模型图片检测（走 serverless API，类别与框坐标准确）。"""
    meta = meta or load_roboflow_meta(abs_path)
    if not meta:
        raise ValueError("缺少 Roboflow 元信息 roboflow_meta.json")
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")
    detections = _predict_roboflow(meta["model_id"], img, conf=conf)
    h, w = img.shape[:2]
    image_b64 = None
    if draw:
        plotted = _draw_roboflow_detections(img, detections)
        ok, buf = cv2.imencode(".jpg", plotted)
        image_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None
    return {
        "detections": detections,
        "count": len(detections),
        "imageBase64": image_b64,
        "width": w,
        "height": h,
    }


def detect_video_roboflow(abs_path, src_path, dst_path, conf=0.25, progress_cb=None, meta=None):
    """Roboflow Universe 模型视频检测（逐帧 serverless 推理 + 画框）。"""
    meta = meta or load_roboflow_meta(abs_path)
    if not meta:
        raise ValueError("缺少 Roboflow 元信息 roboflow_meta.json")
    model_id = meta["model_id"]

    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        raise ValueError("无法打开视频文件")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    writer, ew, eh = _open_h264(dst_path, fps, w, h)
    class_counts = {}
    total_det = 0
    frames = 0
    is_rocket = _is_rocket_tracking_model(model_id=model_id)
    tracker = _RocketTelemetryTracker(w, h, fps) if is_rocket else None
    speed_samples = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            detections = _predict_roboflow(model_id, frame, conf=conf)
            for d in detections:
                name = d["className"]
                class_counts[name] = class_counts.get(name, 0) + 1
                total_det += 1
            if tracker:
                plotted, metrics = _apply_rocket_frame_overlay(frame, detections, tracker, w, h)
                if metrics.get("valid"):
                    speed_samples.append(metrics["descent_speed"])
            else:
                plotted = _draw_roboflow_detections(frame, detections)
            _write_bgr(writer, plotted, ew, eh)
            frames += 1
            if progress_cb:
                progress_cb(frames, total)
    finally:
        cap.release()
        writer.close()

    result = {
        "frames": frames,
        "totalFrames": total,
        "totalDetections": total_det,
        "classCounts": class_counts,
        "fps": round(float(fps), 2),
        "width": ew,
        "height": eh,
    }
    return _attach_rocket_telemetry_stats(result, speed_samples, is_rocket)


def _get_model(abs_path):
    mtime = os.path.getmtime(abs_path)
    with _lock:
        cached = _cache.get(abs_path)
        if cached and cached[0] == mtime:
            return cached[1]
        from ultralytics import YOLO  # 惰性导入
        model = YOLO(abs_path)
        _cache[abs_path] = (mtime, model)
        return model


def _safe_class_name(names, cls_id: int) -> str:
    """稳健获取类别名：异常映射时回退到 classId 字符串。"""
    if isinstance(names, dict):
        return str(names.get(cls_id, cls_id))
    try:
        return str(names[cls_id])
    except Exception:  # noqa: BLE001
        return str(cls_id)


def _safe_plot(result, fallback_frame=None):
    """稳健绘制：类别名映射异常时回退为手工画框。"""
    try:
        return result.plot()
    except Exception:  # noqa: BLE001
        if fallback_frame is None:
            raise
        canvas = fallback_frame.copy()
        boxes = getattr(result, "boxes", None)
        names = getattr(result, "names", None) or {}
        if boxes is None:
            return canvas
        for b in boxes:
            x1, y1, x2, y2 = [int(float(v)) for v in b.xyxy[0].tolist()]
            cid = int(b.cls[0]) if getattr(b, "cls", None) is not None else -1
            conf = float(b.conf[0]) if getattr(b, "conf", None) is not None else 0.0
            label = f"{_safe_class_name(names, cid)} {conf:.2f}"
            cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(canvas, label, (x1, max(16, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
        return canvas


def detect_image(abs_path, image_bytes, conf=0.25, draw=True):
    """对图片字节做检测。

    draw=True  返回带框 jpg(base64)；False 仅返回检测框坐标(实时场景省编码)。
    返回 dict：detections / imageBase64 / width / height。
    """
    meta = load_roboflow_meta(abs_path)
    if meta:
        return detect_image_roboflow(abs_path, image_bytes, conf=conf, draw=draw, meta=meta)
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")

    model = _get_model(abs_path)
    h, w = img.shape[:2]

    results = model.predict(img, conf=conf, verbose=False)
    r = results[0]

    names = getattr(r, "names", None) or getattr(model, "names", None) or {}
    def _class_name(cls_id: int) -> str:
        return _safe_class_name(names, cls_id)

    detections = []
    if r.boxes is not None:
        for b in r.boxes:
            cls_id = int(b.cls[0])
            xyxy = [round(float(v), 1) for v in b.xyxy[0].tolist()]
            detections.append({
                "className": _class_name(cls_id),
                "classId": cls_id,
                "confidence": round(float(b.conf[0]), 4),
                "bbox": xyxy,
            })
    # 有些仓库权重是「图像分类」而不是「目标检测」：此时 r.boxes 为空，但 r.probs 有类别概率。
    # 为了复用现有 UI/报告链路，给全图一个 bbox，把 topK 概率转成 detections。
    if (not detections) and getattr(r, "probs", None) is not None:
        probs = r.probs
        data = getattr(probs, "data", None)
        if data is not None:
            try:
                if hasattr(data, "detach"):
                    data = data.detach().cpu().numpy()
                elif hasattr(data, "cpu"):
                    data = data.cpu().numpy()
                data = np.asarray(data, dtype=np.float32).reshape(-1)
                if data.size > 0:
                    topk = int(min(5, data.shape[0]))
                    idxs = data.argsort()[::-1][:topk]
                    for idx in idxs:
                        c = float(data[int(idx)])
                        if c < float(conf or 0):
                            continue
                        class_id = int(idx)
                        detections.append({
                            "className": _class_name(class_id),
                            "classId": class_id,
                            "confidence": round(c, 4),
                            "bbox": [0.0, 0.0, float(w), float(h)],
                        })
                    # 若阈值太高导致为空，仍保底放 top1，避免后续报告全是空壳
                    if not detections and topk > 0:
                        idx = int(idxs[0])
                        detections.append({
                            "className": _class_name(idx),
                            "classId": idx,
                            "confidence": round(float(data[idx]), 4),
                            "bbox": [0.0, 0.0, float(w), float(h)],
                        })
            except Exception:  # noqa: BLE001
                # 分类解析失败时退回空检测结果（前端会显示尚未检测/风险兜底）
                pass

    image_b64 = None
    if draw:
        plotted = _safe_plot(r, img)  # BGR ndarray，带框（异常类名映射时自动降级）
        ok, buf = cv2.imencode(".jpg", plotted)
        image_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None

    return {
        "detections": detections,
        "count": len(detections),
        "imageBase64": image_b64,
        "width": w,
        "height": h,
    }


def detect_video(abs_path, src_path, dst_path, conf=0.25, progress_cb=None, model_key=None):
    """逐帧检测视频，输出带框视频到 dst_path。

    progress_cb(processed, total) 每帧回调，用于上报进度。
    返回统计：帧数 / 检出目标总数 / 各类别计数 / 分辨率 / fps。
    """
    meta = load_roboflow_meta(abs_path)
    if meta:
        return detect_video_roboflow(abs_path, src_path, dst_path, conf=conf,
                                     progress_cb=progress_cb, meta=meta)
    model = _get_model(abs_path)
    class_names = _model_class_names(model)
    is_rocket = _is_rocket_tracking_model(model_key=model_key, class_names=class_names)

    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        raise ValueError("无法打开视频文件")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    writer, ew, eh = _open_h264(dst_path, fps, w, h)

    class_counts = {}
    total_det = 0
    frames = 0
    tracker = _RocketTelemetryTracker(w, h, fps) if is_rocket else None
    speed_samples = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            r = model.predict(frame, conf=conf, verbose=False)[0]
            if is_rocket:
                detections = _yolo_result_to_detections(r)
                detections = _refine_rocket_detect_detections(detections, w, h)
                for d in detections:
                    name = d["className"]
                    class_counts[name] = class_counts.get(name, 0) + 1
                    total_det += 1
                plotted, metrics = _apply_rocket_frame_overlay(frame, detections, tracker, w, h)
                if metrics.get("valid"):
                    speed_samples.append(metrics["descent_speed"])
            else:
                if r.boxes is not None:
                    names = r.names
                    for b in r.boxes:
                        cid = int(b.cls[0])
                        name = _safe_class_name(names, cid)
                        class_counts[name] = class_counts.get(name, 0) + 1
                        total_det += 1
                plotted = _safe_plot(r, frame)
            _write_bgr(writer, plotted, ew, eh)
            frames += 1
            if progress_cb:
                progress_cb(frames, total)
    finally:
        cap.release()
        writer.close()

    result = {
        "frames": frames,
        "totalFrames": total,
        "totalDetections": total_det,
        "classCounts": class_counts,
        "fps": round(float(fps), 2),
        "width": ew,
        "height": eh,
    }
    return _attach_rocket_telemetry_stats(result, speed_samples, is_rocket)


def estimate_pose(abs_path, image_bytes, conf=0.25, draw=True):
    """YOLO 姿态估计：图片 -> 关键点 + 骨架标注图。

    无人体/非 pose 权重时 keypoints 为 None，返回 count=0、persons=[]、仍出 r.plot() 图。
    """
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")

    model = _get_model(abs_path)
    r = model.predict(img, conf=conf, verbose=False)[0]

    persons = []
    if r.keypoints is not None and r.keypoints.data is not None:
        for kp in r.keypoints.data.cpu().tolist():  # [人][17][x,y,conf]
            pts = [[round(float(x), 1), round(float(y), 1), round(float(c), 4)]
                   for x, y, c in kp]
            persons.append({"keypoints": pts})

    image_b64 = None
    if draw:
        plotted = r.plot()  # BGR，含骨架
        ok, buf = cv2.imencode(".jpg", plotted)
        image_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None

    h, w = img.shape[:2]
    return {
        "count": len(persons),
        "persons": persons,
        "imageBase64": image_b64,
        "width": w,
        "height": h,
    }


def pose_video(abs_path, src_path, dst_path, conf=0.25, progress_cb=None):
    """逐帧姿态估计视频，输出骨架视频到 dst_path。

    progress_cb(processed, total) 每帧回调。返回 帧数 / 总人体数 / 分辨率 / fps。
    """
    model = _get_model(abs_path)

    cap = None
    writer = None
    total_persons = 0
    frames = 0
    try:
        cap = cv2.VideoCapture(src_path)
        if not cap.isOpened():
            raise ValueError("无法打开视频文件")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

        writer, ew, eh = _open_h264(dst_path, fps, w, h)

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            r = model.predict(frame, conf=conf, verbose=False)[0]
            if r.keypoints is not None and r.keypoints.data is not None:
                total_persons += len(r.keypoints.data)
            _write_bgr(writer, r.plot(), ew, eh)
            frames += 1
            if progress_cb:
                progress_cb(frames, total)
    finally:
        if cap is not None:
            cap.release()
        if writer is not None:
            writer.close()

    return {
        "frames": frames,
        "totalFrames": total,
        "totalPersons": total_persons,
        "fps": round(float(fps), 2),
        "width": ew,
        "height": eh,
    }


# ------------------------------------------------------------ rtmlib 姿态（RTMO / RTMPose / DWPose）
_rtmlib_cache = {}       # (onnx_path, mtime, model_key) -> RTMO
_rtmlib_solver_cache = {}  # (variant, mode, device) -> Body | Wholebody

_RTMO_WEIGHT_URLS = {
    "rtmo-s": (
        "https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/"
        "rtmo-s_8xb32-600e_body7-640x640-dac2bf74_20231211.zip"
    ),
    "rtmo-m": (
        "https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/"
        "rtmo-m_16xb16-600e_body7-640x640-39e78cc4_20231211.zip"
    ),
}

_RTMLIB_WEIGHT_URLS = {
    **_RTMO_WEIGHT_URLS,
    "rtmpose-m": (
        "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
        "rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.zip"
    ),
    "rtmpose-l": (
        "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
        "rtmpose-l_simcc-body7_pt-body7_420e-384x288-3f5a1437_20230504.zip"
    ),
    "dwpose-m": (
        "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
        "rtmpose-m_simcc-ucoco_dw-ucoco_270e-256x192-c8b76419_20230728.zip"
    ),
    "dwpose-l": (
        "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
        "rtmpose-l_simcc-ucoco_dw-ucoco_270e-384x288-2438fd99_20230728.zip"
    ),
}


def rtmlib_variant(model_key):
    """按 model_key 判定 rtmlib 变体：rtmo / body(RTMPose) / wholebody(DWPose)。"""
    key = (model_key or "rtmo-s").lower()
    if key.startswith("dwpose"):
        if "-l" in key or "-x" in key:
            mode = "performance"
        elif "-s" in key or "-t" in key:
            mode = "lightweight"
        else:
            mode = "balanced"
        return "wholebody", mode
    if key.startswith("rtmpose"):
        if "-l" in key or "-x" in key:
            mode = "performance"
        elif "-s" in key or "-t" in key:
            mode = "lightweight"
        else:
            mode = "balanced"
        return "body", mode
    if key.startswith("rtmo"):
        return "rtmo", key
    return "rtmo", "rtmo-s"


def rtmlib_keypoint_count(model_key):
    return 133 if rtmlib_variant(model_key)[0] == "wholebody" else 17


def rtmlib_weight_url(model_key):
    key = (model_key or "rtmo-s").lower()
    return _RTMLIB_WEIGHT_URLS.get(key, _RTMO_WEIGHT_URLS["rtmo-s"])


def extract_rtmlib_onnx_from_zip(zip_path):
    """解压 OpenMMLab ONNX SDK zip，提取 end2end.onnx 到同目录。"""
    import shutil
    import zipfile

    zip_path = os.path.abspath(zip_path)
    if not zip_path.lower().endswith(".zip"):
        return zip_path
    if not os.path.isfile(zip_path):
        raise ValueError(f"权重 zip 不存在：{zip_path}")

    model_dir = os.path.dirname(zip_path)
    base = os.path.splitext(os.path.basename(zip_path))[0]
    onnx_out = os.path.join(model_dir, f"{base}.onnx")
    if os.path.isfile(onnx_out) and os.path.getmtime(onnx_out) >= os.path.getmtime(zip_path):
        return onnx_out

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        target = next((n for n in names if n.endswith("end2end.onnx")), None)
        if target is None:
            onnx_names = [n for n in names if n.lower().endswith(".onnx")]
            if not onnx_names:
                raise ValueError(f"zip 内未找到 ONNX 模型：{zip_path}")
            target = onnx_names[0]
        with zf.open(target) as src, open(onnx_out, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return onnx_out


def resolve_rtmlib_onnx(path_or_url=None, model_key="rtmo-s"):
    """URL / 本地 zip / 本地 onnx -> ONNX Runtime 可加载的 .onnx 路径。"""
    if path_or_url and str(path_or_url).startswith(("http://", "https://")):
        from rtmlib.tools.file import download_checkpoint
        downloaded = download_checkpoint(path_or_url)
        if downloaded.lower().endswith(".zip"):
            return extract_rtmlib_onnx_from_zip(downloaded)
        return downloaded

    if path_or_url and os.path.isfile(os.path.abspath(path_or_url)):
        p = os.path.abspath(path_or_url)
        if p.lower().endswith(".zip"):
            return extract_rtmlib_onnx_from_zip(p)
        return p

    from rtmlib.tools.file import download_checkpoint
    downloaded = download_checkpoint(rtmlib_weight_url(model_key))
    if downloaded.lower().endswith(".zip"):
        return extract_rtmlib_onnx_from_zip(downloaded)
    return downloaded


def _rtmlib_device():
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def _get_rtmo_model(abs_weight_path=None, model_key="rtmo-s"):
    """加载 RTMO（rtmlib ONNX），自动解压 zip 为 end2end.onnx。"""
    key = (model_key or "rtmo-s").lower()
    onnx_src = resolve_rtmlib_onnx(abs_weight_path, key)
    mtime = os.path.getmtime(onnx_src) if os.path.isfile(onnx_src) else 0
    cache_key = (onnx_src, mtime, key)
    with _lock:
        if cache_key in _rtmlib_cache:
            return _rtmlib_cache[cache_key]
        from rtmlib import RTMO
        device = _rtmlib_device()
        model = RTMO(onnx_model=onnx_src, backend="onnxruntime", device=device)
        _rtmlib_cache[cache_key] = model
        return model


def infer_pose_rtmo(frame_bgr, model, conf=0.25):
    """RTMO 单帧推理，返回 COCO-17 关键点列表 [[x,y,conf]×17]。"""
    keypoints, scores = model(frame_bgr)
    if keypoints is None or len(keypoints) == 0:
        return []
    persons = []
    for kp, sc in zip(keypoints, scores):
        kp_arr = np.asarray(kp, dtype=np.float32)
        sc_arr = np.asarray(sc, dtype=np.float32).reshape(-1)
        n = min(17, kp_arr.shape[0], sc_arr.shape[0])
        if n < 5:
            continue
        mean_conf = float(np.mean(sc_arr[:n]))
        if mean_conf < conf:
            continue
        persons.append([
            [float(kp_arr[i, 0]), float(kp_arr[i, 1]), float(sc_arr[i])]
            for i in range(n)
        ])
    return persons


def _resolve_rtmlib_pose_path(abs_weight_path):
    """manifest / zip / onnx -> 本地 pose onnx 路径（可选）。"""
    if not abs_weight_path or not os.path.isfile(abs_weight_path):
        return None
    p = os.path.abspath(abs_weight_path)
    if p.lower().endswith(".json"):
        return None
    if p.lower().endswith(".zip"):
        return extract_rtmlib_onnx_from_zip(p)
    if p.lower().endswith(".onnx"):
        return p
    return None


def _rtmlib_storage_dir(abs_weight_path):
    if not abs_weight_path:
        return None
    p = os.path.abspath(abs_weight_path)
    return p if os.path.isdir(p) else os.path.dirname(p)


def _rtmlib_pose_input_size(model_key):
    key = (model_key or "").lower()
    if "-l" in key:
        return (288, 384)
    return (192, 256)


def _find_local_pose_onnx(abs_weight_path):
    """从模型目录定位已拉取的 pose onnx（manifest 旁 zip/onnx）。"""
    pose_path = _resolve_rtmlib_pose_path(abs_weight_path)
    if pose_path:
        return pose_path
    model_dir = _rtmlib_storage_dir(abs_weight_path)
    if not model_dir or not os.path.isdir(model_dir):
        return None
    onnx_files = [
        os.path.join(model_dir, name)
        for name in os.listdir(model_dir)
        if name.lower().endswith(".onnx")
    ]
    if onnx_files:
        onnx_files.sort(key=os.path.getmtime, reverse=True)
        return onnx_files[0]
    zip_files = [
        os.path.join(model_dir, name)
        for name in os.listdir(model_dir)
        if name.lower().endswith(".zip")
    ]
    if zip_files:
        zip_files.sort(key=os.path.getmtime, reverse=True)
        return extract_rtmlib_onnx_from_zip(zip_files[0])
    return None


def _get_rtmlib_solver(model_key="rtmo-s", abs_weight_path=None):
    """加载 rtmlib 求解器：RTMO | Body(RTMPose) | Wholebody(DWPose)。"""
    variant, spec = rtmlib_variant(model_key)
    if variant == "rtmo":
        return _get_rtmo_model(abs_weight_path, spec)

    device = _rtmlib_device()
    backend = "onnxruntime"
    cache_key = (variant, spec, device, abs_weight_path or "")
    with _lock:
        if cache_key in _rtmlib_solver_cache:
            return _rtmlib_solver_cache[cache_key]

        pose_path = _find_local_pose_onnx(abs_weight_path)
        pose_input_size = _rtmlib_pose_input_size(model_key)
        if variant == "body":
            from rtmlib import Body
            if pose_path:
                model = Body(
                    mode=spec, pose=pose_path, pose_input_size=pose_input_size,
                    backend=backend, device=device,
                )
            else:
                model = Body(mode=spec, backend=backend, device=device)
        else:
            from rtmlib import Wholebody
            if pose_path:
                model = Wholebody(
                    mode=spec, pose=pose_path, pose_input_size=pose_input_size,
                    backend=backend, device=device,
                )
            else:
                model = Wholebody(mode=spec, backend=backend, device=device)

        _rtmlib_solver_cache[cache_key] = model
        return model


def _persons_from_rtmlib(keypoints, scores, model_key, conf):
    """rtmlib 输出 -> 平台 persons 列表。"""
    if keypoints is None or len(keypoints) == 0:
        return []
    kp_arr = np.asarray(keypoints, dtype=np.float32)
    sc_arr = np.asarray(scores, dtype=np.float32)
    if kp_arr.ndim == 2:
        kp_arr = kp_arr[np.newaxis, ...]
        sc_arr = sc_arr[np.newaxis, ...]
    n_kp = rtmlib_keypoint_count(model_key)
    persons = []
    for idx in range(kp_arr.shape[0]):
        kp = kp_arr[idx]
        sc = sc_arr[idx].reshape(-1)
        n = min(n_kp, kp.shape[0], sc.shape[0])
        if n < 5:
            continue
        mean_conf = float(np.mean(sc[:n]))
        if mean_conf < conf:
            continue
        pts = [
            [round(float(kp[j, 0]), 1), round(float(kp[j, 1]), 1), round(float(sc[j]), 4)]
            for j in range(n)
        ]
        item = {"keypoints": pts}
        if n_kp == 133:
            item["keypointCount"] = 133
        persons.append(item)
    return persons


def _draw_rtmlib_skeleton(img_bgr, keypoints, scores, conf):
    """rtmlib 骨架绘制（兼容 to_openpose / openpose_skeleton 参数名差异）。"""
    if keypoints is None or len(keypoints) == 0:
        return img_bgr
    from rtmlib import draw_skeleton
    import inspect

    kp = np.asarray(keypoints, dtype=np.float32)
    sc = np.asarray(scores, dtype=np.float32)
    if kp.ndim == 2:
        kp = kp[np.newaxis, ...]
        sc = sc[np.newaxis, ...]

    params = inspect.signature(draw_skeleton).parameters
    kwargs = {"kpt_thr": conf}
    if "openpose_skeleton" in params:
        kwargs["openpose_skeleton"] = False
    elif "to_openpose" in params:
        kwargs["to_openpose"] = False
    return draw_skeleton(img_bgr, kp, sc, **kwargs)


def infer_pose_rtmlib_frame(frame_bgr, model, model_key, conf=0.25):
    """rtmlib 单帧推理，返回 COCO-17 关键点（全身模型取 body 前 17 点）。"""
    variant, _ = rtmlib_variant(model_key)
    if variant == "rtmo":
        return infer_pose_rtmo(frame_bgr, model, conf=conf)
    keypoints, scores = model(frame_bgr)
    persons = _persons_from_rtmlib(keypoints, scores, model_key, conf)
    return [p["keypoints"][:17] for p in persons]


def write_rtmlib_manifest(folder, model_key):
    """写入 rtmlib 就绪标记（RTMPose/DWPose 两阶段模型）。"""
    import json
    variant, mode = rtmlib_variant(model_key)
    os.makedirs(folder, exist_ok=True)
    manifest = os.path.join(folder, "rtmlib_manifest.json")
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump({
            "variant": variant, "mode": mode, "modelKey": model_key, "ready": True,
        }, f, ensure_ascii=False)
    return manifest


def estimate_pose_rtmlib(model_key, abs_weight_path, image_bytes, conf=0.25, draw=True):
    """rtmlib 姿态估计：图片 -> 关键点 + 骨架图（COCO-17 或 WholeBody-133）。"""
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")

    solver = _get_rtmlib_solver(model_key, abs_weight_path)
    variant, _ = rtmlib_variant(model_key)
    if variant == "rtmo":
        persons_kp = infer_pose_rtmo(img, solver, conf=conf)
        persons = [{"keypoints": kp} for kp in persons_kp]
        keypoints, scores = solver(img)
    else:
        keypoints, scores = solver(img)
        persons = _persons_from_rtmlib(keypoints, scores, model_key, conf)

    image_b64 = None
    if draw and persons:
        if keypoints is not None and len(keypoints):
            plotted = _draw_rtmlib_skeleton(img.copy(), keypoints, scores, conf)
        else:
            plotted = img.copy()
        ok, buf = cv2.imencode(".jpg", plotted)
        image_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None

    h, w = img.shape[:2]
    kp_count = rtmlib_keypoint_count(model_key)
    return {
        "count": len(persons),
        "persons": persons,
        "imageBase64": image_b64,
        "width": w,
        "height": h,
        "keypointCount": kp_count,
        "poseType": "wholebody" if variant == "wholebody" else "body17",
    }


def pose_video_rtmlib(model_key, abs_weight_path, src_path, dst_path, conf=0.25, progress_cb=None):
    """rtmlib 逐帧姿态视频（RTMO / RTMPose / DWPose）。"""
    solver = _get_rtmlib_solver(model_key, abs_weight_path)
    variant, _ = rtmlib_variant(model_key)

    cap = None
    writer = None
    total_persons = 0
    frames = 0
    try:
        cap = cv2.VideoCapture(src_path)
        if not cap.isOpened():
            raise ValueError("无法打开视频文件")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

        writer, ew, eh = _open_h264(dst_path, fps, w, h)

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if variant == "rtmo":
                persons_kp = infer_pose_rtmo(frame, solver, conf=conf)
                total_persons += len(persons_kp)
                keypoints, scores = solver(frame)
            else:
                keypoints, scores = solver(frame)
                persons = _persons_from_rtmlib(keypoints, scores, model_key, conf)
                total_persons += len(persons)

            if keypoints is not None and len(keypoints):
                plotted = _draw_rtmlib_skeleton(frame, keypoints, scores, conf)
            else:
                plotted = frame
            _write_bgr(writer, plotted, ew, eh)
            frames += 1
            if progress_cb:
                progress_cb(frames, total)
    finally:
        if cap is not None:
            cap.release()
        if writer is not None:
            writer.close()

    return {
        "frames": frames,
        "totalFrames": total,
        "totalPersons": total_persons,
        "fps": round(float(fps), 2),
        "width": ew,
        "height": eh,
        "keypointCount": rtmlib_keypoint_count(model_key),
        "poseType": "wholebody" if variant == "wholebody" else "body17",
    }


def track_video(abs_path, src_path, dst_path, conf=0.25, imgsz=640, line=None,
                progress_cb=None):
    """YOLO + ByteTrack 逐帧追踪，输出带框+ID 视频。

    line: 归一化 [x1,y1,x2,y2]（0–1）或 None。非 None 时统计越线进/出。
    返回统计：帧数 / 唯一目标数 / 各类别去重计数 / 越线 {in,out,total} 或 None。
    """
    model = _get_model(abs_path)

    cap = None
    writer = None
    try:
        cap = cv2.VideoCapture(src_path)
        if not cap.isOpened():
            raise ValueError("无法打开视频文件")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

        writer, ew, eh = _open_h264(dst_path, fps, w, h)

        px_line = None
        crossing = None
        if line and len(line) == 4:
            px_line = [line[0] * w, line[1] * h, line[2] * w, line[3] * h]
            crossing = {"in": 0, "out": 0, "total": 0}

        seen_ids = set()
        class_ids = {}            # className -> set(track_id)
        last_centroid = {}        # track_id -> (cx, cy)
        counted = set()           # (track_id, direction) 去抖
        frames = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            r = model.track(frame, persist=True, tracker="bytetrack.yaml",
                            conf=conf, imgsz=imgsz, verbose=False)[0]
            if r.boxes is not None and r.boxes.id is not None:
                names = r.names
                ids = r.boxes.id.int().tolist()
                clss = r.boxes.cls.int().tolist()
                xyxy = r.boxes.xyxy.cpu().tolist()
                for tid, cid, box in zip(ids, clss, xyxy):
                    seen_ids.add(tid)
                    name = names.get(cid, str(cid))
                    class_ids.setdefault(name, set()).add(tid)
                    if px_line is not None:
                        cx = (box[0] + box[2]) / 2.0
                        cy = (box[1] + box[3]) / 2.0
                        prev = last_centroid.get(tid)
                        if prev is not None:
                            d = _crosses(prev, (cx, cy), px_line)
                            if d != 0 and (tid, d) not in counted:
                                counted.add((tid, d))
                                if d > 0:
                                    crossing["in"] += 1
                                else:
                                    crossing["out"] += 1
                                crossing["total"] = crossing["in"] + crossing["out"]
                        last_centroid[tid] = (cx, cy)

            annotated = r.plot()  # BGR，带框+ID
            if px_line is not None:
                p1 = (int(px_line[0]), int(px_line[1]))
                p2 = (int(px_line[2]), int(px_line[3]))
                cv2.line(annotated, p1, p2, (0, 0, 255), 2)
                cv2.putText(annotated, f"IN:{crossing['in']} OUT:{crossing['out']}",
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2,
                            cv2.LINE_AA)
            _write_bgr(writer, annotated, ew, eh)
            frames += 1
            if progress_cb:
                progress_cb(frames, total)
    finally:
        if cap is not None:
            cap.release()
        if writer is not None:
            writer.close()

    return {
        "frames": frames,
        "totalFrames": total,
        "fps": round(float(fps), 2),
        "width": ew,
        "height": eh,
        "uniqueObjects": len(seen_ids),
        "classCounts": {name: len(idset) for name, idset in class_ids.items()},
        "crossing": crossing,
    }


def track_frame(abs_path, image_bytes, conf=0.25, reset=False):
    """单帧追踪（摄像头实时）：返回 检测框 + 轨迹ID（不画图，前端叠画）。

    reset=True（会话首帧）用 persist=False 重置跟踪器/ID；之后 persist=True 续追。
    """
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")
    model = _get_model(abs_path)
    r = model.track(img, persist=not reset, tracker="bytetrack.yaml",
                    conf=conf, verbose=False)[0]
    names = r.names
    detections = []
    if r.boxes is not None:
        ids = (r.boxes.id.int().tolist()
               if r.boxes.id is not None else [None] * len(r.boxes))
        for b, tid in zip(r.boxes, ids):
            cid = int(b.cls[0])
            detections.append({
                "className": names.get(cid, str(cid)),
                "classId": cid,
                "confidence": round(float(b.conf[0]), 4),
                "bbox": [round(float(v), 1) for v in b.xyxy[0].tolist()],
                "trackId": tid,
            })
    h, w = img.shape[:2]
    return {"detections": detections, "width": w, "height": h}


# ------------------------------------------------------------ transformers 文本任务
def _get_pipeline(task, model_dir):
    key = (task, model_dir)
    with _lock:
        if key in _pipe_cache:
            return _pipe_cache[key]
        from transformers import pipeline  # 惰性导入
        pipe = pipeline(task, model=model_dir, tokenizer=model_dir, top_k=None)
        _pipe_cache[key] = pipe
        return pipe


def classify_text(model_dir, text, task="text-classification"):
    """transformers 文本分类（如 FinBERT 情感分析）。

    返回 dict：results=[{label, score}] 按分数降序，top=最高项。
    """
    pipe = _get_pipeline(task, model_dir)
    out = pipe(text)
    # 单条输入 top_k=None -> list[{label,score}]；个别版本套一层 -> list[list[...]]
    rows = out[0] if (out and isinstance(out[0], list)) else out
    results = sorted(
        [{"label": r["label"], "score": round(float(r["score"]), 4)} for r in rows],
        key=lambda x: -x["score"],
    )
    return {"results": results, "top": results[0] if results else None}


# ------------------------------------------------------------ transformers 图像任务
def _get_img_pipeline(task, model_dir):
    """图像任务 pipeline（object-detection / image-classification），按 (task,dir) 缓存。"""
    key = (task, model_dir)
    with _lock:
        if key in _pipe_cache:
            return _pipe_cache[key]
        from transformers import pipeline  # 惰性导入
        pipe = pipeline(task, model=model_dir)
        _pipe_cache[key] = pipe
        return pipe


_DET_COLORS = [(103, 194, 58), (255, 158, 64), (35, 162, 230), (212, 64, 64),
               (222, 84, 222), (194, 195, 19), (140, 90, 213)]  # BGR


def _draw_dets(img, dets):
    """在 BGR 图上画检测框 + 标签（transformers 检测无 r.plot()，手动画）。"""
    for d in dets:
        x1, y1, x2, y2 = [int(v) for v in d["bbox"]]
        c = _DET_COLORS[d["classId"] % len(_DET_COLORS)]
        cv2.rectangle(img, (x1, y1), (x2, y2), c, 2)
        label = f"{d['className']} {d['confidence'] * 100:.0f}%"
        cv2.putText(img, label, (x1, max(12, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 1, cv2.LINE_AA)


def _hf_detect(pipe, pil, conf):
    """跑一次 transformers 目标检测，返回标准化 detections 列表。"""
    out = pipe(pil, threshold=conf)
    label2id = getattr(pipe.model.config, "label2id", {}) or {}
    dets = []
    for o in out:
        b = o["box"]
        dets.append({
            "className": o["label"],
            "classId": int(label2id.get(o["label"], 0)),
            "confidence": round(float(o["score"]), 4),
            "bbox": [round(float(b["xmin"]), 1), round(float(b["ymin"]), 1),
                     round(float(b["xmax"]), 1), round(float(b["ymax"]), 1)],
        })
    return dets


def detect_image_hf(model_dir, image_bytes, conf=0.25, draw=True, task="object-detection"):
    """transformers 目标检测（DETR/RT-DETR/YOLOS 等），输出与 YOLO 同格式。"""
    from PIL import Image
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # BGR
    if img is None:
        raise ValueError("无法解析图片")
    pipe = _get_img_pipeline(task, model_dir)
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    detections = _hf_detect(pipe, pil, conf)

    image_b64 = None
    if draw:
        _draw_dets(img, detections)
        ok, buf = cv2.imencode(".jpg", img)
        image_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None

    h, w = img.shape[:2]
    return {"detections": detections, "count": len(detections),
            "imageBase64": image_b64, "width": w, "height": h}


def detect_video_hf(model_dir, src_path, dst_path, conf=0.25, task="object-detection", progress_cb=None):
    """transformers 目标检测逐帧处理视频。progress_cb(processed, total) 上报进度。"""
    from PIL import Image
    pipe = _get_img_pipeline(task, model_dir)

    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        raise ValueError("无法打开视频文件")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    writer, ew, eh = _open_h264(dst_path, fps, w, h)

    class_counts, total_det, frames = {}, 0, 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            dets = _hf_detect(pipe, pil, conf)
            for d in dets:
                class_counts[d["className"]] = class_counts.get(d["className"], 0) + 1
                total_det += 1
            _draw_dets(frame, dets)
            _write_bgr(writer, frame, ew, eh)
            frames += 1
            if progress_cb:
                progress_cb(frames, total)
    finally:
        cap.release()
        writer.close()

    return {"frames": frames, "totalFrames": total, "totalDetections": total_det,
            "classCounts": class_counts, "fps": round(float(fps), 2), "width": ew, "height": eh}


# ------------------------------------------------------------ RF-DETR 目标检测（Roboflow rfdetr 包）
_rfdetr_cache = {}

_RFDETR_CLASS = {
    "rf-detr-nano": "RFDETRNano",
    "rf-detr-small": "RFDETRSmall",
    "rf-detr-medium": "RFDETRMedium",
    "rf-detr-large": "RFDETRLarge",
}

_RFDETR_WEIGHT = {
    "rf-detr-nano": "rf-detr-nano.pth",
    "rf-detr-small": "rf-detr-small.pth",
    "rf-detr-medium": "rf-detr-medium.pth",
    "rf-detr-large": "rf-detr-large-2026.pth",
}

_RFDETR_SEG_CLASS = {
    "rf-detr-seg-nano": "RFDETRSegNano",
    "rf-detr-seg-small": "RFDETRSegSmall",
    "rf-detr-seg-medium": "RFDETRSegMedium",
    "rf-detr-seg-large": "RFDETRSegLarge",
    "rf-detr-seg-xl": "RFDETRSegXLarge",
    "rf-detr-seg-xlarge": "RFDETRSegXLarge",
    "rf-detr-seg-2xl": "RFDETRSeg2XLarge",
    "rf-detr-seg-xxlarge": "RFDETRSeg2XLarge",
}

_RFDETR_SEG_WEIGHT = {
    "rf-detr-seg-nano": "rf-detr-seg-nano.pt",
    "rf-detr-seg-small": "rf-detr-seg-small.pt",
    "rf-detr-seg-medium": "rf-detr-seg-medium.pt",
    "rf-detr-seg-large": "rf-detr-seg-large.pt",
    "rf-detr-seg-xl": "rf-detr-seg-xlarge.pt",
    "rf-detr-seg-xlarge": "rf-detr-seg-xlarge.pt",
    "rf-detr-seg-2xl": "rf-detr-seg-xxlarge.pt",
    "rf-detr-seg-xxlarge": "rf-detr-seg-xxlarge.pt",
}


def rfdetr_weight_filename(model_key):
    """model_key -> 官方预训练权重文件名（检测或分割）。"""
    key = (model_key or "rf-detr-medium").lower()
    if key in _RFDETR_SEG_WEIGHT:
        return _RFDETR_SEG_WEIGHT[key]
    if "seg" in key:
        return "rf-detr-seg-medium.pt"
    return _RFDETR_WEIGHT.get(key, "rf-detr-medium.pth")


def _get_rfdetr_model(abs_weight_path, model_key="rf-detr-medium"):
    mtime = os.path.getmtime(abs_weight_path)
    cache_key = (abs_weight_path, mtime, model_key)
    with _lock:
        if cache_key in _rfdetr_cache:
            return _rfdetr_cache[cache_key]
        import importlib
        from rfdetr.assets.coco_classes import COCO_CLASS_NAMES
        cls_name = _RFDETR_CLASS.get((model_key or "rf-detr-medium").lower(), "RFDETRMedium")
        rfdetr_mod = importlib.import_module("rfdetr")
        cls = getattr(rfdetr_mod, cls_name)
        model = cls(pretrain_weights=abs_weight_path)
        names = list(COCO_CLASS_NAMES)
        _rfdetr_cache[cache_key] = (model, names)
        return _rfdetr_cache[cache_key]


def _rfdetr_resolve_class_name(sv_det, index, cid, class_names):
    """解析 RF-DETR 类别名。COCO 预训练模型 class_id 为 COCO 官方 cat id（1=person），非 0 索引。"""
    data = getattr(sv_det, "data", None) or {}
    names = data.get("class_name")
    if names is not None and index < len(names):
        n = names[index]
        if n:
            return str(n)
    try:
        from rfdetr.assets.coco_classes import COCO_CLASSES
        if int(cid) in COCO_CLASSES:
            return COCO_CLASSES[int(cid)]
    except ImportError:
        pass
    cid = int(cid)
    if 0 <= cid < len(class_names):
        return class_names[cid]
    return str(cid)


def _rfdetr_to_detections(sv_det, class_names):
    dets = []
    if sv_det is None or len(sv_det) == 0:
        return dets
    for i in range(len(sv_det)):
        x1, y1, x2, y2 = sv_det.xyxy[i]
        cid = int(sv_det.class_id[i])
        cname = _rfdetr_resolve_class_name(sv_det, i, cid, class_names)
        dets.append({
            "className": cname,
            "classId": cid,
            "confidence": round(float(sv_det.confidence[i]), 4),
            "bbox": [round(float(x1), 1), round(float(y1), 1),
                     round(float(x2), 1), round(float(y2), 1)],
        })
    return dets


def detect_image_rfdetr(abs_path, image_bytes, conf=0.25, draw=True, model_key="rf-detr-medium"):
    """RF-DETR 图片检测（Roboflow/rf-detr-medium 等），输出格式与 YOLO 一致。"""
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")
    model, class_names = _get_rfdetr_model(abs_path, model_key)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    sv_det = model.predict(rgb, threshold=conf)
    detections = _rfdetr_to_detections(sv_det, class_names)
    if draw:
        _draw_dets(img, detections)
        ok, buf = cv2.imencode(".jpg", img)
        image_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None
    else:
        image_b64 = None
    h, w = img.shape[:2]
    return {"detections": detections, "count": len(detections),
            "imageBase64": image_b64, "width": w, "height": h}


def detect_video_rfdetr(abs_path, src_path, dst_path, conf=0.25, model_key="rf-detr-medium", progress_cb=None):
    """RF-DETR 逐帧视频检测。"""
    model, class_names = _get_rfdetr_model(abs_path, model_key)
    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        raise ValueError("无法打开视频文件")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    writer, ew, eh = _open_h264(dst_path, fps, w, h)
    class_counts, total_det, frames = {}, 0, 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            sv_det = model.predict(rgb, threshold=conf)
            dets = _rfdetr_to_detections(sv_det, class_names)
            for d in dets:
                class_counts[d["className"]] = class_counts.get(d["className"], 0) + 1
                total_det += 1
            _draw_dets(frame, dets)
            _write_bgr(writer, frame, ew, eh)
            frames += 1
            if progress_cb:
                progress_cb(frames, total)
    finally:
        cap.release()
        writer.close()
    return {"frames": frames, "totalFrames": total, "totalDetections": total_det,
            "classCounts": class_counts, "fps": round(float(fps), 2), "width": ew, "height": eh}


def _encode_mask_b64(mask):
    """bool/uint8 (H,W) -> PNG base64。"""
    if mask is None:
        return None
    m = (mask.astype(np.uint8) * 255) if mask.dtype == bool else mask.astype(np.uint8)
    ok, buf = cv2.imencode(".png", m)
    return base64.b64encode(buf.tobytes()).decode() if ok else None


def _decode_mask_b64(b64):
    """PNG base64 -> bool (H,W)。"""
    arr = np.frombuffer(base64.b64decode(b64), np.uint8)
    gray = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    return gray > 127 if gray is not None else None


def _get_rfdetr_seg_model(abs_weight_path, model_key="rf-detr-seg-medium"):
    mtime = os.path.getmtime(abs_weight_path)
    cache_key = ("seg", abs_weight_path, mtime, model_key)
    with _lock:
        if cache_key in _rfdetr_cache:
            return _rfdetr_cache[cache_key]
        import importlib
        from rfdetr.assets.coco_classes import COCO_CLASS_NAMES
        key = (model_key or "rf-detr-seg-medium").lower()
        cls_name = _RFDETR_SEG_CLASS.get(key, "RFDETRSegMedium")
        rfdetr_mod = importlib.import_module("rfdetr")
        cls = getattr(rfdetr_mod, cls_name)
        model = cls(pretrain_weights=abs_weight_path)
        names = list(COCO_CLASS_NAMES)
        _rfdetr_cache[cache_key] = (model, names)
        return _rfdetr_cache[cache_key]


def _rfdetr_to_segmentations(sv_det, class_names, include_mask=True):
    """RF-DETR-Seg supervision.Detections -> 带 mask 的分割结果列表。"""
    dets = []
    if sv_det is None or len(sv_det) == 0:
        return dets
    masks = getattr(sv_det, "mask", None)
    for i in range(len(sv_det)):
        x1, y1, x2, y2 = sv_det.xyxy[i]
        cid = int(sv_det.class_id[i])
        cname = _rfdetr_resolve_class_name(sv_det, i, cid, class_names)
        item = {
            "className": cname,
            "classId": cid,
            "confidence": round(float(sv_det.confidence[i]), 4),
            "bbox": [round(float(x1), 1), round(float(y1), 1),
                     round(float(x2), 1), round(float(y2), 1)],
        }
        if include_mask and masks is not None:
            item["maskBase64"] = _encode_mask_b64(masks[i])
        dets.append(item)
    return dets


def _annotate_sv_segmentation(img_bgr, sv_det, labels):
    """supervision 实例分割可视化（mask + 框 + 标签）。"""
    import supervision as sv
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    out = rgb.copy()
    if getattr(sv_det, "mask", None) is not None:
        out = sv.MaskAnnotator().annotate(out, sv_det)
    out = sv.BoxAnnotator().annotate(out, sv_det)
    if labels:
        out = sv.LabelAnnotator().annotate(out, sv_det, labels)
    return cv2.cvtColor(out, cv2.COLOR_RGB2BGR)


def _blend_mask_detections(img_bgr, detections, alpha=0.45):
    """按 detections[].maskBase64 半透明叠色。"""
    out = img_bgr.copy()
    for i, d in enumerate(detections):
        b64 = d.get("maskBase64")
        if not b64:
            continue
        mask = _decode_mask_b64(b64)
        if mask is None or not mask.any():
            continue
        if mask.shape[:2] != out.shape[:2]:
            mask = cv2.resize(mask.astype(np.uint8), (out.shape[1], out.shape[0]),
                              interpolation=cv2.INTER_NEAREST).astype(bool)
        color = np.array(_DET_COLORS[i % len(_DET_COLORS)], dtype=np.float32)
        region = mask
        out[region] = (out[region].astype(np.float32) * (1 - alpha) + color * alpha).astype(np.uint8)
    return out


def segment_image_rfdetr(abs_path, image_bytes, conf=0.25, draw=True, model_key="rf-detr-seg-medium"):
    """RF-DETR-Seg 图片实例分割。"""
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")
    model, class_names = _get_rfdetr_seg_model(abs_path, model_key)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    sv_det = model.predict(rgb, threshold=conf)
    detections = _rfdetr_to_segmentations(sv_det, class_names)
    image_b64 = None
    if draw:
        labels = [d["className"] for d in detections]
        plotted = _annotate_sv_segmentation(img, sv_det, labels)
        ok, buf = cv2.imencode(".jpg", plotted)
        image_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None
    h, w = img.shape[:2]
    return {"detections": detections, "count": len(detections),
            "imageBase64": image_b64, "width": w, "height": h}


def segment_video_rfdetr(abs_path, src_path, dst_path, conf=0.25, model_key="rf-detr-seg-medium",
                         progress_cb=None):
    """RF-DETR-Seg 逐帧视频实例分割。"""
    model, class_names = _get_rfdetr_seg_model(abs_path, model_key)
    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        raise ValueError("无法打开视频文件")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    writer, ew, eh = _open_h264(dst_path, fps, w, h)
    class_counts, total_det, frames = {}, 0, 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            sv_det = model.predict(rgb, threshold=conf)
            dets = _rfdetr_to_segmentations(sv_det, class_names, include_mask=False)
            for d in dets:
                class_counts[d["className"]] = class_counts.get(d["className"], 0) + 1
                total_det += 1
            labels = [d["className"] for d in dets]
            frame = _annotate_sv_segmentation(frame, sv_det, labels)
            _write_bgr(writer, frame, ew, eh)
            frames += 1
            if progress_cb:
                progress_cb(frames, total)
    finally:
        cap.release()
        writer.close()
    return {"frames": frames, "totalFrames": total, "totalDetections": total_det,
            "classCounts": class_counts, "fps": round(float(fps), 2), "width": ew, "height": eh}


# ------------------------------------------------------------ MobileSAM 交互式分割
_mobilesam_cache = {}  # abs_path -> (mtime, SamPredictor)


def _mobilesam_device():
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def _get_mobile_sam_predictor(abs_weight_path):
    mtime = os.path.getmtime(abs_weight_path)
    with _lock:
        cached = _mobilesam_cache.get(abs_weight_path)
        if cached and cached[0] == mtime:
            return cached[1]
        import torch
        from mobile_sam import sam_model_registry, SamPredictor
        device = _mobilesam_device()
        sam = sam_model_registry["vit_t"](checkpoint=abs_weight_path)
        sam.to(device=device)
        sam.eval()
        predictor = SamPredictor(sam)
        _mobilesam_cache[abs_weight_path] = (mtime, predictor)
        return predictor


def segment_image_mobilesam(abs_path, image_bytes, points=None, point_labels=None, box=None,
                            mode="prompt", draw=True):
    """MobileSAM 图片分割。mode=prompt 需点/框；mode=auto 全自动分割全图。"""
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = img.shape[:2]
    detections = []

    if mode == "auto":
        from mobile_sam import SamAutomaticMaskGenerator
        predictor = _get_mobile_sam_predictor(abs_path)
        gen = SamAutomaticMaskGenerator(
            predictor.model, points_per_side=16, pred_iou_thresh=0.86,
            stability_score_thresh=0.92, min_mask_region_area=100)
        masks = gen.generate(rgb)
        masks = sorted(masks, key=lambda x: -x.get("area", 0))[:40]
        for i, m in enumerate(masks):
            seg = m["segmentation"]
            bx, by, bw, bh = m.get("bbox", [0, 0, w, h])
            detections.append({
                "className": f"region_{i + 1}",
                "classId": i,
                "confidence": round(float(m.get("predicted_iou", 0.9)), 4),
                "bbox": [round(float(bx), 1), round(float(by), 1),
                         round(float(bx + bw), 1), round(float(by + bh), 1)],
                "maskBase64": _encode_mask_b64(seg),
            })
    else:
        if not points and not box:
            raise ValueError("交互分割请提供点击坐标 points 或框选 box")
        predictor = _get_mobile_sam_predictor(abs_path)
        predictor.set_image(rgb)
        pt_coords = np.array(points, dtype=np.float32) if points else None
        pt_labels = np.array(point_labels, dtype=np.int32) if point_labels else None
        box_arr = np.array(box, dtype=np.float32) if box else None
        masks, scores, _ = predictor.predict(
            point_coords=pt_coords,
            point_labels=pt_labels,
            box=box_arr,
            multimask_output=not box_arr,
        )
        best = int(np.argmax(scores))
        mask = masks[best]
        ys, xs = np.where(mask)
        if len(xs):
            bbox = [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
        else:
            bbox = [0.0, 0.0, 0.0, 0.0]
        detections.append({
            "className": "segment",
            "classId": 0,
            "confidence": round(float(scores[best]), 4),
            "bbox": [round(v, 1) for v in bbox],
            "maskBase64": _encode_mask_b64(mask),
        })

    image_b64 = None
    if draw:
        plotted = _blend_mask_detections(img, detections)
        ok, buf = cv2.imencode(".jpg", plotted)
        image_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None
    return {"detections": detections, "count": len(detections),
            "imageBase64": image_b64, "width": w, "height": h}


def classify_image(model_dir, image_bytes, task="image-classification", top_k=5):
    """transformers 图像分类，返回 results=[{label, score}] 降序 + top。"""
    from PIL import Image
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")
    pipe = _get_img_pipeline(task, model_dir)
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    out = pipe(pil, top_k=top_k)
    results = [{"label": o["label"], "score": round(float(o["score"]), 4)} for o in out]
    return {"results": results, "top": results[0] if results else None}


# ------------------------------------------------------------ transformers 其它 NLP 任务
def _get_text_pipeline(task, model_dir, **kwargs):
    """通用文本任务 pipeline，按 (task, dir, kwargs) 缓存。"""
    key = (task, model_dir, tuple(sorted(kwargs.items())))
    with _lock:
        if key in _pipe_cache:
            return _pipe_cache[key]
        from transformers import pipeline  # 惰性导入
        pipe = pipeline(task, model=model_dir, tokenizer=model_dir, **kwargs)
        _pipe_cache[key] = pipe
        return pipe


def generate_text(model_dir, text, task="summarization", max_new_tokens=256):
    """文本进文本出：翻译 / 摘要 / 文本生成。返回 {text}。"""
    pipe = _get_text_pipeline(task, model_dir)
    if task == "text-generation":
        out = pipe(text, max_new_tokens=max_new_tokens, return_full_text=False)
        return {"text": out[0]["generated_text"]}
    out = pipe(text)
    o = out[0]
    txt = o.get("translation_text") or o.get("summary_text") or o.get("generated_text") or ""
    return {"text": txt}


def zero_shot(model_dir, text, labels, task="zero-shot-classification"):
    """零样本分类：给定候选标签，输出各标签分数。"""
    pipe = _get_text_pipeline(task, model_dir)
    out = pipe(text, candidate_labels=labels)
    results = [{"label": l, "score": round(float(s), 4)} for l, s in zip(out["labels"], out["scores"])]
    return {"results": results, "top": results[0] if results else None}


def fill_mask(model_dir, text, task="fill-mask", top_k=5):
    """完形填空：预测 [MASK] 处候选词。"""
    pipe = _get_text_pipeline(task, model_dir)
    out = pipe(text, top_k=top_k)
    results = [{"label": o["token_str"].strip(), "score": round(float(o["score"]), 4),
                "sequence": o.get("sequence", "")} for o in out]
    return {"results": results, "top": results[0] if results else None}


def extract_entities(model_dir, text, task="token-classification"):
    """命名实体识别(NER)：返回实体跨度。"""
    pipe = _get_text_pipeline(task, model_dir, aggregation_strategy="simple")
    out = pipe(text)
    entities = [{"word": o["word"], "entityGroup": o.get("entity_group") or o.get("entity"),
                 "score": round(float(o["score"]), 4), "start": int(o["start"]), "end": int(o["end"])}
                for o in out]
    return {"text": text, "entities": entities}


def answer_question(model_dir, question, context, task="question-answering"):
    """抽取式问答：从 context 中找答案片段。"""
    pipe = _get_text_pipeline(task, model_dir)
    out = pipe(question=question, context=context)
    return {"answer": out["answer"], "score": round(float(out["score"]), 4),
            "start": int(out["start"]), "end": int(out["end"])}


# ------------------------------------------------------------ funasr 语音识别（SenseVoice）
_funasr_cache = {}  # model_dir -> funasr AutoModel

# SenseVoice 富文本里的标签 -> 中文（语言 / 情感 / 音频事件）
_LANG_CN = {"zh": "中文", "en": "英文", "yue": "粤语", "ja": "日语", "ko": "韩语", "nospeech": "无语音"}
_EMO_CN = {"HAPPY": "开心", "SAD": "悲伤", "ANGRY": "愤怒", "NEUTRAL": "中性",
           "FEARFUL": "恐惧", "DISGUSTED": "厌恶", "SURPRISED": "惊讶"}
_EVENT_CN = {"Speech": "说话", "BGM": "背景音乐", "Applause": "掌声", "Laughter": "笑声",
             "Cry": "哭声", "Sneeze": "喷嚏", "Breath": "呼吸", "Cough": "咳嗽"}


def _get_funasr(model_dir):
    """加载/缓存 funasr SenseVoice 模型。

    funasr-native 仓库(如 ModelScope iic/SenseVoiceSmall)无需 remote_code；
    HF FunAudioLLM 镜像带 model.py 则用 trust_remote_code 加载。
    """
    with _lock:
        if model_dir in _funasr_cache:
            return _funasr_cache[model_dir]
        from funasr import AutoModel  # 惰性导入
        kwargs = dict(model=model_dir, disable_update=True, device="cpu")
        model_py = os.path.join(model_dir, "model.py")
        if os.path.isfile(model_py):
            kwargs.update(trust_remote_code=True, remote_code=model_py)
        model = AutoModel(**kwargs)
        _funasr_cache[model_dir] = model
        return model


def transcribe_audio(model_dir, audio_path):
    """SenseVoice / Paraformer 等 funasr 语音识别：转写 + 语言/情感/音频事件标签。

    返回 {text, language, emotion, events}。
    """
    model = _get_funasr(model_dir)
    res = model.generate(input=audio_path, cache={}, language="auto",
                         use_itn=True, batch_size_s=60)
    raw = res[0]["text"] if res else ""
    return _parse_sensevoice_rich(raw)


# ------------------------------------------------------------ Fun-ASR-Nano（通义 LLM-ASR，纯 CPU）
_funasr_nano_cache = {}  # model_dir -> funasr AutoModel

_NANO_LANG = {
    "auto": "auto", "zh": "中文", "中文": "中文", "cn": "中文",
    "en": "英文", "英文": "英文", "english": "英文",
    "ja": "日文", "日文": "日文", "japanese": "日文",
}


_FUNASR_NANO_MODEL_PY_URL = (
    "https://raw.githubusercontent.com/FunAudioLLM/Fun-ASR/main/model.py"
)


def _ensure_funasr_nano_remote_code(model_dir):
    """ModelScope/HF 权重仓不含 model.py；优先使用 funasr 内置 FunASRNano，否则拉取官方 remote code。

    Returns:
        model_py 路径（若需 trust_remote_code），或 None（使用内置类）。
    """
    model_py = os.path.join(model_dir, "model.py")
    if os.path.isfile(model_py):
        return model_py
    try:
        from funasr.register import tables
        if "FunASRNano" in (tables.model_classes or {}):
            return None  # funasr>=1.2 已注册，无需 model.py
    except Exception:  # noqa: BLE001
        pass
    # 兜底：从 Fun-ASR 仓库下载 remote code
    try:
        import urllib.request
        urllib.request.urlretrieve(_FUNASR_NANO_MODEL_PY_URL, model_py)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Fun-ASR-Nano 缺少 model.py，且自动下载失败。"
            f"请手动保存 {_FUNASR_NANO_MODEL_PY_URL} 到 {model_dir}。"
            f"原因：{e}"
        ) from e
    if not os.path.isfile(model_py):
        raise RuntimeError(f"Fun-ASR-Nano 缺少 model.py：{model_dir}")
    return model_py


def _patch_funasr_nano_cpu_dtype(model_dir):
    """CPU 推理将 config.yaml 中 llm_dtype=bf16 改为 fp32（bf16 需较新 CPU/加速器）。"""
    cfg_path = os.path.join(model_dir, "config.yaml")
    if not os.path.isfile(cfg_path):
        return
    try:
        text = open(cfg_path, encoding="utf-8").read()
    except OSError:
        return
    if "llm_dtype: bf16" not in text and "llm_dtype:bf16" not in text:
        return
    patched = text.replace("llm_dtype: bf16", "llm_dtype: fp32").replace(
        "llm_dtype:bf16", "llm_dtype: fp32"
    )
    bak = cfg_path + ".bf16.bak"
    try:
        if not os.path.isfile(bak):
            open(bak, "w", encoding="utf-8").write(text)
        open(cfg_path, "w", encoding="utf-8").write(patched)
    except OSError:
        pass


def _get_funasr_nano(model_dir):
    """加载/缓存 Fun-ASR-Nano（纯 CPU）。

    ModelScope 拉取的权重目录通常只有 model.pt / config.yaml / Qwen3-0.6B，
    不含 GitHub 仓库里的 model.py。funasr 1.3+ 已内置 FunASRNano 类，可直接加载。
    """
    with _lock:
        if model_dir in _funasr_nano_cache:
            return _funasr_nano_cache[model_dir]
        if not os.path.isdir(model_dir):
            raise RuntimeError(f"Fun-ASR-Nano 模型目录不存在：{model_dir}")
        if not os.path.isfile(os.path.join(model_dir, "model.pt")):
            raise RuntimeError(
                f"Fun-ASR-Nano 缺少 model.pt，请先在模型管理中拉取权重：{model_dir}")
        _patch_funasr_nano_cpu_dtype(model_dir)
        remote = _ensure_funasr_nano_remote_code(model_dir)
        from funasr import AutoModel  # 惰性导入
        kwargs = dict(model=model_dir, disable_update=True, device="cpu")
        if remote:
            kwargs.update(trust_remote_code=True, remote_code=remote)
        model = AutoModel(**kwargs)
        _funasr_nano_cache[model_dir] = model
        return model


def transcribe_audio_nano(model_dir, audio_path, language="auto"):
    """Fun-ASR-Nano 语音识别（纯 CPU）。返回与 SenseVoice 同结构的 {text, language, emotion, events}。"""
    model = _get_funasr_nano(model_dir)
    lang_key = (language or "auto").strip()
    gen_lang = _NANO_LANG.get(lang_key.lower(), lang_key) if lang_key.lower() in _NANO_LANG else lang_key
    if gen_lang not in ("auto", "中文", "英文", "日文"):
        gen_lang = "auto"
    try:
        res = model.generate(
            input=[audio_path],
            cache={},
            batch_size=1,
            language=gen_lang,
            itn=True,
        )
    except TypeError:
        # 兼容旧版 funasr generate 参数名
        res = model.generate(
            input=[audio_path],
            cache={},
            batch_size=1,
            language=gen_lang,
            use_itn=True,
        )
    text = ""
    if res:
        item = res[0] if isinstance(res, list) else res
        if isinstance(item, dict):
            text = (item.get("text") or "").strip()
        else:
            text = str(item).strip()
    lang_label = None if gen_lang == "auto" else gen_lang
    return {"text": text, "language": lang_label, "emotion": None, "events": []}


def _parse_sensevoice_rich(raw):
    """解析 SenseVoice 富文本（<|lang|><|emo|><|event|>正文）-> {text, language, emotion, events}。"""
    import re
    from funasr.utils.postprocess_utils import rich_transcription_postprocess
    text = rich_transcription_postprocess(raw)
    tags = re.findall(r"<\|([^|]+)\|>", raw)
    language = next((_LANG_CN.get(t, t) for t in tags if t in _LANG_CN), None)
    emotion = next((_EMO_CN.get(t, t) for t in tags if t in _EMO_CN), None)
    events = [_EVENT_CN.get(t, t) for t in tags if t in _EVENT_CN]
    return {"text": text, "language": language, "emotion": emotion, "events": events}


# ------------------------------------------------------------ funasr_onnx 语音识别（SenseVoice-onnx 量化版，更小更快）
_funasr_onnx_cache = {}  # model_dir -> funasr_onnx SenseVoiceSmall
_SENSEVOICE_BPE = "chn_jpn_yue_eng_ko_spectok.bpe.model"


def _get_funasr_onnx(model_dir):
    """加载/缓存 funasr_onnx SenseVoiceSmall（量化 onnx）。

    onnx 仓库缺 bpe 分词模型，自动从 iic/SenseVoiceSmall 补一份（377KB）。
    """
    with _lock:
        if model_dir in _funasr_onnx_cache:
            return _funasr_onnx_cache[model_dir]
        bpe = os.path.join(model_dir, _SENSEVOICE_BPE)
        if not os.path.isfile(bpe):
            try:
                from modelscope.hub.file_download import model_file_download
                model_file_download(model_id="iic/SenseVoiceSmall",
                                    file_path=_SENSEVOICE_BPE, local_dir=model_dir)
            except Exception:  # noqa: BLE001  缺 bpe 时给出明确错误
                raise RuntimeError(
                    f"onnx 模型缺分词文件 {_SENSEVOICE_BPE}，且自动下载失败，请手动放入模型目录。")
        from funasr_onnx import SenseVoiceSmall
        model = SenseVoiceSmall(model_dir, batch_size=1, quantize=True)
        _funasr_onnx_cache[model_dir] = model
        return model


def transcribe_audio_onnx(model_dir, audio_path):
    """SenseVoice-onnx 语音识别（量化版，CPU 更快更小）。返回 {text, language, emotion, events}。"""
    model = _get_funasr_onnx(model_dir)
    res = model([audio_path], language="auto", use_itn=True)
    raw = res[0] if res else ""
    return _parse_sensevoice_rich(raw)


# ------------------------------------------------------------ Whisper 语音识别（transformers，HF whisper 模型目录）
_whisper_cache = {}  # model_dir -> transformers ASR pipeline
# Whisper 语言码 -> 中文（覆盖常见语种）
_WHISPER_LANG_CN = {"chinese": "中文", "english": "英文", "cantonese": "粤语",
                    "japanese": "日语", "korean": "韩语", "zh": "中文", "en": "英文",
                    "yue": "粤语", "ja": "日语", "ko": "韩语"}


def _disable_torchcodec_for_asr():
    """禁用 ASR pipeline 对 torchcodec 的探测。

    transformers 5.x 在 is_torchcodec_available()==True 时会 `import torchcodec`，
    而 Windows + torch CPU 环境常常装了 torchcodec 包却缺 FFmpeg 共享 DLL，
    导入直接抛 RuntimeError（libtorchcodec_core*.dll）。本项目已用 imageio-ffmpeg
    预解码波形，无需 torchcodec。
    """
    try:
        import transformers.pipelines.automatic_speech_recognition as asr_mod
        asr_mod.is_torchcodec_available = lambda: False
    except Exception:  # noqa: BLE001
        pass
    try:
        # datasets / audio_utils 等也可能探测；一并关闭缓存判定
        import transformers.utils.import_utils as iu
        if hasattr(iu.is_torchcodec_available, "cache_clear"):
            iu.is_torchcodec_available.cache_clear()
        iu.is_torchcodec_available = lambda: False
    except Exception:  # noqa: BLE001
        pass


def _get_whisper(model_dir):
    """加载/缓存 Whisper ASR pipeline（transformers，CPU）。

    chunk_length_s=30 启用分块，支持任意时长音频；惰性导入 transformers/torch。
    """
    with _lock:
        if model_dir in _whisper_cache:
            return _whisper_cache[model_dir]
        _disable_torchcodec_for_asr()
        from transformers import pipeline  # 惰性导入
        pipe = pipeline(
            "automatic-speech-recognition",
            model=model_dir,
            chunk_length_s=30,
            device="cpu",
            # 明确不用 torchcodec 解码后端（预解码为 numpy）
        )
        _whisper_cache[model_dir] = pipe
        return pipe


def _decode_audio_16k(audio_path):
    """用 imageio-ffmpeg 自带 ffmpeg 解码任意音频 -> 16k 单声道 float32 numpy。

    避免依赖系统 PATH 上的 ffmpeg（transformers 默认调用名为 `ffmpeg` 的可执行文件，
    Windows 上常缺失，导致 "ffmpeg was not found"）。支持 wav/mp3/m4a/flac/ogg/aac。
    """
    import subprocess
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [exe, "-nostdin", "-threads", "1", "-i", audio_path,
           "-ac", "1", "-ar", "16000", "-f", "f32le", "-hide_banner",
           "-loglevel", "error", "pipe:1"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"音频解码失败：{proc.stderr.decode('utf-8', 'ignore')[:200]}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def transcribe_audio_whisper(model_dir, audio_path):
    """Whisper 语音识别（transformers）：转写 + 检测语言。

    task=transcribe 保证按原语言转写（不翻译为英文）；返回 {text, language, emotion, events}
    （与 SenseVoice 同结构，emotion/events 为空，供前端统一渲染）。
    自行用 ffmpeg 解码为波形再喂入 pipeline，规避系统缺 ffmpeg / torchcodec 的问题。
    """
    _disable_torchcodec_for_asr()
    pipe = _get_whisper(model_dir)
    waveform = _decode_audio_16k(audio_path)
    if waveform.size == 0:
        return {"text": "", "language": None, "emotion": None, "events": []}
    # 使用 array+sampling_rate，走 numpy 路径，不触发 torchcodec / ffmpeg 文件解码
    try:
        res = pipe(
            {"array": waveform, "sampling_rate": 16000},
            return_language=True,
            generate_kwargs={"task": "transcribe"},
        )
    except TypeError:
        # 旧版 pipeline 可能不支持 return_language
        res = pipe(
            {"array": waveform, "sampling_rate": 16000},
            generate_kwargs={"task": "transcribe"},
        )
    except Exception as e:  # noqa: BLE001
        err = str(e)
        if "torchcodec" in err.lower() or "libtorchcodec" in err.lower() or "ffmpeg" in err.lower():
            # 兜底：绕过 pipeline，直接 processor + model
            res = _whisper_generate_direct(model_dir, waveform)
        else:
            raise
    text = (res.get("text") or "").strip()
    # 语言取自分块 chunks 的首个非空 language（return_language=True 时提供）
    lang = None
    for ch in res.get("chunks") or []:
        if ch.get("language"):
            lang = ch["language"]
            break
    if lang is None:
        lang = res.get("language")
    language = _WHISPER_LANG_CN.get((lang or "").lower(), lang) if lang else None
    return {"text": text, "language": language, "emotion": None, "events": []}


_whisper_direct_cache = {}  # model_dir -> (processor, model)


def _whisper_generate_direct(model_dir, waveform):
    """不经过 ASR pipeline，直接用 Whisper processor/model（彻底避开 torchcodec）。"""
    import torch
    with _lock:
        if model_dir not in _whisper_direct_cache:
            from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
            processor = AutoProcessor.from_pretrained(model_dir)
            model = AutoModelForSpeechSeq2Seq.from_pretrained(model_dir)
            model.eval()
            _whisper_direct_cache[model_dir] = (processor, model)
        processor, model = _whisper_direct_cache[model_dir]

    # 长音频按 30s 分块（与 pipeline chunk_length_s=30 一致）
    sr = 16000
    chunk = sr * 30
    texts = []
    for start in range(0, len(waveform), chunk):
        piece = waveform[start: start + chunk]
        if piece.size == 0:
            continue
        inputs = processor(piece, sampling_rate=sr, return_tensors="pt")
        prompt_ids = None
        try:
            prompt_ids = processor.get_decoder_prompt_ids(task="transcribe")
        except Exception:  # noqa: BLE001
            prompt_ids = None
        gen_kwargs = {"max_new_tokens": 444}
        if prompt_ids is not None:
            gen_kwargs["forced_decoder_ids"] = prompt_ids
        with torch.no_grad():
            pred_ids = model.generate(inputs.input_features, **gen_kwargs)
        texts.append(processor.batch_decode(pred_ids, skip_special_tokens=True)[0].strip())
    return {"text": " ".join(t for t in texts if t).strip(), "chunks": []}

# ------------------------------------------------------------ Linly-Talker 数字人（SadTalker）
def synthesize_talking_head(model_dir, image_path, audio_path, out_path, progress_cb=None):
    """数字人合成：人像图 + 驱动音频 -> 说话头像视频(H.264 mp4)。

    脚手架交付：数字人生成需 GPU + SadTalker 运行时（vendored 推理代码 + 子模型权重），
    非 pip 单包。本函数已留好接入点（model_dir 为已拉取的 Kedreamix/Linly-Talker 子模型目录，
    输出写 out_path，progress_cb(processed,total) 上报进度）。

    GPU 环境接入步骤：
      1) 安装 CUDA 版 torch/torchaudio；
      2) 引入 Kedreamix/Linly-Talker(SadTalker) 推理代码；
      3) 在此调用其 image+audio→video 推理，导出 H.264 mp4 到 out_path（可复用 _open_h264/_write_bgr）。

    当前为 CPU 环境，生成未启用，抛出明确依赖提示。
    """
    raise RuntimeError(
        "数字人合成需 GPU + SadTalker 运行环境：当前为 CPU 版 torch，暂未启用生成。"
        "请先准备 CUDA 版 torch 并接入 Linly-Talker(SadTalker) 推理代码后再使用本功能。"
    )


def synthesize_speech_hf(model_dir, text, task="text-to-speech"):
    """transformers 文本转语音（VITS/MMS-TTS 等），CPU 原生 pipeline。

    返回 {audio(base64 wav), sampleRate, speaker:None}。
    """
    import io
    import base64
    import numpy as np
    import soundfile as sf

    pipe = _get_text_pipeline(task, model_dir)
    out = pipe(text)
    audio = np.asarray(out["audio"], dtype=np.float32).squeeze()
    sr = int(out["sampling_rate"])
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    audio_b64 = base64.b64encode(buf.getvalue()).decode()
    return {"audio": audio_b64, "sampleRate": sr, "speaker": None}


# ------------------------------------------------------------ VibeVoice-Realtime 文本转语音（预置音色）
_vibevoice_cache = {}  # model_dir -> (processor, model)


def _vibevoice_repo_path():
    """VibeVoice 官方推理代码目录（位于 uploads/models/third_party/VibeVoice）。"""
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(base, "uploads", "models", "third_party", "VibeVoice"))


def _ensure_vibevoice_path():
    """注入 vendored 官方 VibeVoice 仓库到 sys.path（含 streaming 推理代码）。返回仓库根。"""
    repo = _vibevoice_repo_path()
    if os.path.isdir(repo) and repo not in sys.path:
        sys.path.insert(0, repo)
    return repo


def _vibevoice_voice_dir():
    return os.path.join(_ensure_vibevoice_path(), "demo", "voices", "streaming_model")


def list_vibevoice_voices():
    """VibeVoice 预置音色名列表（来自 vendored repo 的 .pt 预填缓存）。"""
    import glob
    vdir = _vibevoice_voice_dir()
    return sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(vdir, "*.pt")))


def _resolve_vibevoice_voice(speaker):
    """音色名 -> .pt 路径（精确 / 模糊匹配 / 默认首个英文）。"""
    import glob
    vdir = _vibevoice_voice_dir()
    exact = os.path.join(vdir, f"{speaker}.pt")
    if os.path.isfile(exact):
        return exact
    pts = sorted(glob.glob(os.path.join(vdir, "*.pt")))
    if not pts:
        raise RuntimeError(
            f"VibeVoice 无可用音色预设（{os.path.join(_vibevoice_repo_path(), 'demo', 'voices', 'streaming_model')}）"
        )
    s = (speaker or "").lower()
    match = [p for p in pts if s and s in os.path.basename(p).lower()]
    if match:
        return match[0]
    en = [p for p in pts if os.path.basename(p).lower().startswith("en-")]
    return en[0] if en else pts[0]


def _get_vibevoice(model_dir):
    """加载/缓存 VibeVoice-Realtime streaming 模型（依赖 uploads/models/third_party/VibeVoice，CPU）。"""
    with _lock:
        if model_dir in _vibevoice_cache:
            return _vibevoice_cache[model_dir]
        _ensure_vibevoice_path()
        import torch
        try:
            from vibevoice.modular.modeling_vibevoice_streaming_inference import \
                VibeVoiceStreamingForConditionalGenerationInference
            from vibevoice.processor.vibevoice_streaming_processor import \
                VibeVoiceStreamingProcessor
        except ImportError as e:
            raise RuntimeError(
                f"VibeVoice 本地推理需官方代码：请确认 {_vibevoice_repo_path()} 已 git clone。"
            ) from e
        processor = VibeVoiceStreamingProcessor.from_pretrained(model_dir)
        model = VibeVoiceStreamingForConditionalGenerationInference.from_pretrained(
            model_dir, torch_dtype=torch.float32, device_map="cpu", attn_implementation="sdpa")
        model.eval()
        model.set_ddpm_inference_steps(num_steps=5)
        _vibevoice_cache[model_dir] = (processor, model)
        return processor, model


def synthesize_speech_vibevoice(model_dir, text, speaker="en-Carter_man"):
    """VibeVoice-Realtime 文本转语音（预置音色）。返回 {audio(base64 wav), sampleRate, speaker}。"""
    import io
    import copy
    import base64 as _b64
    import torch
    import soundfile as _sf

    processor, model = _get_vibevoice(model_dir)
    voice_pt = _resolve_vibevoice_voice(speaker)
    pre = torch.load(voice_pt, map_location="cpu", weights_only=False)  # 官方音色预填缓存（可信）
    inputs = processor.process_input_with_cached_prompt(
        text=text, cached_prompt=pre, padding=True,
        return_tensors="pt", return_attention_mask=True)
    out = model.generate(
        **inputs, max_new_tokens=None, cfg_scale=1.5, tokenizer=processor.tokenizer,
        generation_config={"do_sample": False}, verbose=False,
        all_prefilled_outputs=copy.deepcopy(pre))
    if not out.speech_outputs or out.speech_outputs[0] is None:
        raise ValueError("合成结果为空")
    arr = out.speech_outputs[0].detach().cpu().float().numpy().squeeze()
    sr = 24000
    buf = io.BytesIO()
    _sf.write(buf, arr, sr, format="WAV")
    audio_b64 = _b64.b64encode(buf.getvalue()).decode()
    return {"audio": audio_b64, "sampleRate": sr,
            "speaker": os.path.splitext(os.path.basename(voice_pt))[0]}


# ------------------------------------------------------------ MeloTTS(sherpa-onnx) 中英混合文本转语音
_melotts_cache = {}  # model_dir -> sherpa_onnx.OfflineTts


def _get_melotts(model_dir):
    """加载/缓存 sherpa-onnx MeloTTS（中英混合，纯 onnx，CPU）。"""
    with _lock:
        if model_dir in _melotts_cache:
            return _melotts_cache[model_dir]
        import sherpa_onnx
        j = lambda *p: os.path.join(model_dir, *p)
        rule_fsts = ",".join(j(x) for x in ("date.fst", "number.fst", "phone.fst")
                             if os.path.isfile(j(x)))
        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=j("model.onnx"), lexicon=j("lexicon.txt"),
                    tokens=j("tokens.txt"), dict_dir=j("dict")),
                num_threads=2, provider="cpu"),
            rule_fsts=rule_fsts, max_num_sentences=1)
        tts = sherpa_onnx.OfflineTts(cfg)
        _melotts_cache[model_dir] = tts
        return tts


def synthesize_speech_melotts(model_dir, text, speed=1.0):
    """MeloTTS 中英混合语音合成（sherpa-onnx）。返回 {audio(base64 wav), sampleRate, speaker:None}。"""
    import io
    import base64 as _b64
    import numpy as np
    import soundfile as _sf

    tts = _get_melotts(model_dir)
    audio = tts.generate(text, sid=0, speed=float(speed) or 1.0)
    arr = np.asarray(audio.samples, dtype=np.float32)
    sr = int(audio.sample_rate)
    if arr.size == 0:
        raise ValueError("合成结果为空")
    buf = io.BytesIO()
    _sf.write(buf, arr, sr, format="WAV")
    return {"audio": _b64.b64encode(buf.getvalue()).decode(), "sampleRate": sr, "speaker": None}


# ------------------------------------------------------------ VoxCPM2 文本转语音 / 克隆 / 音色设计
_voxcpm_cache = {}  # model_dir -> VoxCPM 实例


def _get_voxcpm(model_dir):
    """加载/缓存 VoxCPM 模型（openbmb/VoxCPM2 等，HF voxcpm 库，CPU/GPU 自适应）。"""
    with _lock:
        if model_dir in _voxcpm_cache:
            return _voxcpm_cache[model_dir]
        try:
            from voxcpm import VoxCPM
        except ImportError as e:
            raise RuntimeError(
                "VoxCPM 本地推理需安装 voxcpm 库：pip install voxcpm") from e
        # load_denoiser=False：关闭可选降噪器，省额外依赖并加速
        model = VoxCPM.from_pretrained(model_dir, load_denoiser=False)
        _voxcpm_cache[model_dir] = model
        return model


def _voxcpm_to_result(model, wav):
    """VoxCPM generate 输出(numpy) -> {audio(base64 wav), sampleRate, speaker}。"""
    import io
    import base64 as _b64
    import numpy as np
    import soundfile as _sf

    arr = np.asarray(wav, dtype=np.float32).squeeze()
    if arr.size == 0:
        raise ValueError("合成结果为空")
    sr = int(model.tts_model.sample_rate)
    buf = io.BytesIO()
    _sf.write(buf, arr, sr, format="WAV")
    return {"audio": _b64.b64encode(buf.getvalue()).decode(), "sampleRate": sr, "speaker": None}


def synthesize_speech_voxcpm(model_dir, text, cfg_value=2.0, inference_timesteps=10):
    """VoxCPM 纯文本转语音（含音色设计：文本开头括号描述即可，无需特殊处理）。"""
    model = _get_voxcpm(model_dir)
    wav = model.generate(text=text, cfg_value=cfg_value,
                         inference_timesteps=inference_timesteps)
    return _voxcpm_to_result(model, wav)


def synthesize_speech_voxcpm_clone(model_dir, text, prompt_text, prompt_path,
                                   cfg_value=2.0, inference_timesteps=10):
    """VoxCPM 零样本音色克隆：参考音频(+其文本) → 用该音色读目标文本。"""
    model = _get_voxcpm(model_dir)
    wav = model.generate(text=text, prompt_wav_path=prompt_path, prompt_text=prompt_text,
                         cfg_value=cfg_value, inference_timesteps=inference_timesteps)
    return _voxcpm_to_result(model, wav)


# ------------------------------------------------------------ 越线计数（纯几何，可单测）
def _orient(ax, ay, bx, by, cx, cy):
    """点 C 相对有向线段 A->B 的叉积；>0 / <0 表示两侧，=0 共线。"""
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _crosses(prev, curr, line):
    """移动线段 prev->curr 是否穿过计数线段 line=[x1,y1,x2,y2]。

    返回 0=未穿；+1=进（prev 在线负侧→正侧）；-1=出（反向）。
    用线段相交判定：两线段互相分隔对方端点才算真正相交。
    """
    ax, ay = prev
    bx, by = curr
    x1, y1, x2, y2 = line
    d1 = _orient(x1, y1, x2, y2, ax, ay)   # prev 相对计数线
    d2 = _orient(x1, y1, x2, y2, bx, by)   # curr 相对计数线
    d3 = _orient(ax, ay, bx, by, x1, y1)   # 线端点相对移动线段
    d4 = _orient(ax, ay, bx, by, x2, y2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 1 if d1 < 0 else -1
    return 0


# ------------------------------------------------------------ GOT-OCR2 文字识别（OCR）
_ocr_cache = {}  # model_dir -> (processor, model)


def _get_ocr(model_dir):
    """加载/缓存 GOT-OCR2（transformers 原生 image-text-to-text，CPU/float32）。"""
    with _lock:
        if model_dir in _ocr_cache:
            return _ocr_cache[model_dir]
        import torch
        from transformers import AutoProcessor, AutoModelForImageTextToText
        processor = AutoProcessor.from_pretrained(model_dir)
        model = AutoModelForImageTextToText.from_pretrained(
            model_dir, torch_dtype=torch.float32, low_cpu_mem_usage=True).eval()
        _ocr_cache[model_dir] = (processor, model)
        return processor, model


def recognize_text(model_dir, image_bytes, formatted=False):
    """GOT-OCR2 文字识别：图片字节 -> 文本。formatted=True 输出格式化(markdown/latex)。"""
    import io as _io
    from PIL import Image
    try:
        img = Image.open(_io.BytesIO(image_bytes)).convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"无法解析图片：{e}")

    processor, model = _get_ocr(model_dir)
    if formatted:
        try:
            inputs = processor(img, return_tensors="pt", format=True)
        except TypeError:
            inputs = processor(img, return_tensors="pt")  # 不支持 format 参数则回退 plain
    else:
        inputs = processor(img, return_tensors="pt")

    gen = model.generate(**inputs, do_sample=False, max_new_tokens=4096,
                         tokenizer=processor.tokenizer, stop_strings="<|im_end|>")
    text = processor.decode(
        gen[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()

    w, h = img.size
    return {"text": text, "chars": len(text), "width": w, "height": h}


# ------------------------------------------------------------ PaddleOCR onnx（RapidOCR：det+rec）
_paddle_cache = {}  # (det_onnx, rec_onnx) -> RapidOCR 引擎


def _find_onnx(model_dir):
    """目录内找权重 onnx（优先 inference.onnx，否则首个 .onnx）。"""
    import os
    cand = os.path.join(model_dir, "inference.onnx")
    if os.path.isfile(cand):
        return cand
    for root, _dirs, files in os.walk(model_dir):
        for f in files:
            if f.lower().endswith(".onnx"):
                return os.path.join(root, f)
    raise ValueError("目录内未找到 onnx 模型")


def _extract_rec_keys(rec_dir):
    """从 rec 目录 inference.yml 的 PostProcess.character_dict 提取字符字典，写 rec_keys.txt（幂等）。"""
    import os
    import yaml
    keys_path = os.path.join(rec_dir, "rec_keys.txt")
    if os.path.isfile(keys_path) and os.path.getsize(keys_path) > 0:
        return keys_path
    yml_path = os.path.join(rec_dir, "inference.yml")
    if not os.path.isfile(yml_path):
        raise ValueError("识别模型目录缺少 inference.yml")
    with open(yml_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    chars = (cfg or {}).get("PostProcess", {}).get("character_dict")
    if not chars:
        raise ValueError("无法解析识别字典(character_dict)")
    with open(keys_path, "w", encoding="utf-8") as f:
        f.write("\n".join(str(c) for c in chars))
    return keys_path


def _get_paddle(det_onnx, rec_onnx, keys_path):
    """加载/缓存 RapidOCR 引擎（按 det+rec onnx 路径键）。"""
    with _lock:
        key = (det_onnx, rec_onnx)
        if key in _paddle_cache:
            return _paddle_cache[key]
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as e:
            raise RuntimeError("PaddleOCR 引擎需安装 rapidocr_onnxruntime：pip install rapidocr_onnxruntime") from e
        engine = RapidOCR(det_model_path=det_onnx, rec_model_path=rec_onnx,
                          rec_keys_path=keys_path)
        _paddle_cache[key] = engine
        return engine


def paddle_ocr(det_dir, rec_dir, image_bytes):
    """PaddleOCR（RapidOCR）det+rec 流水线：图片字节 -> 文本 + 框。"""
    det_onnx = _find_onnx(det_dir)
    rec_onnx = _find_onnx(rec_dir)
    keys_path = _extract_rec_keys(rec_dir)

    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # BGR
    if img is None:
        raise ValueError("无法解析图片")

    engine = _get_paddle(det_onnx, rec_onnx, keys_path)
    result, _elapse = engine(img)

    lines = []
    for item in (result or []):
        box, txt, score = item[0], item[1], item[2]
        lines.append({
            "text": txt,
            "score": round(float(score), 4),
            "box": [[round(float(x), 1), round(float(y), 1)] for x, y in box],
        })
    h, w = img.shape[:2]
    return {
        "text": "\n".join(l["text"] for l in lines),
        "lines": lines,
        "count": len(lines),
        "width": w,
        "height": h,
    }


# ---------------------------------------------------------------------------
# InsightFace face recognition (detect + ArcFace embedding)
# ---------------------------------------------------------------------------
_face_cache = {}  # (root, pack, providers, det_size) -> FaceAnalysis


def _face_providers():
    """Prefer CUDA EP when available, else CPU."""
    try:
        import onnxruntime as ort
        avail = ort.get_available_providers()
        if "CUDAExecutionProvider" in avail:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    except Exception:  # noqa: BLE001
        pass
    return ["CPUExecutionProvider"]


def _get_face_app(root_dir, pack_name="buffalo_s", det_size=(640, 640)):
    """Cached FaceAnalysis; root_dir is insightface root (models/<pack> under it)."""
    providers = _face_providers()
    key = (os.path.abspath(root_dir), pack_name, ",".join(providers), det_size)
    with _lock:
        app = _face_cache.get(key)
        if app is not None:
            return app
        from insightface.app import FaceAnalysis
        os.makedirs(root_dir, exist_ok=True)
        app = FaceAnalysis(name=pack_name, root=root_dir, providers=providers)
        ctx_id = 0 if providers and providers[0].startswith("CUDA") else -1
        app.prepare(ctx_id=ctx_id, det_size=det_size)
        _face_cache[key] = app
        return app


def ensure_insightface_pack(root_dir, pack_name="buffalo_s"):
    """Ensure pack exists under root/models/<pack>; return (pack_dir, size_bytes)."""
    pack_dir = os.path.join(root_dir, "models", pack_name)
    marker = os.path.join(pack_dir, "w600k_mbf.onnx")
    alt = os.path.join(pack_dir, "w600k_r50.onnx")
    if not (os.path.isfile(marker) or os.path.isfile(alt)):
        _get_face_app(root_dir, pack_name)
    total = 0
    if os.path.isdir(pack_dir):
        for r, _d, files in os.walk(pack_dir):
            for f in files:
                total += os.path.getsize(os.path.join(r, f))
    return pack_dir, total


def _decode_bgr(image_bytes):
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("cannot decode image")
    return img


def extract_face_embeddings(root_dir, pack_name, image_bytes, det_thresh=0.5):
    """Extract face embeddings (L2-normalized) from image bytes."""
    from services.face_gallery import l2_normalize

    app = _get_face_app(root_dir, pack_name)
    img = _decode_bgr(image_bytes)
    faces = app.get(img)
    out = []
    for f in faces or []:
        if float(getattr(f, "det_score", 1.0)) < float(det_thresh):
            continue
        emb = l2_normalize(np.asarray(f.embedding, dtype=np.float32))
        bbox = [float(x) for x in f.bbox.tolist()]
        out.append({
            "embedding": emb,
            "bbox": bbox,
            "detScore": round(float(f.det_score), 4),
        })
    return out, img


def recognize_faces(
    root_dir,
    pack_name,
    model_key,
    image_bytes,
    threshold=0.4,
    det_thresh=0.5,
    draw=False,
):
    """1:N recognize; returns detections with bbox/name/score/matched."""
    from services.face_gallery import match_embedding

    faces, img = extract_face_embeddings(
        root_dir, pack_name, image_bytes, det_thresh=det_thresh)
    h, w = img.shape[:2]
    detections = []
    for face in faces:
        m = match_embedding(face["embedding"], model_key, threshold=threshold)
        detections.append({
            "className": m["name"],
            "classId": m["personId"] if m["personId"] is not None else -1,
            "personId": m["personId"],
            "name": m["name"],
            "confidence": m["score"],
            "score": m["score"],
            "matched": m["matched"],
            "detScore": face["detScore"],
            "bbox": face["bbox"],
        })

    image_b64 = None
    if draw and detections:
        vis = img.copy()
        for d in detections:
            x1, y1, x2, y2 = [int(v) for v in d["bbox"]]
            color = (0, 200, 80) if d["matched"] else (0, 165, 255)
            cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
            label = f"{d['name']} {d['score']:.2f}"
            cv2.putText(
                vis, label, (x1, max(0, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA,
            )
        ok, buf = cv2.imencode(".jpg", vis)
        if ok:
            image_b64 = base64.b64encode(buf.tobytes()).decode("ascii")

    return {
        "detections": detections,
        "count": len(detections),
        "width": w,
        "height": h,
        "imageBase64": image_b64,
        "threshold": float(threshold),
        "providers": _face_providers(),
    }

