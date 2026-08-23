"""诊断 MTMC 测试视频：检测数、类别、跟踪 ID。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

import cv2
import numpy as np

VIDEOS = [
    os.path.join(ROOT, "..", "docs", "test_data", "video", "camera_recordings", "camera_192_168_8_71_20260820_094046.mp4"),
    os.path.join(ROOT, "..", "docs", "test_data", "video", "camera_recordings", "camera_192_168_8_81_20260820_094044.mp4"),
]


def find_model():
    from models import AiModel
    from app import create_app

    app = create_app()
    with app.app_context():
        m = AiModel.query.filter_by(model_key="yolo26n", status="0").first()
        if not m:
            m = AiModel.query.filter_by(task="object-detection", status="0").first()
        if not m or not m.file_path:
            return None, None
        upload = app.config["UPLOAD_FOLDER"]
        path = os.path.join(upload, m.file_path)
        if os.path.isdir(path):
            for name in ("yolo26n.pt", "yolo11n.pt", "best.pt"):
                p = os.path.join(path, name)
                if os.path.isfile(p):
                    return p, m.model_key
            for f in os.listdir(path):
                if f.endswith(".pt"):
                    return os.path.join(path, f), m.model_key
        return path if os.path.isfile(path) else None, m.model_key


def sample_frames(video_path, n=8):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frames = []
    for i in range(n):
        idx = int((i + 1) * max(total, 1) / (n + 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if ok:
            frames.append(frame)
    cap.release()
    return frames


def main():
    model_path, model_key = find_model()
    print("model:", model_path, model_key)
    if not model_path:
        print("NO MODEL")
        return

    from inference import _get_model, _yolo_predict_kwargs

    model = _get_model(model_path)
    names = model.names or {}

    for vp in VIDEOS:
        print("\n===", os.path.basename(vp), "===")
        if not os.path.isfile(vp):
            print("MISSING")
            continue
        frames = sample_frames(vp)
        for i, frame in enumerate(frames):
            kw = _yolo_predict_kwargs(conf=0.25)
            r = model.predict(frame, **kw)[0]
            persons, vehicles, others = 0, 0, []
            if r.boxes is not None:
                for b in r.boxes:
                    cid = int(b.cls[0])
                    cname = str(names.get(cid, cid))
                    conf = float(b.conf[0])
                    if cid == 0:
                        persons += 1
                    elif cid in (1, 2, 3, 5, 7):
                        vehicles += 1
                    else:
                        others.append((cname, conf))
            print(f"  frame#{i}: persons={persons} vehicles(coco1-7)={vehicles} other={others[:5]}")


if __name__ == "__main__":
    main()
