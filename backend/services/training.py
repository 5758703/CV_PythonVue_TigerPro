"""YOLOv8 模型训练服务（参照 train_water_gauge.py）。"""
import csv
import json
import os
import random
import shutil
import threading
from datetime import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

_cancel_flags = {}
_cancel_lock = threading.Lock()


def request_cancel(job_id):
    with _cancel_lock:
        _cancel_flags[job_id] = True


def is_cancelled(job_id):
    with _cancel_lock:
        return _cancel_flags.get(job_id, False)


def clear_cancel(job_id):
    with _cancel_lock:
        _cancel_flags.pop(job_id, None)


# ── VOC → YOLO ────────────────────────────────────────

def parse_voc(xml_path: Path, class_names):
    """解析 VOC XML。

    Returns:
        (img_w, img_h, boxes, found_classes)
        - boxes: 只包含 class_names 内的目标
        - found_classes: xml 中出现过的所有类别名（用于诊断）
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    size = root.find("size")
    if size is None:
        raise ValueError("VOC XML 缺少 <size> 节点")
    w_node = size.find("width")
    h_node = size.find("height")
    if w_node is None or h_node is None:
        raise ValueError("VOC XML <size> 缺少 width/height")
    img_w = int(float(w_node.text))
    img_h = int(float(h_node.text))

    boxes = []
    found = set()
    for obj in root.iter("object"):
        name_node = obj.find("name")
        if name_node is None or not (name_node.text or "").strip():
            continue
        cls_name = name_node.text.strip()
        found.add(cls_name)
        cls_id = class_names.index(cls_name) if cls_name in class_names else -1
        if cls_id < 0:
            continue
        bb = obj.find("bndbox")
        if bb is None:
            continue
        xmin_n, ymin_n = bb.find("xmin"), bb.find("ymin")
        xmax_n, ymax_n = bb.find("xmax"), bb.find("ymax")
        if None in (xmin_n, ymin_n, xmax_n, ymax_n):
            continue
        xmin = float(xmin_n.text)
        ymin = float(ymin_n.text)
        xmax = float(xmax_n.text)
        ymax = float(ymax_n.text)
        boxes.append((cls_id, xmin, ymin, xmax, ymax))
    return img_w, img_h, boxes, sorted(found)


def voc_to_yolo(cls_id, xmin, ymin, xmax, ymax, img_w, img_h):
    cx = ((xmin + xmax) / 2) / img_w
    cy = ((ymin + ymax) / 2) / img_h
    bw = (xmax - xmin) / img_w
    bh = (ymax - ymin) / img_h
    return cx, cy, bw, bh


def build_yolo_dataset(raw_dir: Path, yolo_dir: Path, class_names, split_ratio=0.8, seed=42):
    """将 raw_dir 中的 VOC(jpg+xml) 转为 YOLO 目录结构。"""
    for split in ("train", "val"):
        (yolo_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (yolo_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    xml_files = sorted(raw_dir.glob("*.xml"))
    random.seed(seed)
    random.shuffle(xml_files)
    n_train = int(len(xml_files) * split_ratio)
    splits = {"train": xml_files[:n_train], "val": xml_files[n_train:]}

    ok, skip = 0, 0
    skip_no_image = 0
    skip_no_boxes = 0
    skip_parse_error = 0
    found_classes = set()
    train_n, val_n = 0, 0
    for split, files in splits.items():
        for xml_path in files:
            stem = xml_path.stem
            img_src = None
            for ext in (".jpg", ".jpeg", ".png", ".bmp"):
                p = raw_dir / f"{stem}{ext}"
                if p.exists():
                    img_src = p
                    break
            if img_src is None:
                skip += 1
                skip_no_image += 1
                continue
            try:
                img_w, img_h, boxes, found = parse_voc(xml_path, class_names)
                found_classes.update(found)
            except Exception:  # noqa: BLE001
                skip += 1
                skip_parse_error += 1
                continue
            if not boxes:
                skip += 1
                skip_no_boxes += 1
                continue
            img_dst = yolo_dir / "images" / split / img_src.name
            shutil.copy2(img_src, img_dst)
            lbl_dst = yolo_dir / "labels" / split / f"{stem}.txt"
            with open(lbl_dst, "w", encoding="utf-8") as f:
                for cls_id, xmin, ymin, xmax, ymax in boxes:
                    cx, cy, bw, bh = voc_to_yolo(cls_id, xmin, ymin, xmax, ymax, img_w, img_h)
                    f.write(f"{cls_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
            ok += 1
            if split == "train":
                train_n += 1
            else:
                val_n += 1
    diag = {
        "xmlTotal": len(xml_files),
        "ok": ok,
        "skip": skip,
        "skipNoImage": skip_no_image,
        "skipNoBoxes": skip_no_boxes,
        "skipParseError": skip_parse_error,
        "foundClasses": sorted(found_classes),
    }
    return ok, skip, train_n, val_n, diag


def write_data_yaml(yolo_dir: Path, class_names):
    yaml_path = yolo_dir / "data.yaml"
    content = (
        f"path: {yolo_dir.as_posix()}\n"
        f"train: images/train\n"
        f"val: images/val\n\n"
        f"nc: {len(class_names)}\n"
        f"names: {class_names}\n"
    )
    yaml_path.write_text(content, encoding="utf-8")
    return yaml_path


def parse_results_csv(results_csv: Path):
    """解析 Ultralytics results.csv 最后一行指标。"""
    if not results_csv.exists():
        return {}
    try:
        with open(results_csv, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return {}
        last = rows[-1]
        out = {}
        for k, v in last.items():
            key = k.strip()
            try:
                out[key] = round(float(v), 6)
            except (ValueError, TypeError):
                out[key] = v
        return out
    except OSError:
        return {}


def read_metrics_history(results_csv: Path, max_rows=200):
    if not results_csv.exists():
        return []
    try:
        with open(results_csv, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        history = []
        for row in rows[-max_rows:]:
            item = {}
            for k, v in row.items():
                key = k.strip()
                try:
                    item[key] = round(float(v), 6)
                except (ValueError, TypeError):
                    item[key] = v
            history.append(item)
        return history
    except OSError:
        return []


def _update_job_metrics(job, save_dir):
    results_csv = Path(save_dir) / "results.csv"
    latest = parse_results_csv(results_csv)
    history = read_metrics_history(results_csv)
    job.set_metrics({"latest": latest, "history": history})
    if latest:
        for key in ("metrics/mAP50(B)", "metrics/mAP50-95(B)", "mAP50", "mAP50-95"):
            if key in latest:
                job.progress = min(99, job.progress)
                break


def run_training_worker(app, job_id):
    """后台训练线程。"""
    with app.app_context():
        from extensions import db
        from models.training import TrainingJob, TrainingDataset

        job = TrainingJob.query.get(job_id)
        if not job:
            return
        ds = TrainingDataset.query.get(job.dataset_id)
        if not ds or ds.status != "ready" or not ds.yaml_path:
            job.status = "failed"
            job.error_message = "数据集未就绪，请先构建数据集"
            db.session.commit()
            return

        upload_root = Path(app.config["UPLOAD_FOLDER"])
        yaml_abs = upload_root / ds.yaml_path
        if not yaml_abs.exists():
            job.status = "failed"
            job.error_message = f"data.yaml 不存在: {ds.yaml_path}"
            db.session.commit()
            return

        hp = job.hyperparams_dict()
        epochs = int(hp.get("epochs", job.total_epochs or 100))
        batch = int(hp.get("batch", 8))
        imgsz = int(hp.get("imgsz", 640))
        device = str(hp.get("device", "cpu"))
        patience = int(hp.get("patience", 20))

        runs_root = upload_root / "training" / "runs" / str(job_id)
        runs_root.mkdir(parents=True, exist_ok=True)
        run_name = job.run_name or f"train_{job_id}"

        log_root = upload_root / "training" / "logs" / str(job_id)
        log_root.mkdir(parents=True, exist_ok=True)
        train_log = log_root / "train.log"

        def _log(line: str):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                train_log.open("a", encoding="utf-8").write(f"[{ts}] {line}\n")
            except OSError:
                pass

        job.status = "running"
        job.total_epochs = epochs
        job.current_epoch = 0
        job.progress = 0
        job.log_dir = str(runs_root.relative_to(upload_root)).replace("\\", "/")
        db.session.commit()
        clear_cancel(job_id)

        _log(f"训练开始: job={job_id} base={job.base_model} epochs={epochs} batch={batch} imgsz={imgsz} device={device}")
        _log(f"data.yaml: {ds.yaml_path}")

        def on_train_epoch_end(trainer):
            if is_cancelled(job_id):
                trainer.stop = True
                _log("收到取消请求，正在停止…")
                return
            with app.app_context():
                j = TrainingJob.query.get(job_id)
                if j is None:
                    return
                j.current_epoch = int(trainer.epoch) + 1
                j.progress = min(99, int(j.current_epoch / max(epochs, 1) * 100))
                _update_job_metrics(j, trainer.save_dir)
                db.session.commit()
                latest = j.metrics_dict().get("latest") or {}
                m50 = latest.get("metrics/mAP50(B)", latest.get("mAP50"))
                lbox = latest.get("train/box_loss")
                _log(f"Epoch {j.current_epoch}/{epochs} progress={j.progress}% mAP50={m50} box_loss={lbox}")

        try:
            from ultralytics import YOLO

            model = YOLO(job.base_model or "yolov8n.pt")
            model.add_callback("on_train_epoch_end", on_train_epoch_end)

            results = model.train(
                data=str(yaml_abs),
                epochs=epochs,
                imgsz=imgsz,
                batch=batch,
                device=device,
                project=str(runs_root),
                name=run_name,
                patience=patience,
                workers=0,
                exist_ok=True,
                verbose=True,
            )

            job = TrainingJob.query.get(job_id)
            if job is None:
                return

            if is_cancelled(job_id):
                job.status = "cancelled"
                job.error_message = "用户取消训练"
                _log("训练取消完成")
            else:
                save_dir = Path(results.save_dir) if results else runs_root / run_name
                best_pt = save_dir / "weights" / "best.pt"
                if best_pt.exists():
                    out_dir = upload_root / "training" / "weights" / str(job_id)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out_pt = out_dir / "best.pt"
                    shutil.copy2(best_pt, out_pt)
                    job.output_weight_path = str(out_pt.relative_to(upload_root)).replace("\\", "/")
                    job.status = "done"
                    job.progress = 100
                    job.current_epoch = epochs
                    _update_job_metrics(job, save_dir)
                    _log(f"训练完成，best.pt 已保存: {job.output_weight_path}")
                else:
                    job.status = "failed"
                    job.error_message = f"未找到 best.pt: {save_dir}"
                    _log(f"训练失败：未找到 best.pt: {save_dir}")
        except Exception as e:  # noqa: BLE001
            job = TrainingJob.query.get(job_id)
            if job:
                if is_cancelled(job_id):
                    job.status = "cancelled"
                    job.error_message = "用户取消训练"
                    _log("训练取消（异常路径）")
                else:
                    job.status = "failed"
                    job.error_message = str(e)
                    _log(f"训练异常：{e}")
        finally:
            db.session.commit()
            clear_cancel(job_id)
            _log(f"训练线程结束: status={job.status if job else 'unknown'}")


def run_validate_worker(app, job_id):
    """后台验证线程：写入 logs/<job_id>/val.log，并返回 metrics。"""
    with app.app_context():
        from extensions import db
        from models.training import TrainingJob, TrainingDataset

        upload_root = Path(app.config["UPLOAD_FOLDER"])
        log_root = upload_root / "training" / "logs" / str(job_id)
        log_root.mkdir(parents=True, exist_ok=True)
        val_log = log_root / "val.log"

        def _log(line: str):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                val_log.open("a", encoding="utf-8").write(f"[{ts}] {line}\n")
            except OSError:
                pass

        job = TrainingJob.query.get(job_id)
        if not job:
            _log("任务不存在")
            return None
        if not job.output_weight_path:
            _log("任务无训练权重，无法验证")
            return None
        ds = TrainingDataset.query.get(job.dataset_id)
        if not ds or not ds.yaml_path:
            _log("数据集 yaml 不可用")
            return None

        hp = job.hyperparams_dict()
        device = str(hp.get("device", "cpu"))
        weight_abs = upload_root / job.output_weight_path
        yaml_abs = upload_root / ds.yaml_path
        _log(f"验证开始: job={job_id} weight={job.output_weight_path} device={device}")
        try:
            metrics = validate_model(weight_abs, yaml_abs, device=device)
            _log(f"验证完成: metrics_keys={list(metrics.keys())}")
            return metrics
        except Exception as e:  # noqa: BLE001
            _log(f"验证异常：{e}")
            return None


def validate_model(weight_abs: Path, yaml_abs: Path, device="cpu"):
    from ultralytics import YOLO

    model = YOLO(str(weight_abs))
    metrics = model.val(data=str(yaml_abs), device=device, verbose=False)
    result = {}
    if hasattr(metrics, "results_dict"):
        for k, v in metrics.results_dict.items():
            try:
                result[k] = round(float(v), 6)
            except (TypeError, ValueError):
                result[k] = v
    elif hasattr(metrics, "box"):
        result["mAP50"] = round(float(metrics.box.map50), 6)
        result["mAP50-95"] = round(float(metrics.box.map), 6)
    return result


def test_predict(weight_abs: Path, image_bytes, conf=0.25):
    import base64

    import cv2
    import numpy as np
    from ultralytics import YOLO

    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")

    model = YOLO(str(weight_abs))
    results = model(img, conf=conf, verbose=False)
    annotated = results[0].plot()
    ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 92])
    img_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None

    detections = []
    if results and results[0].boxes is not None:
        names = results[0].names or {}
        for box in results[0].boxes:
            cls_id = int(box.cls.item())
            detections.append({
                "className": names.get(cls_id, str(cls_id)),
                "confidence": round(float(box.conf.item()), 4),
                "bbox": [round(float(x), 1) for x in box.xyxy[0].tolist()],
            })
    return {"imageBase64": img_b64, "detections": detections, "count": len(detections)}


def export_model(weight_abs: Path, out_dir: Path, fmt="onnx"):
    from ultralytics import YOLO

    out_dir.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(weight_abs))
    path = model.export(format=fmt)
    if path and Path(path).exists():
        dest = out_dir / Path(path).name
        if Path(path).resolve() != dest.resolve():
            shutil.copy2(path, dest)
        return dest
    raise FileNotFoundError(f"导出失败: {fmt}")


def deploy_to_ai_model(app, job, model_name, model_key, category, description=""):
    """将训练权重注册到 ai_model 表。"""
    from extensions import db
    from models import AiModel

    if not job.output_weight_path:
        raise ValueError("训练任务尚无可用权重")

    upload_root = Path(app.config["UPLOAD_FOLDER"])
    src = upload_root / job.output_weight_path
    if not src.exists():
        raise ValueError("权重文件不存在")

    if AiModel.query.filter_by(model_key=model_key).first():
        raise ValueError(f"模型标识 {model_key} 已存在")

    dest_dir = Path(app.config["MODEL_FOLDER"]) / model_key
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "best.pt"
    shutil.copy2(src, dest)

    rel = str(dest.relative_to(upload_root)).replace("\\", "/")
    m = AiModel(
        model_name=model_name,
        model_key=model_key,
        category=category or "自定义训练",
        task="object-detection",
        library="ultralytics",
        version="v1",
        file_path=rel,
        file_size=dest.stat().st_size,
        description=description or f"训练任务 #{job.id} 产出",
        status="0",
    )
    db.session.add(m)
    db.session.flush()
    job.output_model_id = m.id
    db.session.commit()
    return m
