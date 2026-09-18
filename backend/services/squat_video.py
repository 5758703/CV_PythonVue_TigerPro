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
        f"SQUATS  {int(state.get('count') or 0)}",
        f"STAGE   {state.get('stage') or 'waiting_stand'}",
        f"KNEE    {angle_text}",
        f"STATUS  {state.get('trackingStatus') or 'no_person'}",
    )
    overlay = canvas.copy()
    cv2.rectangle(overlay, (8, 8), (310, 104), (16, 22, 30), -1)
    cv2.addWeighted(overlay, 0.78, canvas, 0.22, 0, canvas)
    for index, text in enumerate(lines):
        cv2.putText(canvas, text, (18, 30 + index * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 245, 250), 1, cv2.LINE_AA)
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
