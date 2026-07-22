"""抽样验证车牌 OCR（需在 backend 目录、Python 3.12 + rapidocr 1.4.4 环境运行）。"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import cv2

from inference import detect_image, paddle_ocr
from services.vehicle_track import (
    _plate_candidates,
    _ocr_plate,
    _plate_format_score,
)

VIDEO_PATH = BACKEND.parent / "docs/test_data/video/车辆行驶01.mp4"
VEHICLE_MODEL = BACKEND / "uploads/models/yolo26n/yolo26n.pt"
PLATE_MODEL = BACKEND / "uploads/models/yolov8-license-plate/best.pt"
DET_DIR = BACKEND / "uploads/models/PP-OCRv6_small_det_onnx"
REC_DIR = BACKEND / "uploads/models/PP-OCRv6_small_rec_onnx"
VEHICLE_CLASSES = {1, 2, 3, 5, 7}


def area(bb):
    x1, y1, x2, y2 = bb[:4]
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def main():
    cap = cv2.VideoCapture(str(VIDEO_PATH))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {VIDEO_PATH}")

    ocr_fn = lambda b: paddle_ocr(str(DET_DIR), str(REC_DIR), b, plate_mode=True)
    frames = [0, 10, 20, 30, 40, 50, 60, 80, 100, 150]
    hits = 0

    for idx in frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            print("frame", idx, "read_failed")
            continue

        ok2, buf = cv2.imencode(".jpg", frame)
        if not ok2:
            print("frame", idx, "encode_failed")
            continue

        det_res = detect_image(str(VEHICLE_MODEL), buf.tobytes(), conf=0.25, draw=False)
        dets = det_res.get("detections") or []
        vehicles = [d for d in dets if int(d.get("classId", -1)) in VEHICLE_CLASSES and d.get("bbox")]
        if not vehicles:
            print("frame", idx, "no_vehicle")
            continue

        best_vehicle = max(vehicles, key=lambda d: area(d["bbox"]))
        candidates = list(_plate_candidates(best_vehicle["bbox"], frame, str(PLATE_MODEL), 0.25))
        print("frame", idx, "vehicle_bbox", best_vehicle["bbox"], "candidates", len(candidates))

        best_text = ""
        best_rank = -1.0
        best_src = None
        for pb, src in candidates[:3]:
            res = _ocr_plate(ocr_fn, frame, pb)
            text = res.get("text") or ""
            score = float(res.get("score") or 0.0)
            fmt = _plate_format_score(text)
            rank = fmt * 0.65 + min(1.0, score) * 0.35
            print("  candidate", src, pb, repr(text), "score", score, "fmt", round(fmt, 2), "rank", round(rank, 2))
            if text and rank >= best_rank:
                best_text, best_rank, best_src = text, rank, src

        print("  => best", repr(best_text), "rank", round(best_rank, 2), best_src)
        if best_text:
            hits += 1

    cap.release()
    print("hits", hits, "of", len(frames))


if __name__ == "__main__":
    main()
