"""手部关键点估计与 0-9 手势识别（OpenCV Zoo MediaPipe 双模型，cv2.dnn 推理）。

管线：MPPalmDet（192 输入，SSD anchors）检手掌 → 按掌心 7 点旋转对齐裁剪 →
MPHandPose（224 输入）回归 21 关键点 + 左右手 + 置信度 →
角度法数伸直手指（0-5）+ Zoo GestureClassification 识别 0-9（含中式单手 6-9）。

前后处理移植自 opencv_zoo（Apache-2.0）：
- models/palm_detection_mediapipe/mp_palmdet.py
- models/handpose_estimation_mediapipe/mp_handpose.py
- models/handpose_estimation_mediapipe/demo.py（GestureClassification）
anchors 为规则 SSD 网格（24×24×2 + 12×12×6），程序生成。
"""
from __future__ import annotations

import os
import threading
from typing import Any

import cv2
import numpy as np

PALM_MODEL_FILE = "palm_detection_mediapipe_2023feb.onnx"
HANDPOSE_MODEL_FILE = "handpose_estimation_mediapipe_2023feb.onnx"

# 21 关键点连线（MediaPipe Hands 拓扑）
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),          # 拇指
    (0, 5), (5, 6), (6, 7), (7, 8),          # 食指
    (5, 9), (9, 10), (10, 11), (11, 12),     # 中指
    (9, 13), (13, 14), (14, 15), (15, 16),   # 无名指
    (13, 17), (17, 18), (18, 19), (19, 20),  # 小指
    (0, 17),
]
# 按指配色（BGR）：拇指紫/食指黄/中指绿/无名指蓝/小指橙
FINGER_COLORS = {
    "thumb": (200, 0, 200), "index": (0, 200, 255), "middle": (0, 200, 0),
    "ring": (255, 120, 0), "pinky": (0, 120, 255),
}
_CONN_FINGER = ["thumb"] * 4 + ["index"] * 4 + ["middle"] * 4 + ["ring"] * 4 + ["pinky"] * 4 + ["pinky"]


def _gen_palm_anchors() -> np.ndarray:
    anchors = []
    for stride, count in [(8, 2), (16, 6)]:
        grid = 192 // stride
        for y in range(grid):
            for x in range(grid):
                for _ in range(count):
                    anchors.append([(x + 0.5) / grid, (y + 0.5) / grid])
    return np.array(anchors, dtype=np.float64)


class MPPalmDet:
    """手掌检测：输出 [x1,y1,x2,y2, 7×(x,y)掌部关键点, score]。"""

    def __init__(self, model_path: str, nms_threshold=0.3, score_threshold=0.5, top_k=5000):
        self.nms_threshold = nms_threshold
        self.score_threshold = score_threshold
        self.top_k = top_k
        self.input_size = np.array([192, 192])  # wh
        self.model = cv2.dnn.readNet(model_path)
        self.anchors = _gen_palm_anchors()

    def _preprocess(self, image):
        pad_bias = np.array([0.0, 0.0])  # left, top
        ratio = min(self.input_size / image.shape[:2])
        if image.shape[0] != self.input_size[0] or image.shape[1] != self.input_size[1]:
            ratio_size = (np.array(image.shape[:2]) * ratio).astype(np.int32)
            image = cv2.resize(image, (ratio_size[1], ratio_size[0]))
            pad_h = self.input_size[0] - ratio_size[0]
            pad_w = self.input_size[1] - ratio_size[1]
            pad_bias[0] = left = pad_w // 2
            pad_bias[1] = top = pad_h // 2
            image = cv2.copyMakeBorder(image, top, pad_h - top, left, pad_w - left,
                                       cv2.BORDER_CONSTANT, None, (0, 0, 0))
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        pad_bias = (pad_bias / ratio).astype(np.int32)
        return image[np.newaxis, :, :, :], pad_bias

    def infer(self, image):
        h, w = image.shape[:2]
        input_blob, pad_bias = self._preprocess(image)
        self.model.setInput(input_blob)
        output_blob = self.model.forward(self.model.getUnconnectedOutLayersNames())
        return self._postprocess(output_blob, np.array([w, h]), pad_bias)

    def _postprocess(self, output_blob, original_shape, pad_bias):
        score = output_blob[1][0, :, 0].astype(np.float64)
        box_delta = output_blob[0][0, :, 0:4]
        landmark_delta = output_blob[0][0, :, 4:]
        scale = max(original_shape)
        score = 1 / (1 + np.exp(-score))

        cxy_delta = box_delta[:, :2] / self.input_size
        wh_delta = box_delta[:, 2:] / self.input_size
        xy1 = (cxy_delta - wh_delta / 2 + self.anchors) * scale
        xy2 = (cxy_delta + wh_delta / 2 + self.anchors) * scale
        boxes = np.concatenate([xy1, xy2], axis=1)
        boxes -= [pad_bias[0], pad_bias[1], pad_bias[0], pad_bias[1]]

        keep_idx = cv2.dnn.NMSBoxes(boxes, score, self.score_threshold, self.nms_threshold, top_k=self.top_k)
        if len(keep_idx) == 0:
            return np.empty(shape=(0, 19))
        selected_score = score[keep_idx]
        selected_box = boxes[keep_idx]
        selected_landmarks = landmark_delta[keep_idx].reshape(-1, 7, 2) / self.input_size
        selected_anchors = self.anchors[keep_idx]
        for idx in range(len(selected_landmarks)):
            selected_landmarks[idx] += selected_anchors[idx]
        selected_landmarks *= scale
        selected_landmarks -= pad_bias
        return np.c_[selected_box.reshape(-1, 4), selected_landmarks.reshape(-1, 14), selected_score.reshape(-1, 1)]


class MPHandPose:
    """手部 21 关键点：输入原图 + palm 检测行，输出 [bbox4, 21×3 屏幕系, 21×3 世界系, handedness, conf]。"""

    PALM_LANDMARKS_INDEX_OF_PALM_BASE = 0
    PALM_LANDMARKS_INDEX_OF_MIDDLE_FINGER_BASE = 2
    PALM_BOX_PRE_SHIFT_VECTOR = [0, 0]
    PALM_BOX_PRE_ENLARGE_FACTOR = 4
    PALM_BOX_SHIFT_VECTOR = [0, -0.4]
    PALM_BOX_ENLARGE_FACTOR = 3
    HAND_BOX_SHIFT_VECTOR = [0, -0.1]
    HAND_BOX_ENLARGE_FACTOR = 1.65

    def __init__(self, model_path: str, conf_threshold=0.8):
        self.conf_threshold = conf_threshold
        self.input_size = np.array([224, 224])
        self.model = cv2.dnn.readNet(model_path)

    def _crop_and_pad_from_palm(self, image, palm_bbox, for_rotation=False):
        wh_palm_bbox = palm_bbox[1] - palm_bbox[0]
        shift_vector = (self.PALM_BOX_PRE_SHIFT_VECTOR if for_rotation else self.PALM_BOX_SHIFT_VECTOR) * wh_palm_bbox
        palm_bbox = palm_bbox + shift_vector
        center = np.sum(palm_bbox, axis=0) / 2
        wh_palm_bbox = palm_bbox[1] - palm_bbox[0]
        enlarge = self.PALM_BOX_PRE_ENLARGE_FACTOR if for_rotation else self.PALM_BOX_ENLARGE_FACTOR
        half = wh_palm_bbox * enlarge / 2
        palm_bbox = np.array([center - half, center + half]).astype(np.int32)
        palm_bbox[:, 0] = np.clip(palm_bbox[:, 0], 0, image.shape[1])
        palm_bbox[:, 1] = np.clip(palm_bbox[:, 1], 0, image.shape[0])
        image = image[palm_bbox[0][1]:palm_bbox[1][1], palm_bbox[0][0]:palm_bbox[1][0], :]
        side_len = np.linalg.norm(image.shape[:2]) if for_rotation else max(image.shape[:2])
        side_len = int(side_len)
        pad_h = side_len - image.shape[0]
        pad_w = side_len - image.shape[1]
        left = pad_w // 2
        top = pad_h // 2
        image = cv2.copyMakeBorder(image, top, pad_h - top, left, pad_w - left,
                                   cv2.BORDER_CONSTANT, None, (0, 0, 0))
        bias = palm_bbox[0] - [left, top]
        return image, palm_bbox, bias

    def _preprocess(self, image, palm):
        pad_bias = np.array([0, 0], dtype=np.int32)
        palm_bbox = palm[0:4].reshape(2, 2)
        image, palm_bbox, bias = self._crop_and_pad_from_palm(image, palm_bbox, True)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pad_bias += bias

        palm_bbox = palm_bbox - pad_bias
        palm_landmarks = palm[4:18].reshape(7, 2) - pad_bias
        p1 = palm_landmarks[self.PALM_LANDMARKS_INDEX_OF_PALM_BASE]
        p2 = palm_landmarks[self.PALM_LANDMARKS_INDEX_OF_MIDDLE_FINGER_BASE]
        radians = np.pi / 2 - np.arctan2(-(p2[1] - p1[1]), p2[0] - p1[0])
        radians = radians - 2 * np.pi * np.floor((radians + np.pi) / (2 * np.pi))
        angle = np.rad2deg(radians)
        center_palm_bbox = np.sum(palm_bbox, axis=0) / 2
        rotation_matrix = cv2.getRotationMatrix2D(center_palm_bbox, angle, 1.0)
        rotated_image = cv2.warpAffine(image, rotation_matrix, (image.shape[1], image.shape[0]))
        homogeneous_coord = np.c_[palm_landmarks, np.ones(palm_landmarks.shape[0])]
        rotated_palm_landmarks = np.array([
            np.dot(homogeneous_coord, rotation_matrix[0]),
            np.dot(homogeneous_coord, rotation_matrix[1])])
        rotated_palm_bbox = np.array([
            np.amin(rotated_palm_landmarks, axis=1),
            np.amax(rotated_palm_landmarks, axis=1)])
        crop, rotated_palm_bbox, _ = self._crop_and_pad_from_palm(rotated_image, rotated_palm_bbox)
        blob = cv2.resize(crop, dsize=tuple(self.input_size), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        return blob[np.newaxis, :, :, :], rotated_palm_bbox, angle, rotation_matrix, pad_bias

    def infer(self, image, palm):
        input_blob, rotated_palm_bbox, angle, rotation_matrix, pad_bias = self._preprocess(image, palm)
        self.model.setInput(input_blob)
        output_blob = self.model.forward(self.model.getUnconnectedOutLayersNames())
        return self._postprocess(output_blob, rotated_palm_bbox, angle, rotation_matrix, pad_bias)

    def _postprocess(self, blob, rotated_palm_bbox, angle, rotation_matrix, pad_bias):
        landmarks, conf, handedness, landmarks_word = blob
        conf = float(conf[0][0])
        if conf < self.conf_threshold:
            return None
        landmarks = landmarks[0].reshape(-1, 3).astype(np.float64)
        landmarks_word = landmarks_word[0].reshape(-1, 3).astype(np.float64)

        wh_rotated_palm_bbox = rotated_palm_bbox[1] - rotated_palm_bbox[0]
        scale_factor = wh_rotated_palm_bbox / self.input_size
        landmarks[:, :2] = (landmarks[:, :2] - self.input_size / 2) * max(scale_factor)
        landmarks[:, 2] = landmarks[:, 2] * max(scale_factor)
        coords_rotation_matrix = cv2.getRotationMatrix2D((0, 0), angle, 1.0)
        rotated_landmarks = np.dot(landmarks[:, :2], coords_rotation_matrix[:, :2])
        rotated_landmarks = np.c_[rotated_landmarks, landmarks[:, 2]]
        rotated_landmarks_world = np.dot(landmarks_word[:, :2], coords_rotation_matrix[:, :2])
        rotated_landmarks_world = np.c_[rotated_landmarks_world, landmarks_word[:, 2]]

        rotation_component = np.array([
            [rotation_matrix[0][0], rotation_matrix[1][0]],
            [rotation_matrix[0][1], rotation_matrix[1][1]]])
        translation_component = np.array([rotation_matrix[0][2], rotation_matrix[1][2]])
        inverted_translation = np.array([
            -np.dot(rotation_component[0], translation_component),
            -np.dot(rotation_component[1], translation_component)])
        inverse_rotation_matrix = np.c_[rotation_component, inverted_translation]
        center = np.append(np.sum(rotated_palm_bbox, axis=0) / 2, 1)
        original_center = np.array([
            np.dot(center, inverse_rotation_matrix[0]),
            np.dot(center, inverse_rotation_matrix[1])])
        landmarks[:, :2] = rotated_landmarks[:, :2] + original_center + pad_bias

        bbox = np.array([np.amin(landmarks[:, :2], axis=0), np.amax(landmarks[:, :2], axis=0)])
        wh_bbox = bbox[1] - bbox[0]
        bbox = bbox + self.HAND_BOX_SHIFT_VECTOR * wh_bbox
        center_bbox = np.sum(bbox, axis=0) / 2
        wh_bbox = bbox[1] - bbox[0]
        half = wh_bbox * self.HAND_BOX_ENLARGE_FACTOR / 2
        bbox = np.array([center_bbox - half, center_bbox + half])
        return np.r_[bbox.reshape(-1), landmarks.reshape(-1),
                     rotated_landmarks_world.reshape(-1), float(handedness[0][0]), conf]


# ── 数手指（角度法，方向无关）────────────────────────────────
_FINGER_JOINTS = {
    "index": (5, 6, 8),   # MCP, PIP, TIP
    "middle": (9, 10, 12),
    "ring": (13, 14, 16),
    "pinky": (17, 18, 20),
}


def _angle_deg(v1, v2) -> float:
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return 180.0
    cos = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
    return float(np.degrees(np.arccos(cos)))


def count_fingers(landmarks: np.ndarray) -> dict[str, Any]:
    """21×(x,y[,z]) 屏幕坐标 → 每指是否伸直 + 伸直手指数（0-5）。

    四指：PIP 处弯曲角（MCP→PIP vs PIP→TIP）< 60° 且指尖远于 PIP（相对手腕）。
    拇指：IP 处弯曲角 < 50° 且指尖相对小指根距离大于拇指 MCP（张开判定）。
    """
    pts = np.asarray(landmarks, dtype=np.float64)[:, :2]
    wrist = pts[0]
    fingers: dict[str, bool] = {}
    for name, (mcp, pip, tip) in _FINGER_JOINTS.items():
        bend = _angle_deg(pts[pip] - pts[mcp], pts[tip] - pts[pip])
        farther = np.linalg.norm(pts[tip] - wrist) > np.linalg.norm(pts[pip] - wrist)
        fingers[name] = bool(bend < 60.0 and farther)
    thumb_bend = _angle_deg(pts[3] - pts[2], pts[4] - pts[3])
    thumb_open = np.linalg.norm(pts[4] - pts[17]) > np.linalg.norm(pts[2] - pts[17]) * 1.1
    fingers["thumb"] = bool(thumb_bend < 50.0 and thumb_open)
    count = int(sum(fingers.values()))
    return {"fingers": fingers, "count": count}


# ── 0-9 手势分类（移植自 opencv_zoo handpose demo GestureClassification）──
# 中式单手数：
#   0 拳  1 食指  2 食+中  3 食+中+无  4 四指  5 五指张开
#   6 拇+小（电话）  7 拇+食（枪形）  8 拇+食+中  9 拇+食+中+无
_GESTURE_DIGIT = {
    "Zero": 0, "One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5,
    "Six": 6, "Seven": 7, "Eight": 8, "Nine": 9,
}
_GESTURE_ZH = {
    "Zero": "零（拳）", "One": "一", "Two": "二", "Three": "三", "Four": "四", "Five": "五",
    "Six": "六（拇+小）", "Seven": "七（拇+食）", "Eight": "八（拇+食+中）",
    "Nine": "九（拇+食+中+无）", "Undefined": "未识别",
}


class GestureClassification:
    """OpenCV Zoo MediaPipe Handpose demo 同款 0-9 分类（Apache-2.0）。"""

    def _vector_2_angle(self, v1, v2) -> float:
        n1 = np.linalg.norm(v1)
        n2 = np.linalg.norm(v2)
        if n1 < 1e-6 or n2 < 1e-6:
            return 180.0
        cos = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
        return float(np.degrees(np.arccos(cos)))

    def _hand_angle(self, hand: np.ndarray) -> list[float]:
        """五指弯曲角：拇指 wrist→IP vs DIP→TIP；其余 wrist→PIP vs DIP→TIP。"""
        pairs = (
            ((0, 2), (3, 4)),    # thumb
            ((0, 6), (7, 8)),    # index
            ((0, 10), (11, 12)), # middle
            ((0, 14), (15, 16)), # ring
            ((0, 18), (19, 20)), # pinky
        )
        out = []
        for (a, b), (c, d) in pairs:
            out.append(self._vector_2_angle(
                np.array([hand[a][0] - hand[b][0], hand[a][1] - hand[b][1]]),
                np.array([hand[c][0] - hand[d][0], hand[c][1] - hand[d][1]]),
            ))
        return out

    def _finger_status(self, lm_list: np.ndarray) -> list[bool]:
        """指尖相对手腕是否比参考关节更远 → 伸直。"""
        originx, originy = lm_list[0]
        keypoint_list = [[5, 4], [6, 8], [10, 12], [14, 16], [18, 20]]  # thumb用MCP vs tip
        finger_list = []
        for p0, p1 in keypoint_list:
            x1, y1 = lm_list[p0]
            x2, y2 = lm_list[p1]
            farther = np.hypot(x2 - originx, y2 - originy) > np.hypot(x1 - originx, y1 - originy)
            finger_list.append(bool(farther))
        return finger_list

    def _classify(self, hand: np.ndarray) -> str:
        thr_angle = 65.0
        thr_angle_thumb = 30.0
        thr_angle_s = 49.0
        gesture_str = "Undefined"

        angle_list = self._hand_angle(hand)
        thumb_open, first_open, second_open, third_open, fourth_open = self._finger_status(hand)

        # 0 拳
        if (angle_list[0] > thr_angle_thumb) and (angle_list[1] > thr_angle) and (angle_list[2] > thr_angle) and (
                angle_list[3] > thr_angle) and (angle_list[4] > thr_angle) and \
                (not first_open) and (not second_open) and (not third_open) and (not fourth_open):
            gesture_str = "Zero"
        # 1 食指
        elif (angle_list[0] > thr_angle_thumb) and (angle_list[1] < thr_angle_s) and (angle_list[2] > thr_angle) and (
                angle_list[3] > thr_angle) and (angle_list[4] > thr_angle) and \
                first_open and (not second_open) and (not third_open) and (not fourth_open):
            gesture_str = "One"
        # 2 食+中
        elif (angle_list[0] > thr_angle_thumb) and (angle_list[1] < thr_angle_s) and (angle_list[2] < thr_angle_s) and (
                angle_list[3] > thr_angle) and (angle_list[4] > thr_angle) and \
                (not thumb_open) and first_open and second_open and (not third_open) and (not fourth_open):
            gesture_str = "Two"
        # 3 食+中+无
        elif (angle_list[0] > thr_angle_thumb) and (angle_list[1] < thr_angle_s) and (angle_list[2] < thr_angle_s) and (
                angle_list[3] < thr_angle_s) and (angle_list[4] > thr_angle) and \
                (not thumb_open) and first_open and second_open and third_open and (not fourth_open):
            gesture_str = "Three"
        # 4 四指
        elif (angle_list[0] > thr_angle_thumb) and (angle_list[1] < thr_angle_s) and (angle_list[2] < thr_angle_s) and (
                angle_list[3] < thr_angle_s) and (angle_list[4] < thr_angle) and \
                first_open and second_open and third_open and fourth_open:
            gesture_str = "Four"
        # 5 五指
        elif (angle_list[0] < thr_angle_s) and (angle_list[1] < thr_angle_s) and (angle_list[2] < thr_angle_s) and (
                angle_list[3] < thr_angle_s) and (angle_list[4] < thr_angle_s) and \
                thumb_open and first_open and second_open and third_open and fourth_open:
            gesture_str = "Five"
        # 6 拇+小（中式）
        elif (angle_list[0] < thr_angle_s) and (angle_list[1] > thr_angle) and (angle_list[2] > thr_angle) and (
                angle_list[3] > thr_angle) and (angle_list[4] < thr_angle_s) and \
                thumb_open and (not first_open) and (not second_open) and (not third_open) and fourth_open:
            gesture_str = "Six"
        # 7 拇+食（中式）
        elif (angle_list[0] < thr_angle_s) and (angle_list[1] < thr_angle) and (angle_list[2] > thr_angle) and (
                angle_list[3] > thr_angle) and (angle_list[4] > thr_angle_s) and \
                thumb_open and first_open and (not second_open) and (not third_open) and (not fourth_open):
            gesture_str = "Seven"
        # 8 拇+食+中
        elif (angle_list[0] < thr_angle_s) and (angle_list[1] < thr_angle) and (angle_list[2] < thr_angle) and (
                angle_list[3] > thr_angle) and (angle_list[4] > thr_angle_s) and \
                thumb_open and first_open and second_open and (not third_open) and (not fourth_open):
            gesture_str = "Eight"
        # 9 拇+食+中+无
        elif (angle_list[0] < thr_angle_s) and (angle_list[1] < thr_angle) and (angle_list[2] < thr_angle) and (
                angle_list[3] < thr_angle) and (angle_list[4] > thr_angle_s) and \
                thumb_open and first_open and second_open and third_open and (not fourth_open):
            gesture_str = "Nine"

        return gesture_str

    def classify(self, landmarks: np.ndarray) -> dict[str, Any]:
        hand = np.asarray(landmarks, dtype=np.float64)[:21, :2]
        gesture = self._classify(hand)
        digit = _GESTURE_DIGIT.get(gesture)
        return {
            "gesture": gesture,
            "gestureZh": _GESTURE_ZH.get(gesture, "未识别"),
            "digit": digit,
        }


_gesture_clf = GestureClassification()


def classify_gesture(landmarks: np.ndarray) -> dict[str, Any]:
    """21 关键点 → {gesture, gestureZh, digit}（digit 为 0-9 或 None）。"""
    return _gesture_clf.classify(landmarks)


# ── 引擎（模型缓存）──────────────────────────────────────────
_engines: dict[str, tuple[MPPalmDet, MPHandPose]] = {}
_lock = threading.Lock()


def get_engine(model_dir: str, *, palm_score=0.5, hand_conf=0.8) -> tuple[MPPalmDet, MPHandPose]:
    palm_path = os.path.join(model_dir, PALM_MODEL_FILE)
    hand_path = os.path.join(model_dir, HANDPOSE_MODEL_FILE)
    for p in (palm_path, hand_path):
        if not os.path.isfile(p):
            raise FileNotFoundError(f"缺少模型文件：{p}")
    key = f"{model_dir}|{palm_score}|{hand_conf}"
    with _lock:
        eng = _engines.get(key)
        if eng is None:
            eng = (MPPalmDet(palm_path, score_threshold=palm_score), MPHandPose(hand_path, conf_threshold=hand_conf))
            _engines[key] = eng
        return eng


def detect_hands(img_bgr: np.ndarray, model_dir: str, *, palm_score=0.5, hand_conf=0.8,
                 max_hands=2) -> list[dict[str, Any]]:
    """整图 → 手列表：bbox / 21 关键点 / 左右手 / 置信度 / 每指状态 / 伸直数 / 0-9 手势。"""
    palm_det, hand_pose = get_engine(model_dir, palm_score=palm_score, hand_conf=hand_conf)
    with _lock:  # cv2.dnn.Net 非线程安全
        palms = palm_det.infer(img_bgr)
        hands: list[dict[str, Any]] = []
        for palm in palms[:max_hands]:
            r = hand_pose.infer(img_bgr, palm)
            if r is None:
                continue
            bbox = r[0:4]
            lm = r[4:67].reshape(21, 3)
            handedness = float(r[130])
            conf = float(r[131])
            fc = count_fingers(lm)
            gs = classify_gesture(lm)
            # digit：优先 Zoo 0-9；未识别时回退伸直手指数（0-5）
            digit = gs["digit"] if gs["digit"] is not None else fc["count"]
            hands.append({
                "bbox": [round(float(v), 1) for v in bbox],
                "landmarks": [[round(float(x), 1), round(float(y), 1), round(float(z), 2)] for x, y, z in lm],
                "handedness": "Right" if handedness > 0.5 else "Left",
                "confidence": round(conf, 4),
                "fingers": fc["fingers"],
                "count": fc["count"],
                "gesture": gs["gesture"],
                "gestureZh": gs["gestureZh"],
                "digit": digit,
            })
    return hands


def primary_digit(hands: list[dict[str, Any]]) -> int | None:
    """取置信度最高的那只手的 digit（单手 0-9）；无手返回 None。"""
    if not hands:
        return None
    best = max(hands, key=lambda h: float(h.get("confidence") or 0))
    d = best.get("digit")
    return int(d) if d is not None else None


def _hand_center_x(hand: dict[str, Any]) -> float:
    """手在画面中的水平位置（bbox 中心，缺省用腕关节 x）。"""
    bbox = hand.get("bbox") or []
    if len(bbox) >= 4:
        return (float(bbox[0]) + float(bbox[2])) / 2.0
    lm = hand.get("landmarks") or []
    if lm:
        return float(lm[0][0])
    return 0.0


def _digit_of(hand: dict[str, Any]) -> int | None:
    d = hand.get("digit")
    return int(d) if d is not None else None


def resolve_handedness(hands: list[dict[str, Any]], *, swap_labels: bool = True) -> list[dict[str, Any]]:
    """校正左右手标签，避免双手显示只剩一侧数字。

    MediaPipe Handpose 默认假设输入为自拍镜像图；浏览器摄像头帧通常未水平翻转，
    因此在已区分左右时默认对模型标签做 Left↔Right 交换。
    若双手仍同侧（常见误检成两只 Right），再按画面位置分配：
    未镜像正对镜头时，画面右侧≈使用者左手、画面左侧≈使用者右手。
    """
    if not hands:
        return hands
    out = [dict(h) for h in hands]

    sides = {h.get("handedness") for h in out}
    distinct = "Left" in sides and "Right" in sides

    if distinct and swap_labels:
        for h in out:
            side = h.get("handedness")
            if side == "Left":
                h["handedness"] = "Right"
            elif side == "Right":
                h["handedness"] = "Left"
        return out

    if len(out) < 2 or distinct:
        return out

    # 同侧或缺失：取置信度最高的两只，按画面 x 赋左右（自拍未镜像）
    top2 = sorted(out, key=lambda h: float(h.get("confidence") or 0), reverse=True)[:2]
    top2_x = sorted(top2, key=_hand_center_x)
    # 画面左 → 使用者右手；画面右 → 使用者左手
    top2_x[0]["handedness"] = "Right"
    top2_x[1]["handedness"] = "Left"
    return out


def _best_digit_on_side(hands: list[dict[str, Any]], side: str) -> int | None:
    """同一侧多只手时取置信度最高者的 digit。"""
    group = [h for h in hands if h.get("handedness") == side]
    if not group:
        return None
    best = max(group, key=lambda h: float(h.get("confidence") or 0))
    return _digit_of(best)


def format_display_digits(hands: list[dict[str, Any]]) -> dict[str, Any]:
    """组合显示：双手为「左.右」（如 1.2），单手仅显示该手数字。

    先 resolve_handedness；若仍无法凑齐左右，则对置信度最高的两只手按画面位置回退组合。
    """
    if not hands:
        return {"displayText": None, "leftDigit": None, "rightDigit": None}

    left_d = _best_digit_on_side(hands, "Left")
    right_d = _best_digit_on_side(hands, "Right")
    if left_d is not None and right_d is not None:
        return {"displayText": f"{left_d}.{right_d}", "leftDigit": left_d, "rightDigit": right_d}

    if len(hands) >= 2:
        top2 = sorted(hands, key=lambda h: float(h.get("confidence") or 0), reverse=True)[:2]
        top2_x = sorted(top2, key=_hand_center_x)
        # 与 resolve_handedness 自拍未镜像约定一致：右画面=左手，左画面=右手
        left_d = _digit_of(top2_x[1])
        right_d = _digit_of(top2_x[0])
        if left_d is not None and right_d is not None:
            return {"displayText": f"{left_d}.{right_d}", "leftDigit": left_d, "rightDigit": right_d}
        if left_d is not None:
            return {"displayText": str(left_d), "leftDigit": left_d, "rightDigit": None}
        if right_d is not None:
            return {"displayText": str(right_d), "leftDigit": None, "rightDigit": right_d}

    if left_d is not None:
        return {"displayText": str(left_d), "leftDigit": left_d, "rightDigit": None}
    if right_d is not None:
        return {"displayText": str(right_d), "leftDigit": None, "rightDigit": right_d}
    d = primary_digit(hands)
    return {
        "displayText": str(d) if d is not None else None,
        "leftDigit": None,
        "rightDigit": None,
    }


def draw_hands(img_bgr: np.ndarray, hands: list[dict[str, Any]]) -> np.ndarray:
    """骨架 + 0-9 手势标注（MediaPipe 风格：逐指彩色连线、红色关键点）。"""
    vis = img_bgr.copy()
    for hand in hands:
        pts = np.array([[int(p[0]), int(p[1])] for p in hand["landmarks"]])
        for (a, b), finger in zip(HAND_CONNECTIONS, _CONN_FINGER):
            cv2.line(vis, tuple(pts[a]), tuple(pts[b]), FINGER_COLORS[finger], 2, cv2.LINE_AA)
        for p in pts:
            cv2.circle(vis, tuple(p), 4, (0, 0, 255), -1, cv2.LINE_AA)
        x1, y1 = int(hand["bbox"][0]), int(hand["bbox"][1])
        dig = hand.get("digit")
        dig_s = str(dig) if dig is not None else "?"
        label = f"{hand['handedness']} {dig_s}"
        cv2.putText(vis, label, (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (0, 255, 255), 2, cv2.LINE_AA)
    return vis
