"""手势识别视频处理：逐帧 MediaPipe / 中国手语，输出标注视频 + 稳定序列。"""
from __future__ import annotations

import os
from typing import Any, Callable

import cv2
import numpy as np

from services.handpose_multi import merge_estimate_results


def _draw_frame_bgr(img: np.ndarray, hands: list, detections: list) -> np.ndarray:
    """在帧上绘制骨架/检测框（不编码 base64）。"""
    from services.handpose import draw_hands

    vis = img.copy()
    if hands:
        vis = draw_hands(vis, hands)
    for d in detections or []:
        bbox = d.get("bbox") or []
        if len(bbox) < 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"{d.get('className', '?')} {float(d.get('confidence') or 0):.2f}"
        cv2.putText(vis, label, (x1, max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.65, (0, 255, 0), 2, cv2.LINE_AA)
    # 顶部显示当前组合结果
    return vis


def _overlay_banner(vis: np.ndarray, text: str | None) -> np.ndarray:
    if not text:
        return vis
    out = vis.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 36), (20, 20, 20), -1)
    cv2.putText(out, text[:64], (10, 26), cv2.FONT_HERSHEY_SIMPLEX,
                0.8, (0, 255, 255), 2, cv2.LINE_AA)
    return out


def run_frame_estimate(
    img: np.ndarray,
    *,
    selected: list[str],
    mediapipe_dir: str,
    csl_dir: str,
    palm_score: float = 0.5,
    hand_conf: float = 0.8,
    max_hands: int = 2,
    det_conf: float = 0.5,
) -> dict[str, Any]:
    """单帧估计（视频循环复用）。"""
    use_mp = "mediapipe" in selected
    use_csl = "csl-yolo11s" in selected
    mp_data = None
    csl_data = None

    if use_mp:
        from services.handpose import detect_hands, format_display_digits, primary_digit, resolve_handedness
        hands = detect_hands(
            img, mediapipe_dir,
            palm_score=palm_score, hand_conf=hand_conf, max_hands=max_hands,
        )
        hands = resolve_handedness(hands, swap_labels=True)
        disp = format_display_digits(hands)
        dig = primary_digit(hands)
        mp_data = {
            "recognizer": "mediapipe",
            "hands": hands,
            **disp,
            "primaryDigit": dig,
            "totalCount": int(dig) if dig is not None else 0,
            "extendedTotal": int(sum(h["count"] for h in hands)),
        }

    if use_csl:
        from services.sign_language import detect_sign_language
        csl_data = detect_sign_language(
            img, csl_dir, conf=det_conf, draw=False, mediapipe_dir=mediapipe_dir,
        )

    return merge_estimate_results(img, selected, mp_data, csl_data, draw=False)


def process_handpose_video(
    src_path: str,
    dst_path: str,
    *,
    selected: list[str],
    mediapipe_dir: str,
    csl_dir: str,
    palm_score: float = 0.5,
    hand_conf: float = 0.8,
    max_hands: int = 2,
    det_conf: float = 0.5,
    frame_stride: int = 2,
    stable_n: int = 3,
    progress_cb: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """逐帧手势识别并写出标注视频。

    frame_stride：每隔 N 帧推理一次（中间帧沿用上次叠加），默认 2 加速。
    stable_n：连续相同 displayText 达 N 次推理才记入序列。
    """
    from inference import _open_h264, _write_bgr

    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        raise ValueError("无法打开视频文件")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if w <= 0 or h <= 0:
        cap.release()
        raise ValueError("视频尺寸无效")

    stride = max(1, int(frame_stride or 1))
    need_n = max(1, int(stable_n or 1))
    writer, ew, eh = _open_h264(dst_path, fps, w, h)

    sequence: list[dict[str, Any]] = []
    last_token: str | None = None
    stable_token: str | None = None
    stable_cnt = 0
    frames = 0
    inferred = 0
    last_vis: np.ndarray | None = None
    last_display: str | None = None

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames += 1
            do_infer = ((frames - 1) % stride == 0) or last_vis is None

            if do_infer:
                inferred += 1
                data = run_frame_estimate(
                    frame,
                    selected=selected,
                    mediapipe_dir=mediapipe_dir,
                    csl_dir=csl_dir,
                    palm_score=palm_score,
                    hand_conf=hand_conf,
                    max_hands=max_hands,
                    det_conf=det_conf,
                )
                hands = data.get("hands") or []
                dets = data.get("detections") or []
                display = data.get("displayText")
                last_display = display if display not in (None, "") else None
                vis = _draw_frame_bgr(frame, hands, dets)
                vis = _overlay_banner(vis, last_display)
                last_vis = vis

                token = last_display
                if token == stable_token:
                    stable_cnt += 1
                else:
                    stable_token = token
                    stable_cnt = 1
                if token is None:
                    if stable_cnt >= need_n:
                        last_token = None
                elif stable_cnt == need_n and token != last_token:
                    last_token = token
                    sec = round((frames - 1) / max(fps, 1e-6), 2)
                    sequence.append({
                        "text": token,
                        "digitText": data.get("digitText"),
                        "signText": data.get("signText"),
                        "labelZh": data.get("labelZh"),
                        "frame": frames,
                        "sec": sec,
                    })
            else:
                # 非推理帧：仍画上帧结果条，骨架沿用最近一帧叠加再贴到当前帧太贵；
                # 仅贴 banner + 可选半透明提示，保持视频流畅。
                vis = frame.copy()
                if last_vis is not None and last_vis.shape[:2] == frame.shape[:2]:
                    # 轻量：只复用检测框层不合适，直接用上次全帧会画面跳动；改写当前帧 banner
                    vis = _overlay_banner(vis, last_display)
                else:
                    vis = _overlay_banner(vis, last_display)

            _write_bgr(writer, vis, ew, eh)
            if progress_cb and (frames % 3 == 0 or frames == total):
                progress_cb(frames, total or frames)
    finally:
        cap.release()
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass

    if progress_cb:
        progress_cb(frames, frames)

    return {
        "frames": frames,
        "inferredFrames": inferred,
        "fps": round(fps, 2),
        "width": w,
        "height": h,
        "frameStride": stride,
        "sequence": sequence,
        "sequenceText": " ".join(s["text"] for s in sequence),
        "recognizers": list(selected),
        "outputExists": os.path.isfile(dst_path),
    }
