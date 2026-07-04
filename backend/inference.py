"""YOLO 推理服务：加载本地权重对图片做目标检测。

模型按权重绝对路径 + 文件 mtime 缓存，避免重复加载。
ultralytics / torch 体积大，全部惰性导入，加快应用启动。
"""
import base64
import os
import sys
import threading

import cv2
import numpy as np

_cache = {}            # abs_path -> (mtime, YOLO 实例)
_pipe_cache = {}       # (task, model_dir) -> transformers pipeline
_lock = threading.Lock()


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


def detect_image(abs_path, image_bytes, conf=0.25, draw=True):
    """对图片字节做检测。

    draw=True  返回带框 jpg(base64)；False 仅返回检测框坐标(实时场景省编码)。
    返回 dict：detections / imageBase64 / width / height。
    """
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")

    model = _get_model(abs_path)
    results = model.predict(img, conf=conf, verbose=False)
    r = results[0]

    names = r.names
    detections = []
    if r.boxes is not None:
        for b in r.boxes:
            cls_id = int(b.cls[0])
            xyxy = [round(float(v), 1) for v in b.xyxy[0].tolist()]
            detections.append({
                "className": names.get(cls_id, str(cls_id)),
                "classId": cls_id,
                "confidence": round(float(b.conf[0]), 4),
                "bbox": xyxy,
            })

    image_b64 = None
    if draw:
        plotted = r.plot()  # BGR ndarray，带框
        ok, buf = cv2.imencode(".jpg", plotted)
        image_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None

    h, w = img.shape[:2]
    return {
        "detections": detections,
        "count": len(detections),
        "imageBase64": image_b64,
        "width": w,
        "height": h,
    }


def detect_video(abs_path, src_path, dst_path, conf=0.25, progress_cb=None):
    """逐帧检测视频，输出带框视频到 dst_path。

    progress_cb(processed, total) 每帧回调，用于上报进度。
    返回统计：帧数 / 检出目标总数 / 各类别计数 / 分辨率 / fps。
    """
    model = _get_model(abs_path)

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
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            r = model.predict(frame, conf=conf, verbose=False)[0]
            if r.boxes is not None:
                names = r.names
                for b in r.boxes:
                    cid = int(b.cls[0])
                    name = names.get(cid, str(cid))
                    class_counts[name] = class_counts.get(name, 0) + 1
                    total_det += 1
            _write_bgr(writer, r.plot(), ew, eh)
            frames += 1
            if progress_cb:
                progress_cb(frames, total)
    finally:
        cap.release()
        writer.close()

    return {
        "frames": frames,
        "totalFrames": total,
        "totalDetections": total_det,
        "classCounts": class_counts,
        "fps": round(float(fps), 2),
        "width": ew,
        "height": eh,
    }


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


def rfdetr_weight_filename(model_key):
    """model_key -> 官方预训练权重文件名。"""
    return _RFDETR_WEIGHT.get((model_key or "rf-detr-medium").lower(), "rf-detr-medium.pth")


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


def _rfdetr_to_detections(sv_det, class_names):
    dets = []
    if sv_det is None or len(sv_det) == 0:
        return dets
    for i in range(len(sv_det)):
        x1, y1, x2, y2 = sv_det.xyxy[i]
        cid = int(sv_det.class_id[i])
        cname = class_names[cid] if 0 <= cid < len(class_names) else str(cid)
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
    """SenseVoice 语音识别：转写 + 语言/情感/音频事件标签。

    返回 {text, language, emotion, events}。
    """
    model = _get_funasr(model_dir)
    res = model.generate(input=audio_path, cache={}, language="auto",
                         use_itn=True, batch_size_s=60)
    raw = res[0]["text"] if res else ""
    return _parse_sensevoice_rich(raw)


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


def _get_whisper(model_dir):
    """加载/缓存 Whisper ASR pipeline（transformers，CPU）。

    chunk_length_s=30 启用分块，支持任意时长音频；惰性导入 transformers/torch。
    """
    with _lock:
        if model_dir in _whisper_cache:
            return _whisper_cache[model_dir]
        from transformers import pipeline  # 惰性导入
        pipe = pipeline("automatic-speech-recognition", model=model_dir,
                        chunk_length_s=30, device="cpu")
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
    自行用 ffmpeg 解码为波形再喂入 pipeline，规避系统缺 ffmpeg 的问题。
    """
    pipe = _get_whisper(model_dir)
    waveform = _decode_audio_16k(audio_path)
    res = pipe({"raw": waveform, "sampling_rate": 16000}, return_language=True,
               generate_kwargs={"task": "transcribe"})
    text = (res.get("text") or "").strip()
    # 语言取自分块 chunks 的首个非空 language（return_language=True 时提供）
    lang = None
    for ch in res.get("chunks") or []:
        if ch.get("language"):
            lang = ch["language"]
            break
    language = _WHISPER_LANG_CN.get((lang or "").lower(), lang) if lang else None
    return {"text": text, "language": language, "emotion": None, "events": []}


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
