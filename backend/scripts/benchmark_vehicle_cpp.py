"""Compare vehicle feature runtimes on the six labelled cross-camera pairs.

Offline feature/retrieval benchmark only; no detector, OCR, database or download.
Labels are used only for evaluation. Model output is not trained on these pairs.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import cv2
import numpy as np
import onnxruntime as ort
from benchmark_vehicle_reid import CASES, VEHICLE_PREFIX, crop, read_image, retrieval_metrics
from services import vehicle_reid_feat as features
from services.reid_cpp import NativeReidSession


def normalize(matrix):
    matrix = np.asarray(matrix, dtype=np.float32)
    return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)


def evaluate(factory, images, args):
    tick = time.perf_counter()
    extract, close, metadata = factory()
    create_ms = (time.perf_counter() - tick) * 1000
    try:
        batch = [images[i % len(images)] for i in range(args.batch_size)]
        tick = time.perf_counter()
        extract(batch)
        first_ms = (time.perf_counter() - tick) * 1000
        # One-at-a-time for quality: same shape/precision in every runtime.
        vectors = np.concatenate([extract([image]) for image in images])
        for _ in range(args.warmup): extract(batch)
        def run(_):
            started = time.perf_counter()
            extract(batch)
            return (time.perf_counter() - started) * 1000
        tick = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            latencies = list(executor.map(run, range(args.iterations)))
        duration = time.perf_counter() - tick
        return {**metadata, "sessionCreateMs": create_ms, "firstBatchMs": first_ms,
                "p50BatchMs": float(np.percentile(latencies, 50)),
                "p95BatchMs": float(np.percentile(latencies, 95)),
                "cropsPerSecond": len(batch) * args.iterations / duration,
                "retrieval": retrieval_metrics(vectors[:6], vectors[6:], args.threshold, args.margin)}, vectors
    finally:
        close()


def benchmark(model, images, args):
    def legacy():
        def extract(crops):
            pairs = [features.extract_vehicle_embedding(str(model), image, runtime="python") for image in crops]
            if any(meta["backend"] != "vehicle-onnx" for _, meta in pairs):
                raise RuntimeError("legacy vehicle model degraded to histogram")
            return np.stack([vector for vector, _ in pairs])
        return extract, lambda: None, {"provider": "CPUExecutionProvider", "threads": "existing-default"}
    def tuned():
        options = ort.SessionOptions()
        options.intra_op_num_threads = args.threads
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
        width, height = features._input_spatial(session)
        dynamic = not isinstance(session.get_inputs()[0].shape[0], int) and len(session.get_inputs()) == 1
        def extract(crops):
            blobs = [features._preprocess(image, width, height) for image in crops]
            if dynamic and len(crops) > 1:
                outputs = []
                for start in range(0, len(crops), 64):
                    blob = np.concatenate(blobs[start:start + 64])
                    outputs.append(session.run([session.get_outputs()[0].name], features._build_feed(session, blob))[0].reshape(len(blob), -1))
                return normalize(np.concatenate(outputs))
            return normalize(np.stack([session.run([session.get_outputs()[0].name], features._build_feed(session, blob))[0].reshape(-1)
                                       for blob in blobs]))
        return extract, lambda: None, {"provider": "onnxruntime-python-cpu", "threads": args.threads, "dynamicBatch": dynamic}
    def native():
        session = NativeReidSession(model, kind="vehicle", threads=args.threads)
        return lambda crops: normalize(session.extract(crops, batch_limit=min(args.batch_size, 64))), session.close, {
            "provider": "onnxruntime-cpp-cpu", "threads": args.threads, "dynamicBatch": session.dynamic_batch}
    report = {"model": str(model), "modelVersion": features.model_version(str(model)), "results": {}, "errors": {}}
    vectors = {}
    for name, factory in [("legacy", legacy), ("python-ort-tuned", tuned), ("cpp", native)]:
        try:
            report["results"][name], vectors[name] = evaluate(factory, images, args)
            print(json.dumps({"model": model.name, "mode": name,
                              **{k: v for k, v in report['results'][name].items() if k != 'retrieval'}}, ensure_ascii=False), flush=True)
        except Exception as error:
            report["errors"][name] = str(error)
            print(f"{model.name}/{name}: {error}", flush=True)
    if "cpp" in vectors:
        report["parity"] = {}
        for name in ("legacy", "python-ort-tuned"):
            if name in vectors:
                report["parity"][name] = {"maxAbsError": float(np.max(np.abs(vectors[name] - vectors['cpp']))),
                                          "minCosine": float(np.min(np.sum(vectors[name] * vectors['cpp'], axis=1))),
                                          "allclose": bool(np.allclose(vectors[name], vectors['cpp'], atol=1e-5, rtol=1e-4)),
                                          "sameRanking": bool(np.array_equal((vectors[name][:6] @ vectors[name][6:].T).argsort(axis=1),
                                                                                 (vectors['cpp'][:6] @ vectors['cpp'][6:].T).argsort(axis=1)))}
    # Do not keep all default-thread pools and large model arenas alive while
    # testing the next model, which would contaminate resource comparisons.
    with features._lock: features._sess_cache.clear()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=BACKEND.parent / "docs/test_data")
    parser.add_argument("--iterations", type=int, default=24)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--threshold", type=float, default=.48)
    parser.add_argument("--margin", type=float, default=.04)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.iterations, args.workers, args.threads, args.batch_size) < 1 or args.warmup < 0:
        parser.error("counts must be positive; warmup may be zero")
    images = [[], []]
    dataset = []
    for index, case in enumerate(CASES):
        path = args.data_root / "images" / f"{VEHICLE_PREFIX}{index + 1:02d}.png"
        image = read_image(path)
        dataset.append({"id": case['id'], "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "boxes": case['boxes']})
        for side in [0, 1]: images[side].append(crop(image, case['boxes'][side]))
    report = {"scope": "vehicle-feature-extraction-and-six-pair-retrieval-only", "date": "2026-10-14",
              "dataset": dataset, "platform": platform.platform(), "processor": platform.processor(), "cpuCount": os.cpu_count(),
              "python": sys.version, "opencv": cv2.__version__, "onnxruntime": ort.__version__,
              "config": {k: str(v) if isinstance(v, Path) else [str(p) for p in v] if k == "models" else v for k, v in vars(args).items()},
              "models": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for model in args.models:
        report["models"].append(benchmark(model, images[0] + images[1], args))
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if any(row['errors'] or not row.get('parity') or any(not p['allclose'] or not p['sameRanking'] for p in row['parity'].values()) for row in report['models']):
        raise SystemExit(1)


if __name__ == "__main__": main()
