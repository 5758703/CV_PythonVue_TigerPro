"""Pose-runtime adapter and video pipeline for squat counting."""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from services.squat_counter import SquatConfig, SquatCounter


_SKELETON = (
    (5, 6), (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16),
)


def _filled_rounded_rect(image, left, top, right, bottom, radius, color):
    """Draw a filled rounded rectangle, clipped to the image bounds."""
    height, width = image.shape[:2]
    left, right = max(0, left), min(width - 1, right)
    top, bottom = max(0, top), min(height - 1, bottom)
    if left >= right or top >= bottom:
        return
    radius = max(1, min(radius, (right - left) // 2, (bottom - top) // 2))
    cv2.rectangle(image, (left + radius, top), (right - radius, bottom), color, -1)
    cv2.rectangle(image, (left, top + radius), (right, bottom - radius), color, -1)
    for center in (
        (left + radius, top + radius), (right - radius, top + radius),
        (left + radius, bottom - radius), (right - radius, bottom - radius),
    ):
        cv2.circle(image, center, radius, color, -1, cv2.LINE_AA)


def _person_bbox(person: dict, keypoint_conf: float = 0.05):
    bbox = person.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        return [float(value) for value in bbox[:4]]
    visible = []
    for point in (person.get("keypoints") or [])[:17]:
        if isinstance(point, (list, tuple)) and len(point) >= 3 and float(point[2]) >= keypoint_conf:
            visible.append((float(point[0]), float(point[1])))
    if not visible:
        return None
    xs, ys = zip(*visible)
    pad = max(4.0, 0.05 * max(max(xs) - min(xs), max(ys) - min(ys)))
    return [min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad]


def normalize_persons(persons):
    normalized = []
    for raw in persons or []:
        person = dict(raw or {})
        keypoints = person.get("keypoints") or []
        if len(keypoints) < 17:
            continue
        person["keypoints"] = [list(point[:3]) for point in keypoints[:17]]
        bbox = _person_bbox(person)
        if bbox is None:
            continue
        person["bbox"] = bbox
        normalized.append(person)
    return normalized


class PoseFrameEstimator:
    """Adapt existing image pose runtimes to a common frame interface."""

    def __init__(self, library: str, model_key: str, weight_path: str | None, conf: float = 0.25):
        self.library = (library or "").lower()
        self.model_key = model_key or ""
        self.weight_path = weight_path
        self.conf = float(conf)

    def infer(self, frame):
        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            raise ValueError("failed to encode video frame")
        raw = encoded.tobytes()
        if self.library == "rtmlib":
            from inference import estimate_pose_rtmlib
            payload = estimate_pose_rtmlib(
                self.model_key, self.weight_path, raw, conf=self.conf, draw=False,
            )
        elif self.library == "yolo-master":
            from services import yolo_master
            payload = yolo_master.estimate_pose(self.weight_path, raw, conf=self.conf, draw=False)
        else:
            from inference import estimate_pose
            payload = estimate_pose(self.weight_path, raw, conf=self.conf, draw=False)
        return normalize_persons(payload.get("persons") if isinstance(payload, dict) else [])


def annotate_squat_frame(frame, state):
    """Return a copy with primary skeleton and squat telemetry."""
    canvas = frame.copy()
    person = state.get("primaryPerson") or {}
    points = person.get("keypoints") or []
    for start, end in _SKELETON:
        if len(points) <= max(start, end):
            continue
        first, second = points[start], points[end]
        if len(first) >= 3 and len(second) >= 3 and first[2] >= 0.05 and second[2] >= 0.05:
            cv2.line(
                canvas,
                (int(first[0]), int(first[1])),
                (int(second[0]), int(second[1])),
                (63, 220, 120),
                2,
                cv2.LINE_AA,
            )
    for point in points[:17]:
        if len(point) >= 3 and point[2] >= 0.05:
            cv2.circle(canvas, (int(point[0]), int(point[1])), 3, (20, 240, 255), -1, cv2.LINE_AA)
    bbox = person.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        cv2.rectangle(canvas, (int(bbox[0]), int(bbox[1])), (int(bbox[2]), int(bbox[3])), (63, 220, 120), 2)

    angle = state.get("kneeAngle")
    angle_text = "--" if angle is None else f"{float(angle):.1f} deg"
    lines = (
        f"STAGE   {state.get('stage') or 'waiting_stand'}",
        f"KNEE    {angle_text}",
        f"STATUS  {state.get('trackingStatus') or 'no_person'}",
    )
    height, width = canvas.shape[:2]
    scale = max(0.45, min(1.5, min(width / 640.0, height / 360.0)))
    margin = max(4, int(8 * scale))
    card_width = min(max(int(128 * scale), 56), max(1, width - 2 * margin))
    card_height = min(max(int(112 * scale), 48), max(1, height - 2 * margin))
    card_left = width - margin - card_width
    card_top = margin

    overlay = canvas.copy()
    panel_width = min(int(310 * scale), max(1, card_left - 2 * margin))
    panel_height = min(int(82 * scale), max(1, height - 2 * margin))
    _filled_rounded_rect(
        overlay, margin, margin, margin + panel_width, margin + panel_height,
        max(4, int(10 * scale)), (16, 22, 30),
    )
    _filled_rounded_rect(
        overlay, card_left, card_top, width - margin, card_top + card_height,
        max(5, int(14 * scale)), (10, 50, 63),
    )
    cv2.addWeighted(overlay, 0.80, canvas, 0.20, 0, canvas)

    accent = (56, 220, 255)
    cv2.rectangle(
        canvas, (card_left, card_top), (width - margin, card_top + card_height),
        accent, max(1, int(2 * scale)), cv2.LINE_AA,
    )
    for index, text in enumerate(lines):
        cv2.putText(
            canvas, text,
            (margin + int(10 * scale), margin + int((23 + index * 22) * scale)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55 * scale, (240, 245, 250),
            max(1, int(1.5 * scale)), cv2.LINE_AA,
        )

    label = "SQUATS"
    label_scale = 0.48 * scale
    label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, label_scale, 1)[0]
    label_x = card_left + max(2, (card_width - label_size[0]) // 2)
    cv2.putText(
        canvas, label, (label_x, card_top + int(25 * scale)),
        cv2.FONT_HERSHEY_SIMPLEX, label_scale, (190, 225, 232),
        max(1, int(scale)), cv2.LINE_AA,
    )
    count_text = str(int(state.get("count") or 0))
    count_scale = 2.15 * scale
    count_thickness = max(2, int(4 * scale))
    count_size = cv2.getTextSize(
        count_text, cv2.FONT_HERSHEY_DUPLEX, count_scale, count_thickness,
    )[0]
    count_x = card_left + max(2, (card_width - count_size[0]) // 2)
    count_y = card_top + min(card_height - int(12 * scale), int(91 * scale))
    cv2.putText(
        canvas, count_text, (count_x, count_y), cv2.FONT_HERSHEY_DUPLEX,
        count_scale, (255, 255, 255), count_thickness, cv2.LINE_AA,
    )
    return canvas


def process_squat_video(estimator, src_path, dst_path, config: SquatConfig, progress_cb=None):
    """Analyze one video and write an annotated MP4."""
    from inference import _open_h264, _write_bgr

    source = cv2.VideoCapture(str(src_path))
    if not source.isOpened():
        source.release()
        raise ValueError("failed to open input video")
    fps = float(source.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0:
        fps = 25.0
    width = int(source.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(source.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    total = int(source.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if width <= 0 or height <= 0:
        source.release()
        raise ValueError("input video has invalid dimensions")
    Path(dst_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        writer, encoded_width, encoded_height = _open_h264(
            str(dst_path), fps, width, height,
        )
    except Exception:
        source.release()
        raise

    counter = SquatCounter(config)
    processed = 0
    rep_timestamps = []
    started = time.perf_counter()
    try:
        while True:
            ok, frame = source.read()
            if not ok:
                break
            timestamp = processed / fps
            state = counter.update(estimator.infer(frame), timestamp)
            if state["completedRep"]:
                rep_timestamps.append(round(timestamp, 3))
            _write_bgr(
                writer,
                annotate_squat_frame(frame, state),
                encoded_width,
                encoded_height,
            )
            processed += 1
            if progress_cb is not None:
                progress_cb(processed, total)
    finally:
        source.release()
        writer.close()

    elapsed = max(time.perf_counter() - started, 1e-9)
    summary = counter.snapshot()
    return {
        "frames": processed,
        "count": summary["count"],
        "repTimestamps": rep_timestamps,
        "fps": fps,
        "processedFps": processed / elapsed,
        "durationSeconds": processed / fps,
        "activeSeconds": summary["activeSeconds"],
        "minKneeAngle": summary["minKneeAngle"],
        "averageKneeAngle": summary["averageKneeAngle"],
    }
