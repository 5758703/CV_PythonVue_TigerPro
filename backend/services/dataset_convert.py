"""数据集格式转换（LabelMe / VOC / YOLO / COCO）。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from services.dataset_annotation import ensure_annotation_dirs, write_yolo_labels
from services.training import (
    IMG_EXTENSIONS,
    parse_voc,
    parse_labelme,
    voc_to_yolo,
    _collect_labelme_pairs,
    _find_image,
    parse_data_yaml,
    write_data_yaml,
)

CONVERT_TYPES = {
    "labelme_to_yolo": {
        "label": "LabelMe → YOLO",
        "summary": "将 LabelMe JSON 矩形/多边形标注转为 YOLO TXT（images/ + labels/）",
        "needsClassNames": False,
    },
    "voc_to_yolo": {
        "label": "Pascal VOC → YOLO",
        "summary": "将 VOC XML 标注转为 YOLO TXT（支持扁平或 Annotations+JPEGImages）",
        "needsClassNames": True,
    },
    "yolo_to_voc": {
        "label": "YOLO → Pascal VOC",
        "summary": "将 YOLO 标签导出为 VOC XML（输出到 export/voc/）",
        "needsClassNames": True,
    },
    "yolo_remap": {
        "label": "YOLO 类别重映射",
        "summary": "按类别名称映射表重写 labels/*.txt 中的 class_id",
        "needsClassNames": True,
        "needsClassMap": True,
    },
    "yolo_to_coco": {
        "label": "YOLO → COCO JSON",
        "summary": "将 YOLO 数据集导出为 COCO instances JSON",
        "needsClassNames": True,
    },
}


def get_convert_types() -> list[dict]:
    return [{"value": k, **v} for k, v in CONVERT_TYPES.items()]


def _yolo_pairs(source_dir: Path) -> list[tuple[Path, Path]]:
    pairs = []
    img_root = source_dir / "images" if (source_dir / "images").is_dir() else source_dir
    lbl_root = source_dir / "labels" if (source_dir / "labels").is_dir() else source_dir
    if (source_dir / "images" / "train").is_dir():
        for split in ("train", "val", "test"):
            idir = source_dir / "images" / split
            ldir = source_dir / "labels" / split
            if not idir.is_dir():
                continue
            for img in sorted(idir.iterdir()):
                if img.suffix.lower() not in IMG_EXTENSIONS:
                    continue
                lbl = ldir / f"{img.stem}.txt" if ldir.is_dir() else None
                if lbl and lbl.is_file():
                    pairs.append((img, lbl))
    else:
        for img in sorted(img_root.iterdir()):
            if not img.is_file() or img.suffix.lower() not in IMG_EXTENSIONS:
                continue
            lbl = lbl_root / f"{img.stem}.txt"
            if lbl.is_file():
                pairs.append((img, lbl))
    return pairs


def _voc_xml_files(source_dir: Path) -> list[tuple[Path, Path | None]]:
    """返回 (xml_path, images_dir_hint)。"""
    items = []
    if (source_dir / "Annotations").is_dir():
        img_dir = None
        for name in ("JPEGImages", "Images", "images"):
            if (source_dir / name).is_dir():
                img_dir = source_dir / name
                break
        for xml in sorted((source_dir / "Annotations").glob("*.xml")):
            items.append((xml, img_dir))
    for xml in sorted(source_dir.glob("*.xml")):
        items.append((xml, source_dir))
    return items


def _write_voc_xml(out_path: Path, stem: str, img_w: int, img_h: int, class_names: list[str], boxes: list):
    import xml.etree.ElementTree as ET

    root = ET.Element("annotation")
    ET.SubElement(root, "folder").text = out_path.parent.name
    fn = ET.SubElement(root, "filename")
    fn.text = f"{stem}.jpg"
    sz = ET.SubElement(root, "size")
    ET.SubElement(sz, "width").text = str(img_w)
    ET.SubElement(sz, "height").text = str(img_h)
    ET.SubElement(sz, "depth").text = "3"
    for cls_id, cx, cy, bw, bh in boxes:
        xmin = (cx - bw / 2) * img_w
        ymin = (cy - bh / 2) * img_h
        xmax = (cx + bw / 2) * img_w
        ymax = (cy + bh / 2) * img_h
        obj = ET.SubElement(root, "object")
        name = class_names[cls_id] if 0 <= cls_id < len(class_names) else str(cls_id)
        ET.SubElement(obj, "name").text = name
        bb = ET.SubElement(obj, "bndbox")
        ET.SubElement(bb, "xmin").text = str(int(round(xmin)))
        ET.SubElement(bb, "ymin").text = str(int(round(ymin)))
        ET.SubElement(bb, "xmax").text = str(int(round(xmax)))
        ET.SubElement(bb, "ymax").text = str(int(round(ymax)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(str(out_path), encoding="utf-8", xml_declaration=True)


def convert_labelme_to_yolo(source_dir: Path, target_dir: Path, class_names: list[str] | None) -> dict:
    pairs = _collect_labelme_pairs(source_dir)
    if not pairs:
        raise ValueError("未找到 LabelMe 配对（图片 + 含 shapes 的 .json）")
    all_labels = set()
    for _, jp in pairs:
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
            for s in data.get("shapes") or []:
                lb = (s.get("label") or "").strip()
                if lb:
                    all_labels.add(lb)
        except (OSError, json.JSONDecodeError):
            pass
    if not class_names:
        class_names = sorted(all_labels)
    if not class_names:
        raise ValueError("无法确定类别，请在数据集中配置 classNames")

    img_dir, lbl_dir = ensure_annotation_dirs(target_dir)
    ok, skip = 0, 0
    for img_src, json_path in pairs:
        try:
            img_w, img_h, boxes, _found = parse_labelme(json_path, class_names)
        except (OSError, json.JSONDecodeError):
            skip += 1
            continue
        if img_w <= 0 or img_h <= 0:
            import cv2
            arr = cv2.imread(str(img_src))
            if arr is None:
                skip += 1
                continue
            img_h, img_w = arr.shape[:2]
        if not boxes:
            skip += 1
            continue
        stem = img_src.stem
        dst_img = img_dir / img_src.name
        if not dst_img.exists() or dst_img.resolve() != img_src.resolve():
            shutil.copy2(img_src, dst_img)
        yolo_boxes = []
        for cls_id, xmin, ymin, xmax, ymax in boxes:
            cx, cy, bw, bh = voc_to_yolo(cls_id, xmin, ymin, xmax, ymax, img_w, img_h)
            yolo_boxes.append({
                "classId": cls_id,
                "cx": cx, "cy": cy, "w": bw, "h": bh,
            })
        write_yolo_labels(lbl_dir / f"{stem}.txt", yolo_boxes, class_names)
        ok += 1
    return {"converted": ok, "skipped": skip, "classNames": class_names, "targetDir": str(target_dir)}


def convert_voc_to_yolo(source_dir: Path, target_dir: Path, class_names: list[str]) -> dict:
    if not class_names:
        raise ValueError("VOC 转 YOLO 需要配置类别名称 classNames")
    xml_items = _voc_xml_files(source_dir)
    if not xml_items:
        raise ValueError("未找到 VOC XML 标注文件")
    img_dir, lbl_dir = ensure_annotation_dirs(target_dir)
    ok, skip = 0, 0
    for xml_path, img_hint in xml_items:
        stem = xml_path.stem
        img_src = _find_image(stem, img_hint or source_dir, source_dir / "images", source_dir)
        if img_src is None:
            skip += 1
            continue
        try:
            img_w, img_h, boxes, _found = parse_voc(xml_path, class_names)
        except Exception:  # noqa: BLE001
            skip += 1
            continue
        if not boxes:
            skip += 1
            continue
        dst_img = img_dir / img_src.name
        if not dst_img.exists() or dst_img.resolve() != img_src.resolve():
            shutil.copy2(img_src, dst_img)
        yolo_boxes = []
        for cls_id, xmin, ymin, xmax, ymax in boxes:
            cx, cy, bw, bh = voc_to_yolo(cls_id, xmin, ymin, xmax, ymax, img_w, img_h)
            yolo_boxes.append({"classId": cls_id, "cx": cx, "cy": cy, "w": bw, "h": bh})
        write_yolo_labels(lbl_dir / f"{stem}.txt", yolo_boxes, class_names)
        ok += 1
    return {"converted": ok, "skipped": skip, "classNames": class_names, "targetDir": str(target_dir)}


def convert_yolo_to_voc(source_dir: Path, export_dir: Path, class_names: list[str]) -> dict:
    if not class_names:
        raise ValueError("YOLO 转 VOC 需要配置类别名称")
    pairs = _yolo_pairs(source_dir)
    if not pairs:
        raise ValueError("未找到 YOLO 图片与标签配对")
    ann_dir = export_dir / "Annotations"
    img_dir = export_dir / "JPEGImages"
    ann_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    import cv2
    for img_path, lbl_path in pairs:
        arr = cv2.imread(str(img_path))
        if arr is None:
            continue
        h, w = arr.shape[:2]
        boxes = []
        for line in lbl_path.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            try:
                cls_id = int(float(parts[0]))
                cx, cy, bw, bh = map(float, parts[1:5])
                boxes.append((cls_id, cx, cy, bw, bh))
            except ValueError:
                continue
        if not boxes:
            continue
        shutil.copy2(img_path, img_dir / img_path.name)
        _write_voc_xml(ann_dir / f"{img_path.stem}.xml", img_path.stem, w, h, class_names, boxes)
        ok += 1
    return {"converted": ok, "exportDir": str(export_dir)}


def remap_yolo_classes(source_dir: Path, class_names: list[str], class_map: list[dict]) -> dict:
    """class_map: [{ name: 'old', id: 0 }, ...] 将旧名称映射到新 id。"""
    if not class_names:
        raise ValueError("请配置目标 classNames")
    name_to_new = {}
    for item in class_map or []:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        try:
            new_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        name_to_new[name] = new_id

    old_id_to_name = {i: n for i, n in enumerate(class_names)}
    # 若映射表按名称，需从旧标签 id 反查名称；这里支持额外 oldNames 列表
    pairs = _yolo_pairs(source_dir)
    if not pairs:
        raise ValueError("未找到 YOLO 标签文件")
    updated = 0
    for _img, lbl_path in pairs:
        new_lines = []
        changed = False
        for line in lbl_path.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            try:
                cls_id = int(float(parts[0]))
                coords = parts[1:5]
            except ValueError:
                continue
            old_name = old_id_to_name.get(cls_id, str(cls_id))
            if old_name in name_to_new:
                new_id = name_to_new[old_name]
                changed = True
            else:
                new_id = cls_id
            new_lines.append(f"{new_id} {' '.join(coords)}")
        if changed:
            if new_lines:
                lbl_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            elif lbl_path.is_file():
                lbl_path.unlink()
            updated += 1
    return {"updatedFiles": updated, "classMap": name_to_new}


def convert_yolo_to_coco(source_dir: Path, export_path: Path, class_names: list[str]) -> dict:
    if not class_names:
        raise ValueError("YOLO 转 COCO 需要配置类别名称")
    pairs = _yolo_pairs(source_dir)
    if not pairs:
        raise ValueError("未找到 YOLO 配对")
    import cv2
    images = []
    annotations = []
    categories = [{"id": i, "name": n, "supercategory": "object"} for i, n in enumerate(class_names)]
    ann_id = 1
    for img_id, (img_path, lbl_path) in enumerate(pairs, start=1):
        arr = cv2.imread(str(img_path))
        if arr is None:
            continue
        h, w = arr.shape[:2]
        images.append({
            "id": img_id,
            "file_name": img_path.name,
            "width": w,
            "height": h,
        })
        for line in lbl_path.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            try:
                cls_id = int(float(parts[0]))
                cx, cy, bw, bh = map(float, parts[1:5])
            except ValueError:
                continue
            if cls_id < 0 or cls_id >= len(class_names):
                continue
            px_w, px_h = bw * w, bh * h
            px_x = (cx - bw / 2) * w
            px_y = (cy - bh / 2) * h
            annotations.append({
                "id": ann_id,
                "image_id": img_id,
                "category_id": cls_id,
                "bbox": [round(px_x, 2), round(px_y, 2), round(px_w, 2), round(px_h, 2)],
                "area": round(px_w * px_h, 2),
                "iscrowd": 0,
            })
            ann_id += 1
    coco = {"images": images, "annotations": annotations, "categories": categories}
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(json.dumps(coco, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "images": len(images),
        "annotations": len(annotations),
        "exportPath": str(export_path),
    }


def run_convert(
    convert_type: str,
    source_dir: Path,
    target_dir: Path,
    *,
    class_names: list[str] | None = None,
    class_map: list[dict] | None = None,
    export_dir: Path | None = None,
) -> dict:
    if convert_type not in CONVERT_TYPES:
        raise ValueError(f"不支持的转换类型: {convert_type}")
    if convert_type == "labelme_to_yolo":
        return convert_labelme_to_yolo(source_dir, target_dir, class_names)
    if convert_type == "voc_to_yolo":
        return convert_voc_to_yolo(source_dir, target_dir, class_names or [])
    if convert_type == "yolo_to_voc":
        out = export_dir or (target_dir / "export" / "voc")
        return convert_yolo_to_voc(source_dir, out, class_names or [])
    if convert_type == "yolo_remap":
        return remap_yolo_classes(source_dir, class_names or [], class_map or [])
    if convert_type == "yolo_to_coco":
        out = export_dir or (target_dir / "export" / "instances.json")
        return convert_yolo_to_coco(source_dir, out, class_names or [])
    raise ValueError(f"未实现的转换: {convert_type}")
