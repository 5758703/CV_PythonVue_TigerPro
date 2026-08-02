"""全局镜头运动估计：移动/手持镜头下的工位坐标补偿。

原理
----
逐帧用背景稀疏光流 (goodFeaturesToTrack + calcOpticalFlowPyrLK) 估计相邻帧的
全局相似变换 (estimateAffinePartial2D + RANSAC，可抗行人等局部运动)，
累计得到 C_i：把「帧 0 的归一化坐标」映射到「帧 i 的归一化坐标」。

任意参考帧 ref 上标注的点 P_ref，在当前帧 cur 的位置：

    P_cur = C_cur @ inv(C_ref) @ P_ref

所有矩阵都在归一化坐标空间 (x, y ∈ [0,1]) 表达，与分辨率无关；
前端拿到 profile 后可用同一公式在浏览器里补偿预览叠加层。
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

# 估计用的缩放边长：小图光流快且足够稳
_PROC_MAX_SIDE = 480
_MAX_CORNERS = 240
_MIN_PAIRS = 8


def _to_h3(m23: np.ndarray) -> np.ndarray:
    h = np.eye(3, dtype=np.float64)
    h[:2, :] = m23
    return h


def _norm_space(m_h3: np.ndarray, w: int, h: int) -> np.ndarray:
    """像素空间 3x3 仿射 -> 归一化坐标空间 3x3。"""
    s = np.diag([float(w), float(h), 1.0])
    return np.linalg.inv(s) @ m_h3 @ s


def matrix_to_row(m_h3: np.ndarray) -> list[float]:
    """3x3 -> [a, b, tx, c, d, ty]（行优先前两行）。"""
    return [float(m_h3[0, 0]), float(m_h3[0, 1]), float(m_h3[0, 2]),
            float(m_h3[1, 0]), float(m_h3[1, 1]), float(m_h3[1, 2])]


def row_to_matrix(row) -> np.ndarray:
    m = np.eye(3, dtype=np.float64)
    if row is not None and len(row) >= 6:
        m[0, :] = [float(row[0]), float(row[1]), float(row[2])]
        m[1, :] = [float(row[3]), float(row[4]), float(row[5])]
    return m


class CameraMotionEstimator:
    """逐帧喂 BGR 帧，返回归一化空间的累计变换 C_i (3x3)。"""

    def __init__(self) -> None:
        self._prev_gray: np.ndarray | None = None
        self._cum_px = np.eye(3, dtype=np.float64)  # 缩放图像素空间累计
        self._size: tuple[int, int] | None = None  # (w, h) 缩放图尺寸

    def _prep(self, frame_bgr: np.ndarray) -> np.ndarray:
        h, w = frame_bgr.shape[:2]
        scale = min(1.0, _PROC_MAX_SIDE / max(w, h))
        if scale < 1.0:
            frame_bgr = cv2.resize(frame_bgr, (int(round(w * scale)), int(round(h * scale))))
        return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

    def update(self, frame_bgr: np.ndarray) -> np.ndarray:
        gray = self._prep(frame_bgr)
        gh, gw = gray.shape[:2]
        if self._prev_gray is None or self._prev_gray.shape != gray.shape:
            self._prev_gray = gray
            self._cum_px = np.eye(3, dtype=np.float64)
            self._size = (gw, gh)
            return np.eye(3, dtype=np.float64)

        p0 = cv2.goodFeaturesToTrack(
            self._prev_gray, maxCorners=_MAX_CORNERS, qualityLevel=0.01,
            minDistance=8, blockSize=7,
        )
        step: np.ndarray | None = None
        if p0 is not None and len(p0) >= _MIN_PAIRS:
            p1, st, _err = cv2.calcOpticalFlowPyrLK(
                self._prev_gray, gray, p0, None,
                winSize=(21, 21), maxLevel=3,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
            )
            if p1 is not None and st is not None:
                mask = st.reshape(-1) == 1
                g0 = p0.reshape(-1, 2)[mask]
                g1 = p1.reshape(-1, 2)[mask]
                if len(g0) >= _MIN_PAIRS:
                    m23, _inliers = cv2.estimateAffinePartial2D(
                        g0, g1, method=cv2.RANSAC, ransacReprojThreshold=3.0,
                    )
                    if m23 is not None and np.all(np.isfinite(m23)):
                        step = _to_h3(m23)
        if step is not None:
            self._cum_px = step @ self._cum_px
        # step 估计失败（纹理不足/剧烈模糊）时沿用上一累计，视为该帧无相对运动
        self._prev_gray = gray
        return _norm_space(self._cum_px, self._size[0], self._size[1])


def compute_motion_profile(video_path: str, *, max_frames: int | None = None) -> dict[str, Any]:
    """整段视频的逐帧累计变换（归一化空间）。

    返回 {"fps": float, "count": int, "frames": [[a,b,tx,c,d,ty], ...]}，
    frames[i] 即 C_i。解码 + 小图光流，无模型推理，速度远快于检测。
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("无法打开视频")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25) or 25.0
    est = CameraMotionEstimator()
    frames: list[list[float]] = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            c = est.update(frame)
            frames.append([round(v, 8) for v in matrix_to_row(c)])
            if max_frames is not None and len(frames) >= max_frames:
                break
    finally:
        cap.release()
    return {"fps": fps, "count": len(frames), "frames": frames}


def ref_to_cur_matrix(c_ref: np.ndarray, c_cur: np.ndarray) -> np.ndarray:
    """参考帧 -> 当前帧的点变换矩阵（归一化空间）。"""
    try:
        return c_cur @ np.linalg.inv(c_ref)
    except np.linalg.LinAlgError:
        return np.eye(3, dtype=np.float64)


def warp_region_norm(region: list[list[float]] | None, c_ref: np.ndarray, c_cur: np.ndarray):
    """把归一化多边形从参考帧坐标搬到当前帧坐标；不裁剪（由下游 parse_region 裁剪）。"""
    if not region:
        return region
    m = ref_to_cur_matrix(c_ref, c_cur)
    out = []
    for p in region:
        x, y = float(p[0]), float(p[1])
        out.append([
            m[0, 0] * x + m[0, 1] * y + m[0, 2],
            m[1, 0] * x + m[1, 1] * y + m[1, 2],
        ])
    return out


def _polygon_area(pts: list[list[float]]) -> float:
    if not pts or len(pts) < 3:
        return 0.0
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _clip_half_plane(pts: list[list[float]], inside_fn, intersect_fn) -> list[list[float]]:
    out: list[list[float]] = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        ain, bin_ = inside_fn(a), inside_fn(b)
        if ain:
            out.append(a)
            if not bin_:
                out.append(intersect_fn(a, b))
        elif bin_:
            out.append(intersect_fn(a, b))
    return out


def visible_ratio(region_norm: list[list[float]] | None) -> float:
    """多边形与单位正方形 [0,1]² 的交集面积 / 原面积（Sutherland–Hodgman 裁剪）。

    工位被镜头“摇出画面”时用于暂停离岗计时。
    """
    if not region_norm or len(region_norm) < 3:
        return 0.0
    orig = _polygon_area(region_norm)
    if orig <= 1e-9:
        return 0.0
    pts = [list(map(float, p)) for p in region_norm]

    def lerp(a, b, t):
        return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]

    clips = [
        (lambda p: p[0] >= 0.0, lambda a, b: lerp(a, b, (0.0 - a[0]) / (b[0] - a[0]))),
        (lambda p: p[0] <= 1.0, lambda a, b: lerp(a, b, (1.0 - a[0]) / (b[0] - a[0]))),
        (lambda p: p[1] >= 0.0, lambda a, b: lerp(a, b, (0.0 - a[1]) / (b[1] - a[1]))),
        (lambda p: p[1] <= 1.0, lambda a, b: lerp(a, b, (1.0 - a[1]) / (b[1] - a[1]))),
    ]
    for inside_fn, intersect_fn in clips:
        if not pts:
            return 0.0
        pts = _clip_half_plane(pts, inside_fn, intersect_fn)
    if len(pts) < 3:
        return 0.0
    return min(1.0, _polygon_area(pts) / orig)


def profile_matrix_at(profile: dict[str, Any] | None, sec: float) -> np.ndarray:
    """按时间取最近帧的累计矩阵；profile 缺失时返回单位阵（等价不补偿）。"""
    if not profile or not profile.get("frames"):
        return np.eye(3, dtype=np.float64)
    fps = float(profile.get("fps") or 25) or 25.0
    idx = int(round(max(0.0, float(sec)) * fps))
    frames = profile["frames"]
    idx = min(idx, len(frames) - 1)
    return row_to_matrix(frames[idx])
