"""数据集标注质量分析。"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import cv2

from services.dataset_annotation import ensure_annotation_dirs
from services.training import IMG_EXTENSIONS, parse_data_yaml, detect_dataset_format

SMALL_AREA = 0.005   # 0.5%
LARGE_AREA = 0.10    # 10%


def _resolve_yaml_root(yaml_path: Path) -> Path:
    data = parse_data_yaml(yaml_path)
    root = yaml_path.parent
    if data.get("path"):
        p = Path(data["path"])
        if not p.is_absolute():
            p = (root / p).resolve()
        if p.is_dir():
            root = p
    return root


def _collect_yolo_locations(root: Path) -> list[tuple[Path, Path, str]]:
    """返回 (images_dir, labels_dir, tag) 列表。"""
    locs: list[tuple[Path, Path, str]] = []
    if (root / "images" / "train").is_dir():
        for split in ("train", "val", "test"):
            img_d = root / "images" / split
            lbl_d = root / "labels" / split
            if img_d.is_dir():
                locs.append((img_d, lbl_d if lbl_d.is_dir() else img_d, split))
    elif (root / "images").is_dir():
        lbl_d = root / "labels" if (root / "labels").is_dir() else root / "images"
        locs.append((root / "images", lbl_d, "flat"))
    elif any(root.glob("*.jpg")) or any(root.glob("*.png")):
        locs.append((root, root, "mixed"))
    return locs


def _image_size(path: Path) -> tuple[int, int] | None:
    img = cv2.imread(str(path))
    if img is None:
        return None
    h, w = img.shape[:2]
    return w, h


def _parse_yolo_boxes(lbl_path: Path) -> list[tuple[int, float, float, float, float]]:
    if not lbl_path.is_file():
        return []
    boxes = []
    for line in lbl_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        try:
            cls_id = int(float(parts[0]))
            cx, cy, bw, bh = map(float, parts[1:5])
        except ValueError:
            continue
        if bw <= 0 or bh <= 0:
            continue
        boxes.append((cls_id, cx, cy, bw, bh))
    return boxes


def analyze_dataset_quality(
    source_dir: Path,
    *,
    class_names: list[str] | None = None,
    yaml_path: Path | None = None,
) -> dict:
    """分析 YOLO 风格数据集标注质量。"""
    if not source_dir.exists():
        raise ValueError(f"数据目录不存在: {source_dir}")

    root = source_dir
    if yaml_path and yaml_path.is_file():
        root = _resolve_yaml_root(yaml_path)
        if not class_names:
            data = parse_data_yaml(yaml_path)
            class_names = data.get("names") or []

    class_names = list(class_names or [])
    detected = detect_dataset_format(source_dir if yaml_path is None else root)
    locs = _collect_yolo_locations(root)
    if not locs:
        ensure_annotation_dirs(source_dir)
        locs = _collect_yolo_locations(source_dir)

    all_images: dict[str, Path] = {}
    all_labels: dict[str, Path] = {}
    split_tags: dict[str, str] = {}

    for img_dir, lbl_dir, tag in locs:
        for img in img_dir.iterdir():
            if not img.is_file() or img.suffix.lower() not in IMG_EXTENSIONS:
                continue
            key = f"{tag}:{img.stem}" if tag else img.stem
            all_images[key] = img
            split_tags[key] = tag
        for lbl in lbl_dir.glob("*.txt"):
            if not lbl.is_file():
                continue
            key = f"{tag}:{lbl.stem}" if tag else lbl.stem
            all_labels[key] = lbl

    image_keys = set(all_images)
    label_keys = set(all_labels)
    matched = image_keys & label_keys
    orphan_images = image_keys - label_keys
    orphan_labels = label_keys - image_keys

    total_boxes = 0
    empty_labels = 0
    class_counts: Counter[int] = Counter()
    widths: list[int] = []
    heights: list[int] = []
    areas: list[float] = []
    aspects: list[float] = []
    small_count = 0
    large_count = 0
    invalid_boxes = 0

    for key in matched:
        img_path = all_images[key]
        lbl_path = all_labels[key]
        size = _image_size(img_path)
        if size:
            widths.append(size[0])
            heights.append(size[1])
        boxes = _parse_yolo_boxes(lbl_path)
        if not boxes:
            empty_labels += 1
            continue
        for cls_id, _cx, _cy, bw, bh in boxes:
            total_boxes += 1
            class_counts[cls_id] += 1
            area = bw * bh
            areas.append(area)
            aspects.append(bw / bh if bh > 0 else 0)
            if area < SMALL_AREA:
                small_count += 1
            if area > LARGE_AREA:
                large_count += 1
            if cls_id < 0 or (class_names and cls_id >= len(class_names)):
                invalid_boxes += 1

    # 仅有标签无图的孤立标签中的框也计入标签文件数
    total_images = len(all_images)
    total_label_files = len(all_labels)

    dist = []
    max_count = max(class_counts.values()) if class_counts else 0
    for cls_id, cnt in sorted(class_counts.items()):
        if 0 <= cls_id < len(class_names):
            name = class_names[cls_id]
        else:
            name = f"class_{cls_id}"
        dist.append({
            "classId": cls_id,
            "name": name,
            "count": cnt,
            "percent": round(cnt / total_boxes * 100, 2) if total_boxes else 0,
            "barPercent": round(cnt / max_count * 100, 2) if max_count else 0,
        })

    def _avg(vals):
        return round(sum(vals) / len(vals), 2) if vals else 0

    def _rng(vals):
        return {"min": min(vals), "max": max(vals)} if vals else {"min": 0, "max": 0}

    w_rng, h_rng = _rng(widths), _rng(heights)

    return {
        "sourceDir": str(source_dir),
        "analyzedRoot": str(root),
        "detectedFormat": detected,
        "classNames": class_names,
        "overview": {
            "totalImages": total_images,
            "totalLabels": total_label_files,
            "totalBoxes": total_boxes,
            "classCount": len(class_counts) if class_counts else len(class_names),
            "matchedPairs": len(matched),
            "orphanImages": len(orphan_images),
            "orphanLabels": len(orphan_labels),
            "emptyLabels": empty_labels,
            "invalidClassIds": invalid_boxes,
        },
        "classDistribution": dist,
        "imageSize": {
            "avgWidth": _avg(widths),
            "avgHeight": _avg(heights),
            "widthRange": w_rng,
            "heightRange": h_rng,
        },
        "boxStats": {
            "avgAreaRatio": round(_avg(areas) * 100, 2),
            "avgAspectRatio": _avg(aspects),
            "smallObjects": small_count,
            "largeObjects": large_count,
            "smallThresholdPercent": SMALL_AREA * 100,
            "largeThresholdPercent": LARGE_AREA * 100,
        },
        "issues": _build_issues(
            len(orphan_images), len(orphan_labels), empty_labels, invalid_boxes, total_images,
        ),
    }


def _build_issues(orphan_img, orphan_lbl, empty_lbl, invalid_cls, total_img) -> list[dict]:
    issues = []
    if orphan_img:
        issues.append({"level": "warning", "text": f"发现 {orphan_img} 张孤立图片（无对应标签文件）"})
    if orphan_lbl:
        issues.append({"level": "warning", "text": f"发现 {orphan_lbl} 个孤立标签（无对应图片）"})
    if empty_lbl:
        issues.append({"level": "info", "text": f"发现 {empty_lbl} 个空标签文件（无有效标注框）"})
    if invalid_cls:
        issues.append({"level": "error", "text": f"发现 {invalid_cls} 个标注框类别 ID 超出 classNames 范围"})
    if total_img == 0:
        issues.append({"level": "error", "text": "未找到任何图片，请检查目录结构或先上传/抽帧"})
    if not issues:
        issues.append({"level": "success", "text": "未发现明显配对问题，标注质量良好"})
    return issues
