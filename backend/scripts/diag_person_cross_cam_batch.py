"""批量诊断用户截图 9 组行人/骑行人跨镜重识别（交错 flow + 孤立关联）。"""
from __future__ import annotations

import argparse
import glob
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

import cv2
import numpy as np

from scripts.diag_vehicle_cross_cam_batch import P71, P81, SAMPLE_FPS, load_models
from scripts.eval_mtmc_cross_cam import build_session, open_captures, resize_frame
from services.mtmc_associator import MtmcAssociator
from services.mtmc_engine import _crop, _detect, supplement_rider_person_dets
from services.mtmc_local_track import create_local_tracker
from services.reid_gallery import l2_normalize
from services.strong_reid import extract_person_embedding, color_signature
from services.vehicle_reid_feat import cosine

IMG_DIR = os.path.join(ROOT, "..", "docs", "test_data", "images")


def _person_screenshot_paths() -> list[str]:
    files: list[str] = []
    for i in range(1, 10):
        for pat in (
            os.path.join(IMG_DIR, f"*骑*{i:02d}.png"),
            os.path.join(IMG_DIR, f"*骑*画面{i:02d}.png"),
        ):
            files.extend(sorted(glob.glob(pat)))
    if not files:
        files = sorted(glob.glob(os.path.join(IMG_DIR, "*.png")))
        files = [f for f in files if "\u9a91" in f or "01.png" in f][-9:]
    seen: set[str] = set()
    out: list[str] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out[:9]


PERSON_SCREENSHOTS = _person_screenshot_paths()
# 截图 VLC 时间戳（秒）：cam71 / cam81
PERSON_CASES = [
    ("01-双骑行人", 1.0, 1.0),
    ("02-黑衫骑行人", 3.0, 4.0),
    ("03-灰车带孩", 69.0, 70.0),
    ("04-白衫行人", 75.0, 75.0),
    ("05-米色骑行人", 90.0, 91.0),
    ("06-红帽骑手", 122.0, 124.0),
    ("07-灰衫骑手", 139.0, 141.0),
    ("08-白头盔骑手", 155.0, 156.0),
    ("09-白头盔骑手2", 168.0, 167.0),
]


def _imread(path: str):
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def load_frame(path: str, t: float, fps: float):
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
    ok, f = cap.read()
    cap.release()
    if not ok:
        return None
    h, w = f.shape[:2]
    return cv2.resize(f, (640, max(1, int(h * 640 / w))))


def _pick_person(dets):
    persons = [d for d in dets if str(d.get("className", "")).lower() == "person"]
    pool = persons or list(dets or [])
    if not pool:
        return None
    return max(pool, key=lambda x: (x["bbox"][2] - x["bbox"][0]) * (x["bbox"][3] - x["bbox"][1]))


def _person_embeddings_from_half(half, models: dict, conf: float = 0.15) -> list[dict]:
    hh, hw = half.shape[:2]
    small = cv2.resize(half, (640, max(1, int(hh * 640 / hw))))
    dets = _detect(models["det_person_path"], small, conf, [0])
    persons = [d for d in dets if str(d.get("className", "")).lower() == "person"] or list(dets or [])
    out = []
    for d in persons:
        crop = _crop(small, d["bbox"])
        if crop is None:
            continue
        try:
            emb, _ = extract_person_embedding(
                crop, youtu_root=models["youtu_root"], strong_root=models["strong_reid_root"],
            )
        except Exception:
            continue
        out.append({
            "emb": l2_normalize(emb),
            "bbox": d["bbox"],
            "conf": d["confidence"],
            "color": color_signature(crop),
        })
    return out


def ref_from_screenshot(case_idx: int, models: dict) -> dict:
    """从用户截图左/右半幅取目标行人 ref：外观+颜色综合配对。"""
    if case_idx >= len(PERSON_SCREENSHOTS):
        return {}
    path = PERSON_SCREENSHOTS[case_idx]
    img = _imread(path)
    if img is None:
        return {}
    h, w = img.shape[:2]
    pool = {
        71: _person_embeddings_from_half(img[:, : w // 2], models, conf=0.12),
        81: _person_embeddings_from_half(img[:, w // 2 :], models, conf=0.12),
    }
    if not pool[71] or not pool[81]:
        return {}
    from services.strong_reid import color_sig_cosine
    best = (-1.0, None, None)
    for a in pool[71]:
        for b in pool[81]:
            c = cosine(a["emb"], b["emb"])
            cs = color_sig_cosine(a.get("color"), b.get("color"))
            joint = c if cs < 0 else (0.65 * c + 0.35 * max(c, cs))
            if joint > best[0]:
                best = (joint, a, b)
    if best[1] is None:
        return {}
    return {71: best[1], 81: best[2]}


def ref_from_video(t71: float, t81: float, models: dict, conf: float = 0.15) -> dict:
    """视频帧最佳配对（含颜色），用于截图漏检时回退。"""
    from services.strong_reid import color_sig_cosine
    pools = {}
    for cid, path, t, fps in ((71, P71, t71, 20.0), (81, P81, t81, 25.0)):
        frame = load_frame(path, t, fps)
        if frame is None:
            pools[cid] = []
            continue
        dets = _detect(models["det_person_path"], frame, conf, [0])
        out = []
        for d in dets:
            crop = _crop(frame, d["bbox"])
            if crop is None:
                continue
            try:
                emb, _ = extract_person_embedding(
                    crop, youtu_root=models["youtu_root"], strong_root=models["strong_reid_root"],
                )
            except Exception:
                continue
            out.append({
                "emb": l2_normalize(emb),
                "bbox": d["bbox"],
                "conf": d["confidence"],
                "color": color_signature(crop),
            })
        pools[cid] = out
    if not pools.get(71) or not pools.get(81):
        return {}
    best = (-1.0, None, None)
    for a in pools[71]:
        for b in pools[81]:
            c = cosine(a["emb"], b["emb"])
            cs = color_sig_cosine(a.get("color"), b.get("color"))
            joint = c if cs < 0 else (0.65 * c + 0.35 * max(c, cs))
            if joint > best[0]:
                best = (joint, a, b)
    if best[1] is None:
        return {}
    return {71: best[1], 81: best[2]}


def isolated_test(refs: dict) -> dict:
    r71, r81 = refs.get(71), refs.get(81)
    if not r71 or not r81:
        return {"ok": False, "reason": "missing ref detection"}
    cos = cosine(r71["emb"], r81["emb"])
    now = 1_700_000_000.0
    assoc = MtmcAssociator(
        appear_thresh=0.48, confirm_thresh=0.48, time_window_sec=120,
        topology={(71, 81): (0.0, 30.0), (81, 71): (0.0, 30.0)},
    )
    g1 = assoc.associate(
        object_type="person", camera_id=71, embedding=r71["emb"],
        color_sig=r71.get("color"),
        local_track_id=1, exclude_gids=set(), now=now,
    )
    g2 = assoc.associate(
        object_type="person", camera_id=81, embedding=r81["emb"],
        color_sig=r81.get("color"),
        local_track_id=3, exclude_gids=set(), now=now + 0.5,
    )
    return {"ok": g1.global_id == g2.global_id, "visual_cosine": cos, "g71": g1.global_id, "g81": g2.global_id}


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
    mf = {71: int(dur * meta[71]["fps"]), 81: int(dur * meta[81]["fps"])}
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
            raw_all = _detect(det, small, 0.10, [0, 1, 3])
            raw_p = supplement_rider_person_dets(
                [d for d in raw_all if int(d.get("classId", -1)) == 0],
                [d for d in raw_all if int(d.get("classId", -1)) in (1, 3)],
                frame_w=small.shape[1], frame_h=small.shape[0],
            )
            tracks = trackers[cid].update(raw_p, frame=small)
            claimed: set[str] = set()
            tt = t71 if cid == 71 else t81
            ref_emb = r71["emb"] if cid == 71 else r81["emb"]
            for tr in sorted(
                tracks,
                key=lambda x: -((x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1])),
            ):
                crop = _crop(small, tr.bbox)
                if crop is None:
                    continue
                try:
                    emb, _ = extract_person_embedding(
                        crop,
                        youtu_root=models["youtu_root"],
                        strong_root=models["strong_reid_root"],
                    )
                    emb = l2_normalize(emb)
                    c_sig = color_signature(crop)
                except Exception:
                    continue
                g = session.associator.associate(
                    object_type="person", camera_id=cid, embedding=emb,
                    color_sig=c_sig,
                    visual_key="rider" if str(getattr(tr, "class_name", "")).lower() == "rider" else None,
                    local_track_id=int(tr.track_id), exclude_gids=claimed, now=now,
                )
                claimed.add(g.global_id)
                if abs(t - tt) < 0.51:
                    cos_ref = cosine(emb, ref_emb)
                    snap_all[cid].append((int(tr.track_id), g.global_id, tr.conf, cos_ref))

    for cap in caps.values():
        cap.release()

    if not snap_all[71] or not snap_all[81]:
        return {"ok": False, "reason": "no track at target time", "snap": snap_all}

    ref_thresh = 0.55
    shared = set(r[1] for r in snap_all[71]) & set(r[1] for r in snap_all[81])
    best_gid = None
    best_score = -1.0
    for gid in shared:
        c71 = max(c for _, g, _, c in snap_all[71] if g == gid)
        c81 = max(c for _, g, _, c in snap_all[81] if g == gid)
        if c71 >= ref_thresh and c81 >= ref_thresh:
            joint = min(c71, c81)
            if joint > best_score:
                best_score, best_gid = joint, gid

    if best_gid:
        r71 = max((x for x in snap_all[71] if x[1] == best_gid), key=lambda x: x[3])
        r81 = max((x for x in snap_all[81] if x[1] == best_gid), key=lambda x: x[3])
        return {
            "ok": True, "globalId": best_gid,
            "cam71": f"L{r71[0]} {r71[1]} cos={r71[3]:.3f}",
            "cam81": f"L{r81[0]} {r81[1]} cos={r81[3]:.3f}",
        }

    r71 = max(snap_all[71], key=lambda x: x[3])
    r81 = max(snap_all[81], key=lambda x: x[3])
    return {
        "ok": False,
        "reason": "no shared global with ref cos>=0.55 on both sides",
        "cam71": f"L{r71[0]} {r71[1]} cos={r71[3]:.3f}",
        "cam81": f"L{r81[0]} {r81[1]} cos={r81[3]:.3f}",
        "sharedGlobals": list(shared),
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate labeled cross-camera person/rider cases")
    parser.add_argument("--cases", default="", help="1-based comma-separated case numbers")
    args = parser.parse_args()
    selected = (
        {int(x.strip()) - 1 for x in args.cases.split(",") if x.strip()}
        if args.cases else set()
    )
    models = load_models()
    print("=" * 60)
    print("跨镜行人/骑行人 ReID — 用户截图 9 组")
    print("=" * 60)
    passed = 0
    evaluated = 0
    for idx, (name, t71, t81) in enumerate(PERSON_CASES):
        if selected and idx not in selected:
            continue
        evaluated += 1
        print(f"\n--- {name}  cam71={t71:.0f}s  cam81={t81:.0f}s ---")
        refs = ref_from_screenshot(idx, models)
        if not refs.get(71) or not refs.get(81):
            refs = ref_from_video(t71, t81, models, conf=0.12)
        if refs.get(71) and refs.get(81):
            print(f"  ref visual_cosine={cosine(refs[71]['emb'], refs[81]['emb']):.4f}")
        iso = isolated_test(refs)
        t_start = max(0.0, min(t71, t81) - 25.0)
        flow = flow_test(t71, t81, refs, max(t71, t81) + 5.0, t_start=t_start)
        ok = iso.get("ok") and flow.get("ok")
        print(f"  isolated: {'PASS' if iso.get('ok') else 'FAIL'}  {iso}")
        print(f"  flow:     {'PASS' if flow.get('ok') else 'FAIL'}  {flow}")
        print(f"  >>> {'PASS' if ok else 'FAIL'}")
        passed += int(ok)
    print(f"\n总计: {passed}/{evaluated} 通过")
    return 0 if passed == evaluated else 1


if __name__ == "__main__":
    raise SystemExit(main())
