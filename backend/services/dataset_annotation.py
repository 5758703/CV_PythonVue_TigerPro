"""数据集抽帧与 YOLO 在线标注服务。"""
from __future__ import annotations

import re
from pathlib import Path

import cv2

from services.training import IMG_EXTENSIONS

_FRAME_NAME_RE = re.compile(r"^frame_(\d+)$")


def ensure_annotation_dirs(raw_dir: Path) -> tuple[Path, Path]:
    """确保 raw/images 与 raw/labels 目录存在。"""
    img_dir = raw_dir / "images"
    lbl_dir = raw_dir / "labels"
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)
    return img_dir, lbl_dir


def _next_frame_index(img_dir: Path) -> int:
    max_idx = 0
    for p in img_dir.iterdir():
        if not p.is_file() or p.suffix.lower() not in IMG_EXTENSIONS:
            continue
        m = _FRAME_NAME_RE.match(p.stem)
        if m:
            max_idx = max(max_idx, int(m.group(1)))
    return max_idx + 1


def extract_frames_from_video(
    video_path: Path,
    raw_dir: Path,
    *,
    frame_interval: int = 1,
    max_frames: int = 250,
    start_sec: float = 0.0,
    end_sec: float | None = None,
) -> dict:
    """从视频按间隔抽帧，保存到 raw/images/frame_XXXXX.jpg。"""
    img_dir, _ = ensure_annotation_dirs(raw_dir)
    interval = max(1, int(frame_interval or 1))
    limit = max(1, min(int(max_frames or 250), 2000))

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError("无法打开视频文件")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    start_frame = max(0, int(start_sec * fps))
    end_frame = int(end_sec * fps) if end_sec is not None and end_sec > 0 else (total - 1 if total > 0 else None)

    if start_frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    saved = 0
    read_idx = start_frame
    next_idx = _next_frame_index(img_dir)

    try:
        while saved < limit:
            ok, frame = cap.read()
            if not ok:
                break
            if end_frame is not None and read_idx > end_frame:
                break
            if (read_idx - start_frame) % interval == 0:
                name = f"frame_{next_idx:05d}.jpg"
                out_path = img_dir / name
                cv2.imwrite(str(out_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
                saved += 1
                next_idx += 1
            read_idx += 1
    finally:
        cap.release()

    if saved == 0:
        raise ValueError("未抽取到任何帧，请检查视频时长或抽帧参数")

    return {
        "saved": saved,
        "fps": round(float(fps), 2),
        "totalFrames": total,
        "frameInterval": interval,
        "startFrame": start_frame,
        "endFrame": end_frame,
    }


def _resolve_image(stem: str, img_dir: Path) -> Path | None:
    for ext in IMG_EXTENSIONS:
        p = img_dir / f"{stem}{ext}"
        if p.is_file():
            return p
    return None


def list_annotation_samples(raw_dir: Path) -> list[dict]:
    """列出可标注样本及是否已标注。"""
    img_dir, lbl_dir = ensure_annotation_dirs(raw_dir)
    samples = []
    for img in sorted(img_dir.iterdir()):
        if not img.is_file() or img.suffix.lower() not in IMG_EXTENSIONS:
            continue
        stem = img.stem
        lbl = lbl_dir / f"{stem}.txt"
        box_count = 0
        if lbl.is_file():
            try:
                lines = [ln.strip() for ln in lbl.read_text(encoding="utf-8").splitlines() if ln.strip()]
                box_count = len(lines)
            except OSError:
                box_count = 0
        samples.append({
            "stem": stem,
            "name": img.name,
            "annotated": lbl.is_file() and box_count > 0,
            "boxCount": box_count,
            "size": img.stat().st_size,
        })
    return samples


def annotation_stats(raw_dir: Path) -> dict:
    samples = list_annotation_samples(raw_dir)
    total = len(samples)
    annotated = sum(1 for s in samples if s["annotated"])
    return {
        "total": total,
        "annotated": annotated,
        "unannotated": max(0, total - annotated),
        "totalBoxes": sum(s["boxCount"] for s in samples),
    }


def read_yolo_labels(lbl_path: Path, class_names: list[str]) -> list[dict]:
    """读取 YOLO 标签，返回像素无关的归一化框。"""
    if not lbl_path.is_file():
        return []
    boxes = []
    for line in lbl_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        try:
            cls_id = int(float(parts[0]))
            cx, cy, bw, bh = map(float, parts[1:5])
        except ValueError:
            continue
        cls_name = class_names[cls_id] if 0 <= cls_id < len(class_names) else str(cls_id)
        boxes.append({
            "classId": cls_id,
            "className": cls_name,
            "cx": cx,
            "cy": cy,
            "w": bw,
            "h": bh,
        })
    return boxes


def write_yolo_labels(lbl_path: Path, boxes: list[dict], class_names: list[str]) -> int:
    """写入 YOLO 标签文件。boxes 含 classId 或 className。"""
    lbl_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    name_to_id = {n: i for i, n in enumerate(class_names)}
    for b in boxes or []:
        cls_id = b.get("classId")
        if cls_id is None:
            cls_name = b.get("className")
            if cls_name not in name_to_id:
                raise ValueError(f"未知类别: {cls_name}")
            cls_id = name_to_id[cls_name]
        try:
            cx = float(b["cx"])
            cy = float(b["cy"])
            bw = float(b["w"])
            bh = float(b["h"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError("标注框坐标格式无效") from e
        cx = min(1.0, max(0.0, cx))
        cy = min(1.0, max(0.0, cy))
        bw = min(1.0, max(0.0, bw))
        bh = min(1.0, max(0.0, bh))
        if bw <= 0 or bh <= 0:
            continue
        lines.append(f"{int(cls_id)} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
    if lines:
        lbl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif lbl_path.is_file():
        lbl_path.unlink()
    return len(lines)


def get_sample_image_path(raw_dir: Path, stem: str) -> Path:
    img_dir, _ = ensure_annotation_dirs(raw_dir)
    if ".." in stem or "/" in stem or "\\" in stem:
        raise ValueError("非法样本名")
    img = _resolve_image(stem, img_dir)
    if img is None:
        raise FileNotFoundError(f"图片不存在: {stem}")
    return img


def get_sample_label_path(raw_dir: Path, stem: str) -> Path:
    _, lbl_dir = ensure_annotation_dirs(raw_dir)
    if ".." in stem or "/" in stem or "\\" in stem:
        raise ValueError("非法样本名")
    return lbl_dir / f"{stem}.txt"
