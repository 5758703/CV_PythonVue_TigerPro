"""Reproducible, offline vehicle-only checks for the supplied two-camera clips.

Labels are evaluation inputs, never passed to the detector or association engine.
The six car/truck pairs are supplied by the user; boxes are manually annotated.
Other screenshots are detection smoke tests, with no person identity matching.
No Flask application, database, OCR, external service, or download is needed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

import cv2
import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

VEHICLE_PREFIX = "跨镜车辆重识别-两个镜头同一辆车画面"
# Coordinates in the original screenshots, before removing VLC chrome.
CASES = [
    {"id": "car01", "times": [28, 29], "split": 958,
     "boxes": [[350, 525, 632, 696], [1480, 596, 1755, 768]]},
    {"id": "car02", "times": [37, 37], "split": 960,
     "boxes": [[670, 520, 918, 698], [1106, 545, 1308, 721]]},
    {"id": "car03", "times": [65, 65], "split": 950,
     "boxes": [[693, 520, 918, 678], [1076, 540, 1244, 679]]},
    {"id": "car04", "times": [88, 89], "split": 960,
     "boxes": [[319, 539, 629, 719], [1481, 607, 1767, 786]]},
    {"id": "truck05", "times": [126, 127], "split": 960,
     "boxes": [[308, 465, 684, 713], [1338, 490, 1614, 694]]},
    {"id": "truck06", "times": [145, 146], "split": 960,
     "boxes": [[297, 438, 620, 727], [1394, 478, 1645, 717]]},
]
VIDEO_NAMES = {
    71: "camera_192_168_8_71_20260820_094046.mp4",
    81: "camera_192_168_8_81_20260820_094044.mp4",
}


def read_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot decode {path}")
    return image


def content_rect(image: np.ndarray, x1: int, x2: int) -> list[int]:
    """Find the central non-black run, excluding title bars and playback UI."""
    rows = (image[:, x1 + 5:x2 - 5].max(axis=2) > 20).mean(axis=1) > 0.35
    middle = image.shape[0] // 2
    if not rows[middle]:
        raise ValueError("Expected video content in screenshot centre")
    top, bottom = middle, middle
    while top > 0 and rows[top - 1]:
        top -= 1
    while bottom + 1 < len(rows) and rows[bottom + 1]:
        bottom += 1
    return [x1, top, x2, bottom + 1]


def relative_box(box, rect, width=None):
    x, y, right, bottom = rect
    factor = float(width) / (right - x) if width else 1.0
    return [(box[0] - x) * factor, (box[1] - y) * factor,
            (box[2] - x) * factor, (box[3] - y) * factor]


def crop(image, box):
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    return image[max(0, y1):min(image.shape[0], y2), max(0, x1):min(image.shape[1], x2)]


def iou(a, b):
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    areas = [(r[2] - r[0]) * (r[3] - r[1]) for r in (a, b)]
    return overlap / max(1e-12, sum(areas) - overlap)


def retrieval_metrics(left, right, threshold, margin):
    """Keep all labels in the denominator, including missed detections."""
    n = len(left)
    scores = np.full((n, n), -1.0, dtype=np.float32)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            if a is not None and b is not None:
                scores[i, j] = float(np.dot(a, b))
    complete = np.array([a is not None and b is not None for a, b in zip(left, right)])
    rows, cols = scores.argmax(axis=1), scores.argmax(axis=0)
    top1 = complete & (rows == np.arange(n))
    reverse = complete & (cols == np.arange(n))
    accepted = []
    for i in range(n):
        j = int(rows[i])
        runner_up = np.sort(scores[i])[-2] if n > 1 else -1
        if (scores[i, j] >= threshold and scores[i, j] - runner_up >= margin
                and cols[j] == i):
            accepted.append([i, j])
    negatives = scores[~np.eye(n, dtype=bool)]
    return {
        "pairs": n, "complete_detections": int(complete.sum()),
        "rank1_left_to_right": int(top1.sum()), "rank1_right_to_left": int(reverse.sum()),
        "accepted_correct": sum(i == j for i, j in accepted),
        "accepted_wrong": sum(i != j for i, j in accepted), "accepted_pairs": accepted,
        "negative_pairs": int(negatives.size),
        "negative_pairs_above_threshold": int((negatives >= threshold).sum()),
        "positive_scores": np.diag(scores).tolist(), "similarity_matrix": scores.tolist(),
    }


def latency_summary(values):
    return {"count": len(values), "mean_ms": float(np.mean(values) * 1000),
            "p50_ms": float(np.median(values) * 1000),
            "p95_ms": float(np.percentile(values, 95) * 1000)} if values else {}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_screenshots(args):
    from services.mtmc_engine import _detect, _crop
    from services.vehicle_reid_feat import extract_vehicle_embedding
    reference = [[], []]
    detected = [[], []]
    rows, timings = [], []
    paths = sorted((args.data_root / "images").glob("跨镜*.png"))
    for path in paths:
        image = read_image(path)
        case_index = next((i for i in range(6) if path.name == f"{VEHICLE_PREFIX}{i + 1:02d}.png"), None)
        case = CASES[case_index] if case_index is not None else None
        split = case["split"] if case else image.shape[1] // 2
        annotated = image.copy()
        for side, (x1, x2) in enumerate(((0, split), (split, image.shape[1]))):
            rect = content_rect(image, x1, x2)
            view = crop(image, rect)
            start = time.perf_counter()
            detections = _detect(str(args.detector), view, args.conf, [2, 5, 7])
            elapsed = time.perf_counter() - start
            row = {"file": path.name, "camera": (71, 81)[side], "content_rect": rect,
                   "detection_ms": elapsed * 1000, "detections": detections}
            for det in detections:
                b = det["bbox"]
                pt1 = (int(b[0] + rect[0]), int(b[1] + rect[1]))
                pt2 = (int(b[2] + rect[0]), int(b[3] + rect[1]))
                cv2.rectangle(annotated, pt1, pt2, (70, 180, 255), 2)
            if case:
                label_box = relative_box(case["boxes"][side], rect)
                target = max(detections, key=lambda d: iou(d["bbox"], label_box), default=None)
                overlap = iou(target["bbox"], label_box) if target else 0
                reference_emb, meta = extract_vehicle_embedding(str(args.reid), crop(view, label_box))
                if meta.get("backend") != "vehicle-onnx":
                    raise RuntimeError(f"ReID unavailable: {meta}")
                reference[side].append(reference_emb)
                det_emb = None
                if overlap >= args.iou:
                    start = time.perf_counter()
                    det_emb, meta = extract_vehicle_embedding(str(args.reid), _crop(view, target["bbox"]))
                    timings.append(time.perf_counter() - start)
                    if meta.get("backend") != "vehicle-onnx":
                        raise RuntimeError(f"ReID unavailable: {meta}")
                detected[side].append(det_emb)
                row.update(case_id=case["id"], label_box=label_box, detection_iou=overlap,
                           detection_hit=overlap >= args.iou, reid_meta=meta)
                b = case["boxes"][side]
                cv2.rectangle(annotated, tuple(b[:2]), tuple(b[2:]), (80, 240, 50), 2)
            rows.append(row)
        cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tofile(str(args.output / (path.stem + ".jpg")))
        print(f"screenshot {path.name}", flush=True)
    if len(reference[0]) != 6 or len(reference[1]) != 6:
        raise ValueError("All six labelled vehicle screenshots are required")
    return {"files": len(paths), "views": len(rows), "rows": rows,
            "reference_crop_retrieval": retrieval_metrics(*reference, args.threshold, args.margin),
            "detected_crop_retrieval": retrieval_metrics(*detected, args.threshold, args.margin),
            "warm_embedding_latency": latency_summary(timings),
            "scope": "Car/truck detection on every screenshot; six labelled car/truck pairs. No person/rider identity evaluation."}


def video_labels(args, camera_id, cap):
    """Locate each screenshot in its OWN video by pixel error, not ReID scores.

    VLC's whole-second time is approximate. Search +/-2 seconds at source FPS
    and retain the frame with the lowest pixel error inside the labelled box.
    This frame then enters the same continuous engine stream as every other frame.
    """
    fps = cap.get(cv2.CAP_PROP_FPS)
    side = 0 if camera_id == 71 else 1
    labels = {}
    for index, case in enumerate(CASES):
        screenshot = read_image(args.data_root / "images" / f"{VEHICLE_PREFIX}{index + 1:02d}.png")
        rect = content_rect(screenshot, 0 if side == 0 else case["split"],
                            case["split"] if side == 0 else screenshot.shape[1])
        reference = crop(screenshot, rect)
        box = relative_box(case["boxes"][side], rect)
        reference_patch = cv2.resize(crop(reference, box), (64, 64)).astype(np.float32)
        start = max(0, int((case["times"][side] - 2) * fps))
        stop = int((case["times"][side] + 2) * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        best = None
        for fidx in range(start, stop + 1):
            ok, frame = cap.read()
            if not ok:
                break
            small = cv2.resize(frame, (reference.shape[1], reference.shape[0]))
            patch_image = cv2.resize(crop(small, box), (64, 64)).astype(np.float32)
            error = float(np.mean(np.abs(patch_image - reference_patch)))
            if best is None or error < best[0]:
                best = (error, fidx)
        if best is None:
            raise ValueError(f"No frame for {camera_id}/{case['id']}")
        labels[best[1]] = {"case_id": case["id"], "frame_index": best[1], "time_sec": best[1] / fps,
                           "pixel_mae": best[0], "bbox": relative_box(case["boxes"][side], rect, args.width)}
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return labels


def run_videos(args):
    from services import mtmc_engine as engine
    from services.mtmc_associator import MtmcAssociator
    # Car/truck-only detector adapter. Everything after detection is production code.
    original_detect = engine._detect

    def detect_cars(path, frame, conf, classes):
        return original_detect(path, frame, conf, [2, 5, 7])

    cfg = engine.MtmcConfig(
        camera_ids=[71, 81], enable_person=False, enable_vehicle=True,
        det_vehicle_path=str(args.detector), vehicle_reid_root=str(args.reid),
        conf=args.conf, sample_fps=args.sample_fps, width=args.width, plate_budget=0,
        appear_thresh=args.threshold, vehicle_appear_thresh=args.threshold,
        confirm_thresh=args.threshold, candidate_thresh=max(0.2, args.threshold - 0.1),
        min_match_margin=args.margin, use_faiss_gallery=False, persist_events=False,
    )
    assoc = MtmcAssociator(
        appear_thresh=args.threshold, vehicle_appear_thresh=args.threshold,
        confirm_thresh=args.threshold, candidate_thresh=cfg.candidate_thresh,
        min_match_margin=args.margin, use_faiss_gallery=False, time_window_sec=30,
        topology={(71, 81): {"minTransitSec": 0, "maxTransitSec": 30, "edgeType": "overlap"},
                  (81, 71): {"minTransitSec": 0, "maxTransitSec": 30, "edgeType": "overlap"}},
    )
    session = engine.MtmcSession("offline-vehicle-benchmark", cfg, assoc)
    session.cams = {cid: engine.CamState(camera_id=cid) for cid in (71, 81)}
    meta, labels, cameras, schedule = {}, {}, {}, []
    latencies, hits, counts = [], [], Counter()
    with ExitStack() as stack:
        stack.enter_context(patch.object(engine, "_detect", detect_cars))
        for cid, filename in VIDEO_NAMES.items():
            path = args.data_root / "video/camera_recordings" / filename
            cap = cv2.VideoCapture(str(path))
            stack.callback(cap.release)
            if not cap.isOpened():
                raise ValueError(f"Cannot open {path}")
            fps, total = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            meta[cid] = {"fps": fps, "frames": total, "duration_sec": total / fps,
                         "width": cap.get(cv2.CAP_PROP_FRAME_WIDTH), "height": cap.get(cv2.CAP_PROP_FRAME_HEIGHT)}
            labels[cid] = video_labels(args, cid, cap)
            cameras[cid] = [cap, 0]
            limit = min(total, int(args.duration * fps)) if args.duration else total
            selected = {int(round(t * fps / args.sample_fps)) for t in range(int(limit / fps * args.sample_fps))}
            selected.update(k for k in labels[cid] if k < limit)
            offset = args.camera71_offset if cid == 71 else 0
            schedule.extend((idx / fps + offset, cid, idx) for idx in sorted(selected) if idx < limit)
        print("video labels located", json.dumps(labels, ensure_ascii=False), flush=True)
        start = time.perf_counter()
        with (args.output / "video_frames.jsonl").open("w", encoding="utf-8") as log:
            for number, (timestamp, cid, target_index) in enumerate(sorted(schedule)):
                cap, next_index = cameras[cid]
                while next_index < target_index:
                    if not cap.grab():
                        raise RuntimeError(f"Early EOF {cid}/{next_index}")
                    next_index += 1
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError(f"Decode failed {cid}/{target_index}")
                cameras[cid][1] = target_index + 1
                view = cv2.resize(frame, (args.width, round(frame.shape[0] * args.width / frame.shape[1])))
                state = session.cams[cid]
                # Sampling already happened above; a labelled extra frame must
                # not silently return the previous frame's overlay via FPS gate.
                state.last_process_at = 0
                tick = time.perf_counter()
                engine._process_frame(session, state, view, {}, now=1000 + timestamp)
                latencies.append(time.perf_counter() - tick)
                counts[cid] += 1
                current = [{k: d.get(k) for k in ("bbox", "globalId", "localTrackId", "score", "attrs")}
                           for d in state.last_dets if d.get("objectType") == "vehicle"]
                log.write(json.dumps({"camera": cid, "frame": target_index, "time": timestamp, "detections": current}) + "\n")
                label = labels[cid].get(target_index)
                if label:
                    target = max(current, key=lambda d: iou(d["bbox"], label["bbox"]), default=None)
                    overlap = iou(target["bbox"], label["bbox"]) if target else 0
                    hits.append({**label, "camera": cid, "iou": overlap, "hit": overlap >= args.iou,
                                 "global_id": target["globalId"] if target and overlap >= args.iou else None,
                                 "local_id": target["localTrackId"] if target and overlap >= args.iou else None})
                    cv2.rectangle(view, tuple(int(x) for x in label["bbox"][:2]), tuple(int(x) for x in label["bbox"][2:]), (0, 240, 0), 2)
                    cv2.imencode(".jpg", view)[1].tofile(str(args.output / f"video_{cid}_{label['case_id']}.jpg"))
                if number % 40 == 0:
                    print(f"video {number + 1}/{len(schedule)} time={timestamp:.1f}s elapsed={time.perf_counter()-start:.1f}s", flush=True)
        elapsed = time.perf_counter() - start
        pairs = []
        for case in CASES:
            row = [next((h for h in hits if h["case_id"] == case["id"] and h["camera"] == cid), None) for cid in (71, 81)]
            same = bool(all(h and h["global_id"] for h in row) and row[0]["global_id"] == row[1]["global_id"])
            pairs.append({"case_id": case["id"], "same_global_id": same, "observations": row})
        owners = {}
        for hit in hits:
            if hit["global_id"]:
                owners.setdefault(hit["global_id"], set()).add(hit["case_id"])
        collisions = {gid: sorted(ids) for gid, ids in owners.items() if len(ids) > 1}
        for pair in pairs:
            pair["correct_and_unique"] = bool(pair["same_global_id"] and pair["observations"][0]["global_id"] not in collisions)
        return {"metadata": meta, "sampling_fps_per_camera": args.sample_fps,
                "camera71_offset_sec": args.camera71_offset, "processed_frames": dict(counts),
                "elapsed_sec": elapsed, "frame_latency": latency_summary(latencies),
                "pairs": pairs, "correct_unique_pairs": sum(p["correct_and_unique"] for p in pairs),
                "labelled_identity_collisions": collisions, "stats": session.stats,
                "runtime": session.runtime_status,
                "scope": "Continuous sampled car/truck production engine; 6 labelled pairs only. Remaining objects are not identity-labelled."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT / "docs/test_data")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--detector", type=Path, default=BACKEND / "uploads/models/yolo26n/yolo26n.pt")
    parser.add_argument("--reid", type=Path, required=True)
    parser.add_argument("--stage", choices=["screenshots", "videos", "all"], default="all")
    parser.add_argument("--threshold", type=float, default=0.48)
    parser.add_argument("--margin", type=float, default=0.04)
    parser.add_argument("--conf", type=float, default=0.28)
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument("--sample-fps", type=float, default=2)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--duration", type=float, default=0, help="0 processes both complete videos")
    parser.add_argument("--camera71-offset", type=float, default=2.0, help="Seconds after camera81 recording start; derived from filenames, not verified clock sync")
    args = parser.parse_args()
    if args.sample_fps <= 0 or args.width <= 0:
        parser.error("sample-fps and width must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(args.output.resolve()))
    os.environ.setdefault("YOLO_INFER_BACKEND", "pytorch")
    os.environ.setdefault("YOLO_PREFER_ONNX", "0")
    import torch
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    with args.reid.open("rb") as stream:
        model_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {"config": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
              "model_sha256": model_sha, "environment": {"python": sys.version, "opencv": cv2.__version__, "torch": torch.__version__}}
    for stage, fn in (("screenshots", run_screenshots), ("videos", run_videos)):
        if args.stage in (stage, "all"):
            report[stage] = fn(args)
            write_json(args.output / "report.json", report)
            print(f"{stage} report saved to {args.output / 'report.json'}", flush=True)


if __name__ == "__main__":
    main()
