"""Deterministic single-person squat counting from normalized COCO-17 poses."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from statistics import median
from typing import Sequence


@dataclass(frozen=True)
class SquatConfig:
    keypoint_conf: float = 0.25
    standing_angle: float = 160.0
    bottom_angle: float = 100.0
    confirm_frames: int = 3
    lost_grace_seconds: float = 1.0
    smoothing_window: int = 5

    def __post_init__(self):
        if not 0 <= self.keypoint_conf <= 1:
            raise ValueError("keypoint_conf must be between 0 and 1")
        if not 0 < self.bottom_angle < self.standing_angle <= 180:
            raise ValueError("bottom_angle must be less than standing_angle")
        if self.confirm_frames < 1:
            raise ValueError("confirm_frames must be at least 1")
        if self.lost_grace_seconds < 0:
            raise ValueError("lost_grace_seconds must not be negative")
        if self.smoothing_window < 1:
            raise ValueError("smoothing_window must be at least 1")


def knee_angle(hip: Sequence[float], knee: Sequence[float], ankle: Sequence[float]):
    """Return the smaller hip-knee-ankle angle in degrees."""
    ax, ay = float(hip[0]) - float(knee[0]), float(hip[1]) - float(knee[1])
    bx, by = float(ankle[0]) - float(knee[0]), float(ankle[1]) - float(knee[1])
    length_a = math.hypot(ax, ay)
    length_b = math.hypot(bx, by)
    if length_a <= 1e-9 or length_b <= 1e-9:
        return None
    cosine = max(-1.0, min(1.0, (ax * bx + ay * by) / (length_a * length_b)))
    return math.degrees(math.acos(cosine))


def _bbox(person):
    value = person.get("bbox") if isinstance(person, dict) else None
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        x1, y1, x2, y2 = (float(value[index]) for index in range(4))
    except (TypeError, ValueError):
        return None
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None


def _leg_angle(person, indices, threshold):
    points = person.get("keypoints") if isinstance(person, dict) else None
    if not isinstance(points, (list, tuple)) or len(points) <= max(indices):
        return None
    selected = [points[index] for index in indices]
    if any(not isinstance(point, (list, tuple)) or len(point) < 3 for point in selected):
        return None
    try:
        if any(float(point[2]) < threshold for point in selected):
            return None
    except (TypeError, ValueError):
        return None
    return knee_angle(selected[0], selected[1], selected[2])


def leg_angle(person, config: SquatConfig):
    angles = [
        value for value in (
            _leg_angle(person, (11, 13, 15), config.keypoint_conf),
            _leg_angle(person, (12, 14, 16), config.keypoint_conf),
        ) if value is not None
    ]
    return sum(angles) / len(angles) if angles else None


def _area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


def _iou(first, second):
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = _area(first) + _area(second) - intersection
    return intersection / union if union > 0 else 0.0


def _continuity_score(box, previous):
    overlap = _iou(box, previous)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    px, py = (previous[0] + previous[2]) / 2, (previous[1] + previous[3]) / 2
    diagonal = max(1.0, math.hypot(previous[2] - previous[0], previous[3] - previous[1]))
    distance_score = max(0.0, 1.0 - math.hypot(cx - px, cy - py) / diagonal)
    size_score = min(_area(box), _area(previous)) / max(_area(box), _area(previous))
    return overlap * 4.0 + distance_score * 2.0 + size_score


def select_primary_person(persons, previous_bbox, config: SquatConfig):
    candidates = []
    for person in persons or []:
        box = _bbox(person)
        angle = leg_angle(person, config)
        if box is None or angle is None:
            continue
        base_score = math.log1p(_area(box))
        score = _continuity_score(box, previous_bbox) * 10.0 + base_score if previous_bbox else base_score
        candidates.append((score, person, box, angle))
    return max(candidates, key=lambda item: item[0]) if candidates else None


class SquatCounter:
    """Stateful squat counter for one primary person."""

    def __init__(self, config: SquatConfig | None = None):
        self.config = config or SquatConfig()
        self.count = 0
        self.stage = "waiting_stand"
        self.previous_bbox = None
        self.last_seen_at = None
        self.first_seen_at = None
        self.last_timestamp = None
        self._angles = deque(maxlen=self.config.smoothing_window)
        self._zone_streak = 0
        self._zone = None
        self._angle_sum = 0.0
        self._angle_samples = 0
        self._min_angle = None

    def _result(self, *, raw_angle=None, angle=None, status="tracking", completed=False, person=None):
        active = 0.0
        if self.first_seen_at is not None and self.last_timestamp is not None:
            active = max(0.0, self.last_timestamp - self.first_seen_at)
        return {
            "count": self.count,
            "stage": self.stage,
            "kneeAngle": angle,
            "rawKneeAngle": raw_angle,
            "trackingStatus": status,
            "activeSeconds": active,
            "minKneeAngle": self._min_angle,
            "averageKneeAngle": (
                self._angle_sum / self._angle_samples if self._angle_samples else None
            ),
            "completedRep": completed,
            "primaryPerson": person,
        }

    def snapshot(self):
        angle = median(self._angles) if self._angles else None
        status = "tracking" if self.last_seen_at is not None else "no_person"
        return self._result(angle=angle, status=status)

    def _observe_zone(self, zone):
        if zone == self._zone:
            self._zone_streak += 1
        else:
            self._zone = zone
            self._zone_streak = 1
        return self._zone_streak >= self.config.confirm_frames

    def _reset_partial(self):
        self.stage = "waiting_stand"
        self.previous_bbox = None
        self.last_seen_at = None
        self._angles.clear()
        self._zone = None
        self._zone_streak = 0

    def update(self, persons: list[dict], timestamp: float):
        timestamp = float(timestamp)
        if self.last_timestamp is not None and timestamp < self.last_timestamp:
            raise ValueError("timestamp must be monotonic")
        self.last_timestamp = timestamp
        selected = select_primary_person(persons, self.previous_bbox, self.config)
        if selected is None:
            if self.last_seen_at is not None and timestamp - self.last_seen_at > self.config.lost_grace_seconds:
                self._reset_partial()
            status = "temporarily_lost" if self.last_seen_at is not None else "no_person"
            return self._result(status=status)

        _, person, box, raw_angle = selected
        self.previous_bbox = box
        self.last_seen_at = timestamp
        if self.first_seen_at is None:
            self.first_seen_at = timestamp
        self._angles.append(raw_angle)
        angle = float(median(self._angles))
        self._angle_sum += angle
        self._angle_samples += 1
        self._min_angle = angle if self._min_angle is None else min(self._min_angle, angle)

        if angle >= self.config.standing_angle:
            zone = "stand"
        elif angle <= self.config.bottom_angle:
            zone = "bottom"
        else:
            zone = "transition"
        confirmed = self._observe_zone(zone)
        completed = False

        if self.stage == "waiting_stand":
            if zone == "stand" and confirmed:
                self.stage = "standing"
        elif self.stage == "standing":
            if zone == "transition":
                self.stage = "descending"
            elif zone == "bottom" and confirmed:
                self.stage = "bottom"
        elif self.stage == "descending":
            if zone == "bottom" and confirmed:
                self.stage = "bottom"
            elif zone == "stand" and confirmed:
                self.stage = "standing"
        elif self.stage == "bottom":
            if zone == "transition":
                self.stage = "ascending"
            elif zone == "stand" and confirmed:
                self.count += 1
                self.stage = "standing"
                completed = True
        elif self.stage == "ascending":
            if zone == "stand" and confirmed:
                self.count += 1
                self.stage = "standing"
                completed = True
            elif zone == "bottom" and confirmed:
                self.stage = "bottom"

        return self._result(
            raw_angle=raw_angle,
            angle=angle,
            status="tracking",
            completed=completed,
            person=person,
        )
