"""Compare existing Youtu/OpenCV, tuned Python ORT, and the C++ runtime.

Measures feature extraction only, including resize/normalization. Does not
measure detection, database matching, video decode, or end-to-end MTMC quality.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
import onnxruntime as ort
from person_reid_dnn import extract_feature, preprocess_crop, resolve_onnx
from services.reid_cpp import NativeReidSession


def measure(name, factory, crops, iterations, warmup, workers):
    started = time.perf_counter()
    extract, close, metadata = factory()
    load_ms = (time.perf_counter() - started) * 1000
    try:
        first_start = time.perf_counter()
        result = extract(crops)
        first_ms = (time.perf_counter() - first_start) * 1000
        for _ in range(warmup):
            extract(crops)
        def infer(_):
            start = time.perf_counter()
            extract(crops)
            return (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            latencies = list(pool.map(infer, range(iterations)))
        duration = time.perf_counter() - start
        return {
            "mode": name, "sessionCreateMs": load_ms, "firstBatchMs": first_ms,
            "p50BatchMs": float(np.percentile(latencies, 50)),
            "p95BatchMs": float(np.percentile(latencies, 95)),
            "cropsPerSecond": iterations * len(crops) / duration,
            **metadata,
        }, result
    finally:
        close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--images", nargs="*", help="Already cropped person images; default uses deterministic random crops")
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.iterations, args.batch_size, args.workers, args.threads) < 1 or args.warmup < 0:
        parser.error("counts must be positive (warmup may be zero)")
    model = resolve_onnx(args.model)
    crops = []
    for image in args.images or []:
        crop = cv2.imdecode(np.fromfile(image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if crop is None:
            parser.error(f"Cannot decode {image}")
        crops.append(crop)
    if not crops:
        crops = [np.random.default_rng(i).integers(0, 256, (283, 139, 3), dtype=np.uint8) for i in range(args.batch_size)]
    else:
        crops = [crops[i % len(crops)] for i in range(args.batch_size)]
    options = ort.SessionOptions()
    options.intra_op_num_threads = args.threads
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    def legacy_factory():
        # Existing loader is lazy: model loading appears in firstBatchMs.
        metadata = {"provider": "opencv-first/ort-fallback", "threads": "existing-default"}
        def extract(images):
            pairs = [extract_feature(model, image, runtime="python") for image in images]
            metadata["provider"] = pairs[-1][1].get("provider", "unknown")
            return np.stack([pair[0] for pair in pairs])
        return extract, lambda: None, metadata
    def python_ort_factory():
        session = ort.InferenceSession(model, sess_options=options, providers=["CPUExecutionProvider"])
        input_name, output_name = session.get_inputs()[0].name, session.get_outputs()[0].name
        dynamic_batch = not isinstance(session.get_inputs()[0].shape[0], int)
        def extract(images):
            if not dynamic_batch or len(images) == 1:
                return np.stack([session.run([output_name], {input_name: preprocess_crop(image)})[0].reshape(-1)
                                 for image in images])
            results = []
            for start in range(0, len(images), 64):
                batch = images[start:start + 64]
                blob = np.concatenate([preprocess_crop(image) for image in batch])
                results.append(session.run([output_name], {input_name: blob})[0].reshape(len(batch), -1))
            return np.concatenate(results)
        return extract, lambda: None, {"provider": "onnxruntime-python-cpu", "threads": args.threads,
                                       "dynamicBatch": dynamic_batch}
    def cpp_factory():
        session = NativeReidSession(model, threads=args.threads)
        return session.extract, session.close, {"provider": "onnxruntime-cpp-cpu", "threads": args.threads,
                                                "dynamicBatch": session.dynamic_batch}
    report = {
        "scope": "feature-extraction-only", "inputKind": "person-crops" if args.images else "synthetic-random-crops",
        "model": Path(model).name, "modelSha256": hashlib.sha256(Path(model).read_bytes()).hexdigest(),
        "platform": platform.platform(), "processor": platform.processor(), "cpuCount": os.cpu_count(),
        "python": sys.version, "opencv": cv2.__version__, "onnxruntime": ort.__version__,
        "iterations": args.iterations, "warmup": args.warmup, "batchSize": args.batch_size, "workers": args.workers,
        "results": [], "errors": {},
    }
    features = {}
    for name, factory in [("legacy", legacy_factory), ("python-ort-tuned", python_ort_factory), ("cpp", cpp_factory)]:
        try:
            stats, features[name] = measure(name, factory, crops, args.iterations, args.warmup, args.workers)
            report["results"].append(stats)
            print(json.dumps(stats, ensure_ascii=False), flush=True)
        except Exception as error:
            report["errors"][name] = str(error)
            print(f"{name}: {error}", flush=True)
    if "cpp" in features and "python-ort-tuned" in features:
        reference, actual = features["python-ort-tuned"], features["cpp"]
        reference_norm = reference / np.maximum(np.linalg.norm(reference, axis=1, keepdims=True), 1e-12)
        actual_norm = actual / np.maximum(np.linalg.norm(actual, axis=1, keepdims=True), 1e-12)
        report["parity"] = {"maxAbsError": float(np.max(np.abs(reference - actual))),
                            "minCosine": float(np.min(np.sum(reference_norm * actual_norm, axis=1))),
                            "allclose": bool(np.allclose(reference, actual, rtol=1e-4, atol=1e-5))}
        if "legacy" in features:
            old = features["legacy"]
            old_norm = old / np.maximum(np.linalg.norm(old, axis=1, keepdims=True), 1e-12)
            report["legacyParity"] = {"maxAbsError": float(np.max(np.abs(old - actual))),
                                      "minCosine": float(np.min(np.sum(old_norm * actual_norm, axis=1))),
                                      "allclose": bool(np.allclose(old, actual, rtol=1e-4, atol=1e-5))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {args.output}")
    if report["errors"] or not report.get("parity", {}).get("allclose"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
