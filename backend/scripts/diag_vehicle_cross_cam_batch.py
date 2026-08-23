"""批量诊断用户截图中的跨镜车辆重识别（交错 MTMC 流 + 孤立关联）。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

import cv2

from app import create_app
from models import AiModel
from routes.mtmc import _abs_weight, _build_ocr_fn, _pick_model
from scripts.eval_mtmc_cross_cam import (
    EvalState,
    _record_track,
    _vehicle_fuse_from_track,
    build_session,
    load_models,
    open_captures,
    resize_frame,
)
from services.mtmc_associator import MtmcAssociator, AssocMode
from services.mtmc_engine import _detect, _crop, _sort_vehicle_tracks_for_assoc
from services.mtmc_local_track import create_local_tracker
from services.vehicle_reid_feat import extract_vehicle_embedding, fuse_plate_visual, cosine
from services.vehicle_track import _plate_candidates, _ocr_plate

P71 = os.path.join(
    ROOT, "..", "docs", "test_data", "video", "camera_recordings",
    "camera_192_168_8_71_20260820_094046.mp4",
)
P81 = os.path.join(
    ROOT, "..", "docs", "test_data", "video", "camera_recordings",
    "camera_192_168_8_81_20260820_094044.mp4",
)

# 用户截图用例：(名称, cam71秒, cam81秒, 优先类别)
CASES = [
    ("02-白色SUV", 37.0, 37.0, ["car", "suv"]),
    ("04-黑色sedan", 88.0, 89.0, ["car"]),
    ("05-蓝色货车", 126.0, 127.0, ["truck", "car"]),
    ("06-银色小卡", 145.0, 146.0, ["truck", "car"]),
]

VEHICLE_CLS = [1, 2, 3, 5, 7]
SAMPLE_FPS = 2.0


def load_frame(path: str, t: float, fps: float):
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
    ok, f = cap.read()
    cap.release()
    if not ok:
        return None
    h, w = f.shape[:2]
    return cv2.resize(f, (640, max(1, int(h * 640 / w))))


def _pick_det(dets, class_pref: list[str]):
    if not dets:
        return None
    for cn in class_pref:
        sub = [d for d in dets if d.get("className") == cn]
        if sub:
            return max(sub, key=lambda x: (x["bbox"][2] - x["bbox"][0]) * (x["bbox"][3] - x["bbox"][1]))
    return max(dets, key=lambda x: (x["bbox"][2] - x["bbox"][0]) * (x["bbox"][3] - x["bbox"][1]))


def ref_embedding(t71: float, t81: float, class_pref: list[str], models: dict):
    app = create_app()
    with app.app_context():
        det = _abs_weight(AiModel.query.filter_by(model_key="yolo26n", status="0").first())
        vr = _abs_weight(_pick_model(None, keys=["transreid-vehicle"]))
        plate_path = _abs_weight(_pick_model(None, keys=["yolo26s-plate-pose", "yolo26n-plate"]))
        ocr_fn = _build_ocr_fn(None, None)

    out = {}
    for cid, path, t, fps in ((71, P71, t71, 20.0), (81, P81, t81, 25.0)):
        frame = load_frame(path, t, fps)
        dets = _detect(det, frame, 0.28, VEHICLE_CLS)
        d = _pick_det(dets, class_pref)
        if d is None:
            out[cid] = None
            continue
        crop = _crop(frame, d["bbox"])
        emb, _ = extract_vehicle_embedding(vr, crop)
        plate, ps = None, 0.0
        if ocr_fn and plate_path:
            for pb, _src, _q, warp in _plate_candidates(d["bbox"], frame, plate_path, 0.15):
                ocr = _ocr_plate(ocr_fn, frame, pb, warped=warp)
                if ocr.get("text"):
                    plate, ps = ocr.get("text"), float(ocr.get("score") or 0)
                    break
        fuse = fuse_plate_visual(plate=plate, plate_score=ps, emb_a=emb, emb_b=emb)
        out[cid] = {
            "emb": emb, "bbox": d["bbox"], "conf": d["confidence"],
            "class": d.get("className"), "plate": plate, "fuse": fuse,
        }
    return out


def isolated_test(refs: dict) -> dict:
    r71, r81 = refs.get(71), refs.get(81)
    if not r71 or not r81:
        return {"ok": False, "reason": "missing ref detection"}
    cos = cosine(r71["emb"], r81["emb"])
    now = 1_700_000_000.0
    assoc = MtmcAssociator(appear_thresh=0.48, vehicle_appear_thresh=0.48, confirm_thresh=0.48, time_window_sec=120)
    g1 = assoc.associate(
        object_type="vehicle", camera_id=71, embedding=r71["emb"],
        identity_key=r71["fuse"].get("identityKey"), plate=r71["plate"],
        vehicle_class=r71.get("class"),
        local_track_id=1, exclude_gids=set(), now=now,
    )
    g2 = assoc.associate(
        object_type="vehicle", camera_id=81, embedding=r81["emb"],
        identity_key=r81["fuse"].get("identityKey"), plate=r81["plate"],
        vehicle_class=r81.get("class"),
        local_track_id=3, exclude_gids=set(), now=now + 1.0,
    )
    return {
        "ok": g1.global_id == g2.global_id,
        "visual_cosine": cos,
        "g71": g1.global_id,
        "g81": g2.global_id,
        "mode": assoc.last_mode.value,
    }


def flow_test(t71: float, t81: float, refs: dict, dur: float, t_start: float = 0.0) -> dict:
    r71, r81 = refs.get(71), refs.get(81)
    if not r71 or not r81:
        return {"ok": False, "reason": "missing ref detection"}

    models = load_models()
    session = build_session(models, SAMPLE_FPS)
    caps, meta = open_captures()
    det = models["det_person_path"]
    base_ts = 1.7e9
    trackers = {
        71: create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3),
        81: create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3),
    }
    fi = {71: 0, 81: 0}
    step = {71: max(1, int(round(meta[71]["fps"] / SAMPLE_FPS))), 81: max(1, int(round(meta[81]["fps"] / SAMPLE_FPS)))}
    mf = {71: int(dur * meta[71]["fps"]), 81: int(dur * meta[81]["fps"])}
    # 快进到 t_start（减少长视频前置处理耗时）
    for cid in (71, 81):
        cap = caps[cid]
        target_frame = int(t_start * meta[cid]["fps"])
        cur = 0
        while cur < target_frame:
            if not cap.grab():
                break
            cur += 1
        fi[cid] = cur

    total_steps = max(1, int((dur - t_start) * SAMPLE_FPS))
    snap_all: dict[int, list[tuple]] = {71: [], 81: []}

    for si in range(total_steps + 1):
        t = t_start + si / SAMPLE_FPS
        if t > dur:
            break
        for cid in (71, 81):
            cap = caps[cid]
            target = min(int(t * meta[cid]["fps"]), mf[cid])
            cur = fi[cid]
            while cur < target:
                if not cap.grab():
                    break
                cur += 1
            if cur > mf[cid]:
                fi[cid] = cur
                continue
            ok, frame = cap.read()
            cur += 1
            fi[cid] = cur
            if not ok or frame is None:
                continue
            now = base_ts + t
            small = resize_frame(frame)
            tracks = trackers[cid].update(_detect(det, small, 0.28, VEHICLE_CLS), frame=small)
            claimed: set[str] = set()
            tt = t71 if cid == 71 else t81
            ref_emb = r71["emb"] if cid == 71 else r81["emb"]
            for tr in _sort_vehicle_tracks_for_assoc(tracks, session.associator, cid, now):
                emb, fuse = _vehicle_fuse_from_track(tr, small, models)
                if emb is None:
                    continue
                g = session.associator.associate(
                    object_type="vehicle", camera_id=cid, embedding=emb,
                    identity_key=fuse.get("identityKey"), plate=fuse.get("plate"),
                    vehicle_class=getattr(tr, "class_name", None),
                    local_track_id=int(tr.track_id), exclude_gids=claimed, now=now,
                )
                claimed.add(g.global_id)
                if abs(t - tt) < 0.01:
                    cos_ref = cosine(emb, ref_emb)
                    snap_all[cid].append((int(tr.track_id), g.global_id, tr.conf, cos_ref))

    for cap in caps.values():
        cap.release()

    if not snap_all[71] or not snap_all[81]:
        return {"ok": False, "reason": "no track at target time", "snap": snap_all}

    # 判定：存在同一 Global 在两侧均有高 ref 相似度（目标车辆）
    ref_thresh = 0.85
    g71_set = {row[1] for row in snap_all[71]}
    g81_set = {row[1] for row in snap_all[81]}
    shared = g71_set & g81_set
    best_gid = None
    best_score = -1.0
    for gid in shared:
        c71 = max(c for _, g, _, c in snap_all[71] if g == gid)
        c81 = max(c for _, g, _, c in snap_all[81] if g == gid)
        if c71 >= ref_thresh and c81 >= ref_thresh:
            joint = min(c71, c81)
            if joint > best_score:
                best_score = joint
                best_gid = gid

    if best_gid:
        r71 = max((x for x in snap_all[71] if x[1] == best_gid), key=lambda x: x[3])
        r81 = max((x for x in snap_all[81] if x[1] == best_gid), key=lambda x: x[3])
        return {
            "ok": True,
            "globalId": best_gid,
            "cam71": f"L{r71[0]} {r71[1]} cos={r71[3]:.3f}",
            "cam81": f"L{r81[0]} {r81[1]} cos={r81[3]:.3f}",
            "g71": r71[1],
            "g81": r81[1],
        }

    # fallback：各自 ref 最佳 track（便于调试失败原因）
    r71 = max(snap_all[71], key=lambda x: x[3])
    r81 = max(snap_all[81], key=lambda x: x[3])
    return {
        "ok": False,
        "reason": "no shared global with ref cos>=0.85 on both sides",
        "cam71": f"L{r71[0]} {r71[1]} cos={r71[3]:.3f}",
        "cam81": f"L{r81[0]} {r81[1]} cos={r81[3]:.3f}",
        "g71": r71[1],
        "g81": r81[1],
        "sharedGlobals": list(shared),
    }


def main():
    models = load_models()
    print("=" * 60)
    print("跨镜车辆重识别 — 用户截图 4 组用例")
    print("=" * 60)
    results = []
    for name, t71, t81, pref in CASES:
        print(f"\n--- {name}  cam71={t71:.0f}s  cam81={t81:.0f}s ---")
        refs = ref_embedding(t71, t81, pref, models)
        for cid, tag in ((71, "cam71"), (81, "cam81")):
            r = refs.get(cid)
            if r:
                print(f"  {tag}: cls={r['class']} conf={r['conf']:.2f} plate={r['plate']!r}")
            else:
                print(f"  {tag}: NO DETECTION")
        if refs.get(71) and refs.get(81):
            print(f"  ref visual_cosine={cosine(refs[71]['emb'], refs[81]['emb']):.4f}")

        iso = isolated_test(refs)
        dur = max(t71, t81) + 5.0
        t_start = max(0.0, min(t71, t81) - 25.0)
        flow = flow_test(t71, t81, refs, dur, t_start=t_start)
        ok = iso.get("ok") and flow.get("ok")
        print(f"  isolated: {'PASS' if iso.get('ok') else 'FAIL'}  {iso}")
        print(f"  flow:     {'PASS' if flow.get('ok') else 'FAIL'}  {flow}")
        print(f"  >>> {'PASS' if ok else 'FAIL'}")
        results.append((name, ok, iso, flow))

    print("\n" + "=" * 60)
    print("汇总")
    passed = sum(1 for _, ok, _, _ in results if ok)
    for name, ok, _, _ in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"总计: {passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
