"""模拟 0~35s 交错 MTMC，检查 t=28/29 黑 sedan 是否同一 Global。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from scripts.eval_mtmc_cross_cam import (
    VIDEOS,
    EvalState,
    _vehicle_fuse_from_track,
    build_session,
    load_models,
    open_captures,
    run_interleaved_eval,
    resize_frame,
)
from services.mtmc_engine import _detect, _crop
from services.mtmc_local_track import create_local_tracker
from services.vehicle_reid_feat import cosine


def main():
    models = load_models()
    session = build_session(models, 2.0)
    eval_state = EvalState()
    caps, meta = open_captures()
    run_interleaved_eval(session, eval_state, caps, meta, models, dur=35.0, sample_fps=2.0, base_ts=1.7e9, t0=0)

    # t=28/29 帧上最大 car 的 embedding 对比
    from app import create_app
    from services.mtmc_engine import _detect as det_fn
    import cv2

    def frame_at(v, t):
        cap = caps[v["camera_id"]]
        fps = meta[v["camera_id"]]["fps"]
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, f = cap.read()
        if not ok:
            return None
        h, w = f.shape[:2]
        return cv2.resize(f, (640, max(1, int(h * 640 / w))))

    f71, f81 = frame_at(VIDEOS[0], 28), frame_at(VIDEOS[1], 29)
    det = models["det_person_path"]
    for tag, f, t in ("71", f71, 28), ("81", f81, 29):
        dets = det_fn(det, f, 0.28, [1, 2, 3, 5, 7])
        cars = [d for d in dets if d.get("className") == "car"] or dets
        d = max(cars, key=lambda x: (x["bbox"][2] - x["bbox"][0]) * (x["bbox"][3] - x["bbox"][1]))
        # 找 eval_state 中该时刻附近的 local track global
        print(f"cam{tag} t={t}s largest car conf={d['confidence']:.2f}")

    # 跨镜 globals
    cross = []
    for gid, cams in eval_state.global_cams.items():
        if len(cams) >= 2:
            g = session.associator.get_track(gid)
            if g and g.object_type == "vehicle":
                cross.append((gid, sorted(cams), g.plate, g.hit_count))
    print("vehicle cross globals:", len(cross))
    for row in cross:
        print(" ", row)

    # 检查 cam71/cam81 在 t=28~30 的 cross events
    for e in eval_state.cross_events:
        if e.get("objectType") == "vehicle" and e.get("transitSec", 99) <= 35:
            print("event", e)

    for cap in caps.values():
        cap.release()


if __name__ == "__main__":
    main()
